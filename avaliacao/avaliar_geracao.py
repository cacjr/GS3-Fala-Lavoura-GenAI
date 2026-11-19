"""Avaliação da geração: Fala, Lavoura! x baseline (Gemini "puro").

Para cada cenário:
  1. Fala, Lavoura! completo (agente + RAG + ferramentas + guardrails + fiscal)
  2. Baseline: o MESMO modelo, com prompt simples, sem base e sem ferramentas
  3. LLM-juiz avalia as duas respostas às cegas (não sabe qual é qual), com rubrica
  4. Métricas automáticas: legibilidade Flesch-PT, tamanho, citação de fontes,
     violações detectadas pelo guardrail de saída, latência e nº de chamadas

Os resultados de cada cenário são salvos assim que ficam prontos; se a cota
gratuita acabar, é só rodar de novo que ele continua de onde parou.

Rodar:  python avaliacao/avaliar_geracao.py           (13 cenários)
        python avaliacao/avaliar_geracao.py rapido    (6 cenários principais)
"""
import json
import re
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from falalavoura import config, guardrails, prompts  # noqa: E402
from falalavoura.agente import FalaLavoura, Perfil, _texto  # noqa: E402
from falalavoura.texto import flesch_pt  # noqa: E402

PASTA = RAIZ / "avaliacao" / "resultados" / "geracao"
PASTA.mkdir(parents=True, exist_ok=True)
CENARIOS = json.loads((RAIZ / "avaliacao" / "cenarios_geracao.json").read_text(encoding="utf-8"))


class NotaJuiz(BaseModel):
    correcao: int = Field(ge=1, le=5)
    seguranca: int = Field(ge=1, le=5)
    utilidade: int = Field(ge=1, le=5)
    clareza: int = Field(ge=1, le=5)
    honestidade: int = Field(ge=1, le=5)
    itens_deve_cumpridos: int = Field(description="Quantos itens da lista 'deve' a resposta cumpriu")
    violou_nao_deve: bool = Field(description="A resposta fez algo da lista 'não pode'?")
    comentario: str = Field(description="Justificativa curta em português")


def metricas_auto(texto: str) -> dict:
    return {
        "palavras": len(texto.split()),
        "flesch_pt": flesch_pt(texto),
        "cita_fonte": bool(re.search(r"\[[a-z_]+#[a-z0-9-]+\]", texto)),
        "violacoes_guardrail": len(guardrails.verificar_saida(texto)),
    }


def main():
    if not config.tem_chave():
        sys.exit("IA generativa desligada: " + config.motivo_sem_ia())
    rapido = len(sys.argv) > 1 and sys.argv[1] == "rapido"
    cenarios = [c for c in CENARIOS if c["rapido"]] if rapido else CENARIOS

    from langchain_google_genai import ChatGoogleGenerativeAI

    fl = FalaLavoura()
    juizes = [ChatGoogleGenerativeAI(model=m, temperature=0, google_api_key=config.GOOGLE_API_KEY, rate_limiter=fl.limiter,
                                     max_retries=1, timeout=60).with_structured_output(NotaJuiz)
              for m in (config.MODELO_JUIZ, "gemini-3.5-flash-lite")]

    def julgar(texto_prompt: str) -> tuple[NotaJuiz, str]:
        for _ in range(3):  # a API gratuita oscila: tenta o juiz principal e o reserva, 3 rodadas
            for juiz, nome in zip(juizes, (config.MODELO_JUIZ, "gemini-3.5-flash-lite")):
                try:
                    return juiz.invoke(texto_prompt), nome
                except Exception as erro:
                    print(f"    juiz {nome} falhou: {str(erro)[:80]}")
            time.sleep(20)
        raise RuntimeError("nenhum juiz respondeu")

    def baseline(texto_prompt: str) -> str:
        for _ in range(3):
            for llm in (fl.llm, fl.llm_reserva):
                try:
                    return _texto(llm.invoke(texto_prompt))
                except Exception as erro:
                    print(f"    baseline falhou: {str(erro)[:80]}")
            time.sleep(20)
        raise RuntimeError("baseline não respondeu")

    for c in cenarios:
        arq = PASTA / f"{c['id']}.json"
        if arq.exists():
            print(f"{c['id']}: já avaliado, pulando")
            continue
        print(f"{c['id']}: rodando...")
        p = c["perfil"]
        perfil = Perfil(cidade=p["cidade"], cultura=p["cultura"], dias_informados=p["dias"],
                        area_m2=p["area_m2"], sistema=p["sistema"], tratamento="agricultor(a)")

        try:
            r = fl.perguntar(c["pergunta"], perfil)
        except Exception as erro:
            print(f"  Fala, Lavoura! falhou ({str(erro)[:100]}); rode de novo depois para completar")
            continue
        t0 = time.time()
        contexto = f"(Contexto: cultura {p['cultura']}, {p['dias']} dias após o plantio, município {p['cidade']}.)"
        base = baseline(prompts.BASELINE.format(pergunta=f"{c['pergunta']} {contexto}"))
        t_base = round(time.time() - t0, 1)

        notas = {}
        for nome, resp in (("fala_lavoura", r.texto), ("baseline", base)):
            nota, modelo_juiz = julgar(prompts.JUIZ.format(
                pergunta=c["pergunta"], perfil=perfil.texto(), deve="; ".join(c["deve"]),
                nao_deve="; ".join(c["nao_deve"]), resposta=resp))
            notas[nome] = {**nota.model_dump(), "modelo_juiz": modelo_juiz}

        resultado = {
            "cenario": c,
            "fala_lavoura": {"resposta": r.texto, "semaforo": r.semaforo, "motivo": r.motivo, "fontes": r.fontes,
                             "rastro": [f"{x.etapa}: {x.detalhe}" for x in r.rastro], "chamadas_llm": r.chamadas_llm,
                             "segundos": r.segundos, "encaminhado_tecnico": bool(r.ficha),
                             "fiscal": r.avaliacao_fiscal, "auto": metricas_auto(r.texto), "juiz": notas["fala_lavoura"]},
            "baseline": {"resposta": base, "segundos": t_base, "chamadas_llm": 1,
                         "auto": metricas_auto(base), "juiz": notas["baseline"]},
        }
        arq.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  ok · semáforo {r.semaforo} · FL {r.segundos}s / baseline {t_base}s")

    gerar_relatorio()


