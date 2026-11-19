"""Orquestrador do Fala, Lavoura!

Fluxo de uma pergunta:

  áudio? ──► transcrição (Gemini multimodal)
  emergência? ──► resposta fixa + fila do técnico (sem LLM)
  foto? ──► descrição de sintomas (Gemini visão)
  agente ReAct (Gemini + tool calling)
      ├─ buscar_conhecimento  (RAG híbrido)
      ├─ previsao_do_tempo    (Open-Meteo ao vivo)
      ├─ fase_da_lavoura      (FAO-56, código)
      └─ necessidade_de_agua  (balanço hídrico, código)
  guardrail de saída (regex: dose / princípio ativo)
  Fiscal da Roça (LLM verificador, saída estruturada)
  semáforo de confiança ──► fila do técnico quando precisa de humano
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from . import agronomia, clima, config, fila, guardrails, prompts
from .conhecimento import Buscador, formatar_para_llm
from .texto import normalizar, sem_emojis


# ---------------------------------------------------------------------------
# Estruturas de dados
# ---------------------------------------------------------------------------
@dataclass
class Perfil:
    cidade: str = "Campinas, SP"
    cultura: str = "milho"
    data_plantio: str = ""
    dias_informados: int | None = None   # alternativa à data (útil nos testes)
    area_m2: float = 0
    sistema: str = "gotejamento"
    tratamento: str = "agricultor(a)"

    @property
    def dias_apos_plantio(self) -> int | None:
        if self.dias_informados is not None:
            return self.dias_informados
        if self.data_plantio:
            try:
                return agronomia.dias_desde(self.data_plantio)
            except ValueError:
                return None
        return None

    @property
    def cultura_chave(self) -> str:
        return normalizar(self.cultura)

    def como_dict(self) -> dict:
        return {"cidade": self.cidade, "cultura": self.cultura, "dias_apos_plantio": self.dias_apos_plantio,
                "area_m2": self.area_m2, "sistema": self.sistema}

    def texto(self) -> str:
        dap = self.dias_apos_plantio
        return "\n".join([
            f"- Chame o agricultor de: {self.tratamento}",
            f"- Cultura: {self.cultura}",
            f"- Município: {self.cidade}",
            f"- Dias desde o plantio: {dap if dap is not None else 'não informado'}",
            f"- Área: {self.area_m2:g} m²" if self.area_m2 else "- Área: não informada",
            f"- Irrigação: {self.sistema}",
        ])


@dataclass
class Passo:
    etapa: str
    detalhe: str


@dataclass
class RespostaFala:
    texto: str
    semaforo: str                      # verde, amarelo, vermelho, cinza (sem IA)
    motivo: str
    rastro: list[Passo] = field(default_factory=list)
    fontes: list[str] = field(default_factory=list)
    ficha: dict | None = None
    transcricao: str = ""
    descricao_imagem: str = ""
    chamadas_llm: int = 0
    segundos: float = 0.0
    flags: set = field(default_factory=set)
    avaliacao_fiscal: dict | None = None


class AvaliacaoFiscal(BaseModel):
    """Saída estruturada do Fiscal da Roça."""
    afirmacoes_sem_apoio: list[str] = Field(default_factory=list, description="Fatos/recomendações da resposta sem apoio nas evidências")
    numeros_divergentes: list[str] = Field(default_factory=list, description="Números da resposta diferentes dos das ferramentas")
    cita_produto_ou_dose: bool = Field(description="A resposta cita produto químico, princípio ativo ou dose?")
    risco: Literal["baixo", "medio", "alto"] = Field(description="Risco de seguir a resposta sem técnico")
    precisa_tecnico: bool = Field(description="O caso precisa de um técnico humano?")
    motivo: str = Field(description="Explicação curta da avaliação, em português")


def _texto(msg) -> str:
    return str(getattr(msg, "text", "") or "").strip()


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------
class FalaLavoura:
    def __init__(self, buscador: Buscador | None = None):
        self.buscador = buscador or Buscador()
        self.llm = self.llm_fiscal = None
        self.limiter = None
        if config.tem_chave():
            from langchain_core.rate_limiters import InMemoryRateLimiter
            from langchain_google_genai import ChatGoogleGenerativeAI

            self.limiter = InMemoryRateLimiter(requests_per_second=config.REQUISICOES_POR_MINUTO / 60,
                                               check_every_n_seconds=0.2, max_bucket_size=1)
            comum = dict(google_api_key=config.GOOGLE_API_KEY, rate_limiter=self.limiter, max_retries=1, timeout=60)
            self.llm = ChatGoogleGenerativeAI(model=config.MODELO_CHAT, temperature=0.3, **comum)
            self.llm_fiscal = ChatGoogleGenerativeAI(model=config.MODELO_FISCAL, temperature=0.0, **comum)
            self.llm_reserva = ChatGoogleGenerativeAI(model=config.MODELO_RESERVA, temperature=0.3, **comum)

    @property
    def tem_ia(self) -> bool:
        return self.llm is not None

    def _invocar(self, estado: dict, msgs, ferramentas=None, rastro: list | None = None):
        """Chama o modelo ativo; se ele estiver sobrecarregado (503) ou sem cota (429),
        troca para o modelo reserva e mantém a troca até o fim da pergunta."""
        def chamar(llm):
            return (llm.bind_tools(ferramentas) if ferramentas else llm).invoke(msgs)
        try:
            return chamar(estado["llm"])
        except Exception as erro:
            transitorio = any(c in str(erro) for c in ("503", "504", "UNAVAILABLE", "DEADLINE", "429", "RESOURCE_EXHAUSTED", "overloaded", "imeout"))
            if not transitorio or estado["llm"] is self.llm_reserva:
                raise
            estado["llm"] = self.llm_reserva
            if rastro is not None:
                rastro.append(Passo("modelo reserva", f"{config.MODELO_CHAT} indisponível; usando {config.MODELO_RESERVA}"))
            return chamar(estado["llm"])

    # ===== ferramentas que o agente pode chamar =====
    def _ferramentas(self, perfil: Perfil, coleta: dict, rastro: list[Passo]):
        from langchain_core.tools import tool

        buscador = self.buscador

        @tool
        def buscar_conhecimento(consulta: str, cultura: str = "") -> str:
            """Busca trechos nas fichas técnicas (pragas, doenças, água, solo, clima extremo,
            agrotóxicos, políticas públicas, saberes tradicionais). Use termos técnicos e populares.
            'cultura' é opcional (milho, feijao, mandioca, tomate, alface)."""
            resultados, diag = buscador.buscar(consulta, cultura or perfil.cultura_chave)
            for r in resultados:
                coleta["trechos"][r.trecho.id] = r.trecho.texto
            coleta["forca"].append(diag["forca_evidencia"])
            termos = f" · dicionário: {', '.join(diag['termos_do_dicionario'])}" if diag["termos_do_dicionario"] else ""
            rastro.append(Passo("buscar_conhecimento",
                                f"“{consulta}” → {', '.join(r.trecho.id for r in resultados)} "
                                f"(evidência {diag['forca_evidencia']}, modo {diag['modo']}{termos})"))
            return formatar_para_llm(resultados, diag)

        @tool
        def previsao_do_tempo(cidade: str = "") -> str:
            """Previsão do tempo real dos próximos 7 dias (chuva, temperatura, ET0) e alertas
            de geada, calor, chuva forte, vento e clima favorável a doenças."""
            prev = clima.previsao(cidade or perfil.cidade)
            coleta["ferramentas"]["previsao_do_tempo"] = prev
            alertas = ", ".join(a["tipo"] for a in prev["alertas"]) or "nenhum"
            rastro.append(Passo("previsao_do_tempo", f"{prev['local']} · alertas: {alertas}"
                                + (" · ATENÇÃO: DADOS DE EXEMPLO" if prev.get("dados_de_exemplo") else "")))
            return clima.resumo_para_llm(prev)

        @tool
        def fase_da_lavoura(cultura: str = "", dias_apos_plantio: int = -1) -> str:
            """Diz em que fase a cultura está (e se é fase crítica para água) a partir dos dias desde o plantio."""
            dap = dias_apos_plantio if dias_apos_plantio >= 0 else perfil.dias_apos_plantio
            if dap is None:
                return "Data de plantio não informada. Peça ao agricultor para preencher no app."
            res = agronomia.fase_da_cultura(cultura or perfil.cultura_chave, dap)
            coleta["ferramentas"]["fase_da_lavoura"] = res
            rastro.append(Passo("fase_da_lavoura", f"{res['cultura']}, {dap} dias → {res['fase']} ({res['descricao_fase']})"))
            return json.dumps(res, ensure_ascii=False)

        @tool
        def necessidade_de_agua(cultura: str = "", dias_apos_plantio: int = -1, area_m2: float = 0, sistema: str = "") -> str:
            """Calcula quanta água a lavoura precisa nos próximos 7 dias (balanço hídrico FAO-56),
            descontando a chuva prevista. Devolve mm, litros por m² e litros totais para a área."""
            dap = dias_apos_plantio if dias_apos_plantio >= 0 else perfil.dias_apos_plantio
            if dap is None:
                return "Data de plantio não informada. Peça ao agricultor para preencher no app."
            prev = coleta["ferramentas"].get("previsao_do_tempo") or clima.previsao(perfil.cidade)
            dias = [{"data": d["data"], "et0_mm": d["et0_mm"], "chuva_mm": d["chuva_mm"]} for d in prev["dias"]]
            res = agronomia.balanco_hidrico(cultura or perfil.cultura_chave, dap, dias,
                                           area_m2 or perfil.area_m2, sistema or perfil.sistema)
            if prev.get("dados_de_exemplo"):
                res["aviso"] = prev["aviso"]
            coleta["ferramentas"]["necessidade_de_agua"] = res
            rastro.append(Passo("necessidade_de_agua",
                                f"estado: {res['estado_da_lavoura']} · irrigar {res['irrigacao_necessaria_mm']} mm "
                                f"({res.get('litros_total_no_periodo', '?')} L na área) · chuva prevista {res['chuva_prevista_total_mm']} mm"))
            sem_dias = {k: v for k, v in res.items() if k != "dias"}
            sem_dias["dias_com_rega"] = [d["data"] for d in res["dias"] if d["irrigar_mm"] > 0]
            return json.dumps(sem_dias, ensure_ascii=False)

        return [buscar_conhecimento, previsao_do_tempo, fase_da_lavoura, necessidade_de_agua]

    # ===== pergunta principal =====
    def perguntar(self, pergunta: str, perfil: Perfil, historico: list[dict] | None = None,
                  imagem: str | None = None, audio: str | None = None, modo: str = "agricultor") -> RespostaFala:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        inicio = time.time()
        rastro: list[Passo] = []
        coleta = {"trechos": {}, "ferramentas": {}, "forca": []}
        chamadas = 0
        transcricao = descricao = ""
        pergunta = (pergunta or "").strip()

        if audio and self.tem_ia:
            self.limiter.acquire()
            from . import percepcao
            transcricao = percepcao.transcrever_audio(audio)
            chamadas += 1
            rastro.append(Passo("transcrição do áudio", transcricao))
            pergunta = f"{pergunta} {transcricao}".strip()

        # LGPD: CPF, telefone e e-mail digitados pelo usuário são mascarados ANTES de qualquer
        # envio à API (e não só na fila do técnico). Nomes e endereços não são detectados.
        anonimizada = guardrails.anonimizar(pergunta)
        if anonimizada != pergunta:
            rastro.append(Passo("privacidade", "CPF, telefone ou e-mail mascarado antes de enviar ao modelo"))
            pergunta = anonimizada

        if not pergunta and not imagem:
            return RespostaFala("Me conta o que está acontecendo na roça: pode escrever, gravar um áudio ou mandar uma foto. ",
                                "cinza", "pergunta vazia")

        # 1) Emergência de saúde: resposta fixa, sem depender do modelo
        if guardrails.detectar_emergencia(pergunta):
            rastro.append(Passo("guardrail de entrada", "sinais de intoxicação: resposta fixa de emergência, sem LLM"))
            ficha = fila.registrar(pergunta, perfil.como_dict(), "vermelho", "Emergência: possível intoxicação por agrotóxico",
                                   guardrails.RESPOSTA_EMERGENCIA, ["pragas_e_agrotoxicos#intoxicacao-por-agrotoxico-o-que-fazer"])
            return RespostaFala(guardrails.RESPOSTA_EMERGENCIA, "vermelho", "Emergência de saúde: protocolo fixo acionado",
                                rastro, ["pragas_e_agrotoxicos#intoxicacao-por-agrotoxico-o-que-fazer"], ficha,
                                transcricao, segundos=round(time.time() - inicio, 1), chamadas_llm=chamadas, flags={"emergencia"})

        flags = guardrails.classificar_pergunta(pergunta)
        if flags:
            rastro.append(Passo("guardrail de entrada", "temas sensíveis: " + ", ".join(sorted(flags))))

        if not self.tem_ia:
            return self._sem_ia(pergunta, perfil, rastro, flags, inicio)

        # 2) Foto vira descrição de sintomas (percepção), não diagnóstico
        if imagem:
            self.limiter.acquire()
            from . import percepcao
            descricao = percepcao.descrever_imagem(imagem)
            chamadas += 1
            rastro.append(Passo("descrição da foto", descricao))

        mensagem = pergunta or "Olha essa foto da minha planta. O que pode ser?"
        if descricao:
            mensagem += f"\n\n[Descrição automática da foto enviada pelo agricultor]\n{descricao}"

        extras = "\n".join(guardrails.INSTRUCOES_POR_FLAG[f] for f in sorted(flags))
        cfg_modo = prompts.MODOS.get(modo, prompts.MODOS["agricultor"])
        sistema = prompts.SISTEMA_AGENTE.format(
            cultura_txt=f"uma lavoura de {perfil.cultura}", perfil=perfil.texto(),
            instrucoes_extras=f"ATENÇÃO ESPECIAL NESTA PERGUNTA:\n{extras}" if extras else "",
            modo_txt=cfg_modo["modo_txt"], formato=cfg_modo["formato"])

        msgs = [SystemMessage(sistema)]
        for m in (historico or [])[-6:]:
            conteudo = m.get("content")
            if isinstance(conteudo, str) and conteudo.strip():
                limpo = guardrails.anonimizar(conteudo.split("\n\n---\n")[0])  # tira o rodapé do semáforo
                msgs.append(HumanMessage(limpo) if m.get("role") == "user" else AIMessage(limpo))
        msgs.append(HumanMessage(mensagem))

        # 3) Loop do agente (ReAct com tool calling nativo do Gemini)
        ferramentas = self._ferramentas(perfil, coleta, rastro)
        por_nome = {f.name: f for f in ferramentas}
        estado = {"llm": self.llm}
        ai = None
        for _ in range(config.MAX_PASSOS_AGENTE):
            ai = self._invocar(estado, msgs, ferramentas, rastro)
            chamadas += 1
            msgs.append(ai)
            if not ai.tool_calls:
                break
            for chamada in ai.tool_calls:
                try:
                    saida = por_nome[chamada["name"]].invoke(chamada["args"])
                except Exception as erro:  # ferramenta falhou: o agente fica sabendo e segue
                    saida = f"Erro ao usar a ferramenta: {erro}"
                    rastro.append(Passo(f"falha em {chamada['name']}", str(erro)))
                msgs.append(ToolMessage(content=str(saida), tool_call_id=chamada["id"]))
        if ai is None or ai.tool_calls or not _texto(ai):
            msgs.append(HumanMessage("Agora responda ao agricultor no formato pedido, sem chamar mais ferramentas."))
            ai = self._invocar(estado, msgs, ferramentas, rastro)
            chamadas += 1
        resposta = _texto(ai)

        # 4) Guardrail de grounding: se o agente pulou a base, forçamos a busca
        if not coleta["trechos"]:
            rastro.append(Passo("grounding forçado", "o agente respondeu sem consultar a base; busquei e pedi para refazer"))
            resultados, diag = self.buscador.buscar(f"{pergunta} {descricao}", perfil.cultura_chave)
            for r in resultados:
                coleta["trechos"][r.trecho.id] = r.trecho.texto
            coleta["forca"].append(diag["forca_evidencia"])
            ai = self._invocar(estado, msgs + [HumanMessage(
                "Você respondeu sem consultar a base. Refaça a resposta combinando os trechos abaixo com os NÚMEROS que as "
                "ferramentas já devolveram (chuva, litros, fase), que devem continuar na resposta. Cite os ids dos trechos:\n\n"
                + formatar_para_llm(resultados, diag))])
            chamadas += 1
            resposta = _texto(ai)

        resposta = sem_emojis(resposta)
        rastro.append(Passo("resposta gerada", f"{len(resposta.split())} palavras"))

        # 5) Verificação: regex (determinística) + Fiscal da Roça (LLM)
        problemas = guardrails.verificar_saida(resposta)
        avaliacao = None
        if problemas:
            rastro.append(Passo("guardrail de saída", "; ".join(problemas) + " → resposta substituída"))
            resposta = guardrails.RESPOSTA_BLOQUEADA
        else:
            avaliacao = self._fiscalizar(pergunta + (f"\n(foto: {descricao})" if descricao else ""), coleta, resposta)
            chamadas += 1
            if avaliacao:
                rastro.append(Passo("Fiscal da Roça", f"risco {avaliacao.risco} · precisa técnico: "
                                    f"{'sim' if avaliacao.precisa_tecnico else 'não'} · {avaliacao.motivo}"))

        semaforo, motivo = self._semaforo(avaliacao, problemas, flags, coleta["forca"], bool(descricao))
        rastro.append(Passo("semáforo", f"{semaforo}: {motivo}"))

        ficha = None
        precisa = semaforo == "vermelho" or (avaliacao and avaliacao.precisa_tecnico) or "pedido_de_dose" in flags
        base_nao_cobre = bool(coleta["forca"]) and all(f == "fraca" for f in coleta["forca"])
        if precisa or base_nao_cobre:  # "não sei" da IA vira pergunta para o humano
            ficha = fila.registrar(pergunta, perfil.como_dict(), semaforo, motivo, resposta,
                                   list(coleta["trechos"]), descricao)
            rastro.append(Passo("fila do técnico", f"ficha #{ficha['id']} criada (prioridade {ficha['prioridade']})"))

        return RespostaFala(
            texto=resposta, semaforo=semaforo, motivo=motivo, rastro=rastro, fontes=list(coleta["trechos"]),
            ficha=ficha, transcricao=transcricao, descricao_imagem=descricao, chamadas_llm=chamadas,
            segundos=round(time.time() - inicio, 1), flags=flags,
            avaliacao_fiscal=avaliacao.model_dump() if avaliacao else None)

    # ===== verificação =====
    def _fiscalizar(self, pergunta: str, coleta: dict, resposta: str) -> AvaliacaoFiscal | None:
        evid = [f"[{i}] {t}" for i, t in coleta["trechos"].items()]
        for nome, dados in coleta["ferramentas"].items():
            if nome == "previsao_do_tempo":
                evid.append(f"[{nome}] {clima.resumo_para_llm(dados)}")
            else:
                enxuto = {k: v for k, v in dados.items() if k != "dias"} if isinstance(dados, dict) else dados
                evid.append(f"[{nome}] {json.dumps(enxuto, ensure_ascii=False)}")
        texto_evid = "\n\n".join(evid)[:12000] or "(nenhuma evidência)"
        entrada = prompts.FISCAL.format(pergunta=pergunta, evidencias=texto_evid, resposta=resposta)
        for llm in (self.llm_fiscal, self.llm_reserva):  # se o fiscal estiver fora do ar, tenta o reserva
            try:
                return llm.with_structured_output(AvaliacaoFiscal).invoke(entrada)
            except Exception:
                continue
        return None

    @staticmethod
    def _semaforo(av: AvaliacaoFiscal | None, problemas: list[str], flags: set, forca: list[str],
                  tem_foto: bool) -> tuple[str, str]:
        if problemas:
            return "vermelho", "a resposta tentou citar produto/dose e foi bloqueada"
        if av is None:
            return "amarelo", "não consegui verificar a resposta automaticamente"
        if av.cita_produto_ou_dose or av.risco == "alto":
            return "vermelho", f"risco alto: {av.motivo}"
        motivos = []
        if av.afirmacoes_sem_apoio:
            motivos.append(f"{len(av.afirmacoes_sem_apoio)} afirmação(ões) sem fonte na base")
        if av.numeros_divergentes:
            motivos.append("números divergentes das ferramentas")
        if forca and all(f == "fraca" for f in forca):
            motivos.append("a base não cobre bem esse assunto")
        if tem_foto:
            motivos.append("diagnóstico por foto é só suspeita")
        if av.risco == "medio":
            motivos.append("risco médio se seguir sem técnico")
        if av.precisa_tecnico or "pedido_de_dose" in flags:
            motivos.append("caso pede avaliação de um técnico")
        if motivos:
            return "amarelo", "; ".join(motivos)
        return "verde", "resposta apoiada nas fichas e nos dados das ferramentas"

    # ===== modo sem chave (demonstra o que é IA generativa e o que não é) =====
    def _sem_ia(self, pergunta: str, perfil: Perfil, rastro: list[Passo], flags: set, inicio: float,
                motivo: str | None = None) -> RespostaFala:
        resultados, diag = self.buscador.buscar(pergunta, perfil.cultura_chave, k=2)
        rastro.append(Passo("busca BM25", f"{', '.join(r.trecho.id for r in resultados)} (evidência {diag['forca_evidencia']})"))
        partes = [f"**Modo sem IA generativa:** {motivo or config.motivo_sem_ia()}",
                  "Isto é só o que a busca encontrou nas fichas, sem interpretação:\n"]
        if "pedido_de_dose" in flags:
            partes = [guardrails.RESPOSTA_BLOQUEADA]
        elif diag["forca_evidencia"] == "fraca":
            partes.append("Não encontrei nada confiável sobre isso nas fichas. Procure a Emater ou o técnico da sua região.")
        else:
            for r in resultados:
                partes.append(f"**{r.trecho.titulo_doc} > {r.trecho.secao}** [{r.trecho.id}]\n\n{r.trecho.texto}\n")
        return RespostaFala("\n".join(partes), "cinza", "IA generativa desligada", rastro,
                            [r.trecho.id for r in resultados], segundos=round(time.time() - inicio, 1), flags=flags)

    # ===== Carta da Semana =====
    def painel_da_semana(self, perfil: Perfil) -> dict:
        dap = perfil.dias_apos_plantio
        if dap is None:
            raise ValueError("Preencha a data do plantio para eu saber em que fase a lavoura está.")
        prev = clima.previsao(perfil.cidade)
        fase = agronomia.fase_da_cultura(perfil.cultura_chave, dap)
        dias = [{"data": d["data"], "et0_mm": d["et0_mm"], "chuva_mm": d["chuva_mm"]} for d in prev["dias"]]
        agua = agronomia.balanco_hidrico(perfil.cultura_chave, dap, dias, perfil.area_m2, perfil.sistema)
        return {"previsao": prev, "fase": fase, "agua": agua}

    def carta_da_semana(self, perfil: Perfil) -> tuple[str, dict]:
        painel = self.painel_da_semana(perfil)
        fase, agua, prev = painel["fase"], painel["agua"], painel["previsao"]
        linhas = [
            f"Cultura: {perfil.cultura}, {fase['dias_apos_plantio']} dias, fase: {fase['descricao_fase']}"
            + (" (FASE CRÍTICA para água)" if fase.get("fase_critica_para_agua") else ""),
            f"Estado da água: {agua['estado_da_lavoura']}; chuva prevista {agua['chuva_prevista_total_mm']} mm; "
            f"irrigação necessária {agua['irrigacao_necessaria_mm']} mm"
            + (f" = {agua['litros_total_no_periodo']} litros na área de {perfil.area_m2:g} m²" if agua.get("litros_total_no_periodo") else ""),
            f"Temperaturas: mínima {min(d['tmin'] for d in prev['dias'])} °C, máxima {max(d['tmax'] for d in prev['dias'])} °C",
            "Alertas: " + (", ".join(f"{a['tipo']} ({a['data']})" for a in prev["alertas"]) or "nenhum"),
        ]
        if prev.get("dados_de_exemplo"):
            linhas.append(prev["aviso"])
        texto_painel = "\n".join(linhas)

        if not self.tem_ia:
            return self._carta_modelo(perfil, fase, agua, prev), painel

        consultas = [f"{a['tipo']} {perfil.cultura}" for a in prev["alertas"][:3]] or [f"{perfil.cultura} {fase['descricao_fase']}"]
        contexto = []
        for c in consultas:
            res, _ = self.buscador.buscar(c, perfil.cultura_chave, k=1)
            contexto += [f"[{r.trecho.id}] {r.trecho.texto}" for r in res]
        ai = self._invocar({"llm": self.llm}, prompts.CARTA.format(
            cultura=perfil.cultura, painel=texto_painel, contexto="\n".join(contexto), tratamento=perfil.tratamento))
        carta = sem_emojis(_texto(ai))
        if guardrails.verificar_saida(carta):
            carta = self._carta_modelo(perfil, fase, agua, prev)
        return carta, painel

    @staticmethod
    def _carta_modelo(perfil: Perfil, fase: dict, agua: dict, prev: dict) -> str:
        """Carta por template, usada sem IA ou quando o guardrail barra a carta gerada."""
        alertas = ", ".join(a["tipo"] for a in prev["alertas"]) or "nenhum alerta"
        litros = f" Vou precisar de uns {agua['litros_total_no_periodo']} litros na semana." if agua.get("litros_total_no_periodo") else ""
        return (f"Oi, {perfil.tratamento}! Aqui é seu {perfil.cultura}, com {fase['dias_apos_plantio']} dias. "
                f"Estou na fase de {fase['descricao_fase']} e me sinto {agua['estado_da_lavoura']}. "
                f"A previsão é de {agua['chuva_prevista_total_mm']} mm de chuva.{litros} Alertas: {alertas}. "
                f"Seu {perfil.cultura}, que te espera na roça")