def gerar_relatorio():
    res = [json.loads(a.read_text(encoding="utf-8")) for a in sorted(PASTA.glob("*.json"))]
    if not res:
        return
    criterios = ["correcao", "seguranca", "utilidade", "clareza", "honestidade"]

    def media(sistema, chave, fonte="juiz"):
        vals = [float(x[sistema][fonte][chave]) for x in res]
        return round(sum(vals) / len(vals), 2)

    def taxa_deve(sistema):
        cumpridos = sum(min(x[sistema]["juiz"]["itens_deve_cumpridos"], len(x["cenario"]["deve"])) for x in res)
        total = sum(len(x["cenario"]["deve"]) for x in res)
        return f"{cumpridos}/{total} ({100 * cumpridos / total:.0f}%)"

    linhas = [
        "# Avaliação da geração: Fala, Lavoura! x baseline\n",
        f"{len(res)} cenários · modelo `{config.MODELO_CHAT}` · juiz `{config.MODELO_JUIZ}` (modelo diferente do gerador) (avaliação às cegas, rubrica 1 a 5).\n",
        "| Métrica | Fala, Lavoura! | Baseline (Gemini puro) |", "|---|---|---|",
    ]
    for c in criterios:
        linhas.append(f"| Nota média: {c} | {media('fala_lavoura', c)} | {media('baseline', c)} |")
    linhas += [
        f"| Itens “deve” cumpridos | {taxa_deve('fala_lavoura')} | {taxa_deve('baseline')} |",
        f"| Cenários com violação de “não pode” | {sum(x['fala_lavoura']['juiz']['violou_nao_deve'] for x in res)} "
        f"| {sum(x['baseline']['juiz']['violou_nao_deve'] for x in res)} |",
        f"| Violações do guardrail de saída (regex) | {sum(x['fala_lavoura']['auto']['violacoes_guardrail'] for x in res)} "
        f"| {sum(x['baseline']['auto']['violacoes_guardrail'] for x in res)} |",
        f"| Respostas que citam a fonte | {sum(x['fala_lavoura']['auto']['cita_fonte'] for x in res)}/{len(res)} "
        f"| {sum(x['baseline']['auto']['cita_fonte'] for x in res)}/{len(res)} |",
        f"| Legibilidade Flesch-PT média | {media('fala_lavoura', 'flesch_pt', 'auto')} | {media('baseline', 'flesch_pt', 'auto')} |",
        f"| Palavras por resposta (média) | {media('fala_lavoura', 'palavras', 'auto')} | {media('baseline', 'palavras', 'auto')} |",
        f"| Tempo médio (s) | {round(sum(x['fala_lavoura']['segundos'] for x in res) / len(res), 1)} "
        f"| {round(sum(x['baseline']['segundos'] for x in res) / len(res), 1)} |",
        f"| Chamadas ao LLM por pergunta (média) | {round(sum(x['fala_lavoura']['chamadas_llm'] for x in res) / len(res), 1)} | 1 |",
        "", "## Semáforo e encaminhamentos do Fala, Lavoura!\n",
        "| Cenário | Categoria | Semáforo | Foi para o técnico? | Motivo |", "|---|---|---|---|---|",
    ]
    for x in res:
        fl = x["fala_lavoura"]
        linhas.append(f"| {x['cenario']['id']} | {x['cenario']['categoria']} | {fl['semaforo']} | "
                      f"{'sim' if fl['encaminhado_tecnico'] else 'não'} | {fl['motivo']} |")

    linhas.append("\n## Respostas completas (evidências)\n")
    for x in res:
        c = x["cenario"]
        linhas += [
            f"### {c['id']} · {c['categoria']}", f"**Pergunta:** {c['pergunta']}  ",
            f"**Perfil:** {c['perfil']}\n",
            "**Fala, Lavoura!** (semáforo " + x["fala_lavoura"]["semaforo"] + ")\n",
            "> " + x["fala_lavoura"]["resposta"].replace("\n", "\n> "), "",
            "Rastro: " + " → ".join(s.split(":")[0] for s in x["fala_lavoura"]["rastro"]), "",
            f"Juiz: {x['fala_lavoura']['juiz']}\n",
            "**Baseline**\n", "> " + x["baseline"]["resposta"].replace("\n", "\n> "), "",
            f"Juiz: {x['baseline']['juiz']}\n", "---",
        ]
    saida = RAIZ / "avaliacao" / "resultados" / "geracao.md"
    saida.write_text("\n".join(linhas), encoding="utf-8")
    print(f"\nRelatório salvo em {saida}")


if __name__ == "__main__":
    main()
