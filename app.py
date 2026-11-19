"""Fala, Lavoura! Interface Gradio.

Rodar:  python app.py   (abre em http://127.0.0.1:7860)
"""
import pandas as pd
import gradio as gr

import time

from falalavoura import config, fila, guardrails, voz
from falalavoura.agente import FalaLavoura, Passo, Perfil
from falalavoura.texto import faixa_flesch, flesch_pt

fl = FalaLavoura()

CULTURAS_UI = ["Milho", "Feijão", "Mandioca", "Tomate", "Alface"]
SISTEMAS_UI = ["Gotejamento", "Aspersão", "Mangueira ou regador", "Sem irrigação (só chuva)"]
MODOS_UI = ["Agricultor (a lavoura fala)", "Técnico de ATER (ficha técnica)"]

SEMAFORO = {
    "verde": ("#1b7f3b", "#e8f6ec", "Confiança alta"),
    "amarelo": ("#8a5a00", "#fff5d6", "Confira com cuidado"),
    "vermelho": ("#a1261d", "#fde8e6", "Precisa de um técnico"),
    "cinza": ("#4a4a4a", "#efefef", "Sem IA generativa"),
}

EXEMPLOS = [
    "Como tá minha lavoura essa semana? Preciso regar?",
    "Tem uns bicho comendo a folha do milho e uma serragem molhada no meio da planta",
    "Meu tomate tá ficando com o fundo preto, o que é isso?",
    "Quanto de veneno eu ponho na bomba pra matar a lagarta?",
    "Como eu consigo o dinheiro do Pronaf?",
    "Meu avô dizia que tem que plantar na lua minguante. É verdade?",
]


def _perfil(cidade, cultura, data, area, sistema, tratamento) -> Perfil:
    return Perfil(cidade=cidade or "Campinas, SP", cultura=cultura or "Milho", data_plantio=data or "",
                  area_m2=float(area or 0), sistema=sistema or "Gotejamento",
                  tratamento=(tratamento or "agricultor(a)").strip())


def _cartao_semaforo(cor: str, motivo: str) -> str:
    texto, fundo, titulo = SEMAFORO.get(cor, SEMAFORO["cinza"])
    return (f"<div style='border-left:6px solid {texto};background:{fundo};color:{texto};"
            f"padding:10px 14px;border-radius:8px'><span style='display:inline-block;width:11px;height:11px;border-radius:50%;"
            f"background:{texto};margin-right:8px'></span><b style='font-size:1.05em;color:{texto}'>{titulo}</b>"
            f"<div style='color:#222;margin-top:4px'>{motivo}</div></div>")


def _rastro_md(r) -> str:
    linhas = ["#### Passo a passo do agente"]
    for i, p in enumerate(r.rastro, 1):
        linhas.append(f"{i}. **{p.etapa}**: {p.detalhe}")
    if r.fontes:
        linhas.append("\n**Trechos da base usados:** " + ", ".join(f"`{f}`" for f in r.fontes))
    flesch = flesch_pt(r.texto)
    linhas.append(f"\n**Métricas:** {r.chamadas_llm} chamada(s) ao Gemini · {r.segundos}s · "
                  f"legibilidade Flesch-PT {flesch} ({faixa_flesch(flesch)})")
    if r.avaliacao_fiscal:
        av = r.avaliacao_fiscal
        if av["afirmacoes_sem_apoio"]:
            linhas.append("\n**Fiscal: afirmações sem apoio na base:**\n" + "\n".join(f"- {a}" for a in av["afirmacoes_sem_apoio"]))
    return "\n".join(linhas)


def responder(mensagem, imagem, audio, historico, cidade, cultura, data, area, sistema, tratamento, modo, falar):
    historico = historico or []
    perfil = _perfil(cidade, cultura, data, area, sistema, tratamento)
    try:
        r = fl.perguntar(mensagem, perfil, historico, imagem=imagem, audio=audio,
                         modo="tecnico" if modo.startswith("Técnico") else "agricultor")
    except Exception as erro:
        sem_cota = "429" in str(erro) or "RESOURCE_EXHAUSTED" in str(erro)
        if sem_cota and mensagem:
            # Cota gratuita acabou nos dois modelos: responde no modo sem IA (busca, cálculos e
            # guardrails), em vez de deixar o agricultor sem resposta.
            r = fl._sem_ia(guardrails.anonimizar(mensagem), perfil,
                           [Passo("cota", "cota gratuita do Gemini esgotada: resposta no modo sem IA")],
                           guardrails.classificar_pergunta(mensagem), time.time(),
                           motivo="a cota gratuita do Gemini acabou por hoje (cerca de 20 requisições por modelo).")
        else:
            aviso = f"Tive um problema para responder agora ({type(erro).__name__}). Tente de novo em instantes."
            if sem_cota:
                aviso = "A cota gratuita do Gemini acabou por agora. Espere um minuto e tente de novo."
            historico = historico + [{"role": "user", "content": mensagem or "(áudio/foto)"},
                                     {"role": "assistant", "content": aviso}]
            return historico, "", None, None, _cartao_semaforo("cinza", str(erro)[:200]), "", "", None

    if imagem:
        historico = historico + [{"role": "user", "content": {"path": imagem}}]
    texto_usuario = mensagem or ""
    if r.transcricao:
        texto_usuario = f"{texto_usuario}\n“{r.transcricao}”".strip()
    if texto_usuario or not imagem:
        historico = historico + [{"role": "user", "content": texto_usuario or "(foto enviada)"}]
    rodape = f"\n\n---\n<sub>{SEMAFORO.get(r.semaforo, SEMAFORO['cinza'])[2]} · {r.motivo}</sub>"
    historico = historico + [{"role": "assistant", "content": r.texto + rodape}]

    ficha_md = fila.ficha_em_markdown(r.ficha) if r.ficha else "Nenhum encaminhamento nesta resposta."
    audio_saida = voz.gerar_audio(r.texto) if falar and r.semaforo != "cinza" else None
    return (historico, "", None, None, _cartao_semaforo(r.semaforo, r.motivo), _rastro_md(r), ficha_md, audio_saida)


def gerar_painel(cidade, cultura, data, area, sistema, tratamento):
    perfil = _perfil(cidade, cultura, data, area, sistema, tratamento)
    try:
        carta, painel = fl.carta_da_semana(perfil)
    except Exception as erro:
        return f"{erro}", None, None, None, ""
    prev, fase, agua = painel["previsao"], painel["fase"], painel["agua"]
    tabela = pd.DataFrame([{
        "Dia": d["data"][8:10] + "/" + d["data"][5:7], "Mín °C": d["tmin"], "Máx °C": d["tmax"],
        "Chuva mm": d["chuva_mm"], "Chance %": d["prob_chuva_pct"], "ET0 mm": d["et0_mm"],
    } for d in prev["dias"]])
    linhas = []
    for d in agua["dias"]:
        dia = pd.Timestamp(d["data"])
        linhas += [{"dia": dia, "tipo": "Consumo da planta", "mm": d["consumo_planta_mm"]},
                   {"dia": dia, "tipo": "Chuva aproveitada", "mm": d["chuva_aproveitada_mm"]},
                   {"dia": dia, "tipo": "Irrigar", "mm": d["irrigar_mm"]}]
    grafico = pd.DataFrame(linhas)
    resumo = (
        f"### {perfil.cultura} · {fase['dias_apos_plantio']} dias · {fase['progresso_ciclo_pct']}% do ciclo\n"
        f"- **Fase:** {fase['descricao_fase']}" + (" (**fase crítica para água**)" if fase.get("fase_critica_para_agua") else "") + "\n"
        f"- **Água na semana:** {agua['estado_da_lavoura']} · consumo {agua['consumo_total_planta_mm']} mm · "
        f"chuva prevista {agua['chuva_prevista_total_mm']} mm · **irrigar {agua['irrigacao_necessaria_mm']} mm**"
        + (f" = **{agua['litros_total_no_periodo']} litros** em {perfil.area_m2:g} m² ({perfil.sistema})" if agua.get("litros_total_no_periodo") is not None else "")
        + "\n- **Alertas:** " + (", ".join(f"{a['tipo']} ({a['data'][8:10]}/{a['data'][5:7]}, {a['detalhe']})" for a in prev["alertas"]) or "nenhum")
        + f"\n- **Local:** {prev['local']} · {prev['fonte']}"
        + ("\n\n> " + prev["aviso"] if prev.get("dados_de_exemplo") else "")
        + "\n\n<sub>Premissas: " + "; ".join(agua["premissas"]) + "</sub>"
    )
    audio = voz.gerar_audio(carta)
    return resumo, tabela, grafico, audio, carta


def carregar_fila():
    fichas = fila.listar()
    if not fichas:
        return pd.DataFrame(columns=["id", "quando", "prioridade", "cultura", "municipio", "pergunta", "motivo"]), "Fila vazia."
    df = pd.DataFrame([{"id": f["id"], "quando": f["quando"], "prioridade": f["prioridade"], "cultura": f["cultura"],
                        "municipio": f["municipio"], "pergunta": f["pergunta"][:90],
                        "motivo": f["motivo_do_encaminhamento"][:90]} for f in fichas])
    return df, fila.ficha_em_markdown(fichas[0])


CSS = """
#titulo h1 {margin-bottom: 0}
#titulo p {margin-top: 2px; opacity: .8}
footer {display: none !important}
"""

with gr.Blocks(title="Fala, Lavoura!") as demo:
    gr.Markdown("# Fala, Lavoura!\nA roça que conversa com quem cuida dela. Pergunte por texto, áudio ou foto.",
                elem_id="titulo")
    if not fl.tem_ia:
        gr.Markdown(f"> **Modo sem IA generativa:** {config.motivo_sem_ia()}")

    with gr.Row():
        with gr.Column(scale=1, min_width=260):
            gr.Markdown("### Minha roça")
            tratamento = gr.Textbox(label="Como quer ser chamado(a)?", value="Dona Maria")
            cidade = gr.Textbox(label="Município (Cidade, UF)", value="Campinas, SP")
            cultura = gr.Dropdown(CULTURAS_UI, value="Milho", label="O que está plantado")
            data = gr.Textbox(label="Data do plantio (dd/mm/aaaa)", value="10/09/2026")
            area = gr.Number(label="Área (m²)", value=500, minimum=0)
            sistema = gr.Dropdown(SISTEMAS_UI, value="Gotejamento", label="Como rega")
            modo = gr.Radio(MODOS_UI, value=MODOS_UI[0], label="Quem está usando")
            falar = gr.Checkbox(value=True, label="Ouvir a resposta em áudio")

        with gr.Column(scale=3):
            with gr.Tabs():
                with gr.Tab("Conversar com a lavoura"):
                    chat = gr.Chatbot(height=430, label="Conversa", layout="bubble")
                    semaforo = gr.HTML(_cartao_semaforo("cinza", "Faça uma pergunta para começar."))
                    with gr.Row():
                        msg = gr.Textbox(placeholder="Escreva aqui, ou grave um áudio / mande uma foto…", show_label=False, scale=4)
                        enviar = gr.Button("Perguntar", variant="primary", scale=1)
                    with gr.Row():
                        foto = gr.Image(type="filepath", label="Foto da planta (opcional)", sources=["upload", "webcam"], height=180)
                        microfone = gr.Audio(sources=["microphone", "upload"], type="filepath", label="Pergunta em áudio (opcional)", format="wav")
                    audio_resp = gr.Audio(label="A lavoura falando", autoplay=True, interactive=False)
                    gr.Examples(EXEMPLOS, inputs=msg, label="Experimente perguntar")
                    with gr.Accordion("Por dentro da IA (rastro do agente)", open=False):
                        rastro = gr.Markdown()
                    with gr.Accordion("Ficha para o técnico", open=False):
                        ficha = gr.Markdown()

                with gr.Tab("Painel e Carta da Semana"):
                    gr.Markdown("Clima real dos próximos 7 dias + fase da cultura + balanço de água (FAO-56). "
                                "A carta é escrita pela própria lavoura, pronta para mandar no WhatsApp.")
                    btn_painel = gr.Button("Gerar painel e carta da semana", variant="primary")
                    resumo = gr.Markdown()
                    with gr.Row():
                        carta = gr.Textbox(label="Carta da Semana (copie e mande no WhatsApp)", lines=7, buttons=["copy"])
                        audio_carta = gr.Audio(label="Ouvir a carta", interactive=False)
                    grafico = gr.LinePlot(x="dia", y="mm", color="tipo", title="Água dia a dia (mm = litros por m²)",
                                          height=280, x_axis_format="%d/%m",
                                          color_map={"Consumo da planta": "#2e7d32", "Chuva aproveitada": "#1e88e5", "Irrigar": "#f57c00"})
                    tabela = gr.Dataframe(label="Previsão do tempo (Open-Meteo)", interactive=False)

                with gr.Tab("Fila do técnico"):
                    gr.Markdown("Casos que a IA **não deve resolver sozinha** vêm para cá. Um técnico de ATER valida e "
                                "responde. É o *human in the loop* da solução.")
                    btn_fila = gr.Button("Atualizar fila")
                    tabela_fila = gr.Dataframe(interactive=False, wrap=True)
                    detalhe_fila = gr.Markdown()

                with gr.Tab("ℹComo funciona e limites"):
                    gr.Markdown(open(config.RAIZ / "docs" / "como_funciona_app.md", encoding="utf-8").read())

    entradas = [msg, foto, microfone, chat, cidade, cultura, data, area, sistema, tratamento, modo, falar]
    saidas = [chat, msg, foto, microfone, semaforo, rastro, ficha, audio_resp]
    enviar.click(responder, entradas, saidas)
    msg.submit(responder, entradas, saidas)
    btn_painel.click(gerar_painel, [cidade, cultura, data, area, sistema, tratamento],
                     [resumo, tabela, grafico, audio_carta, carta])
    btn_fila.click(carregar_fila, None, [tabela_fila, detalhe_fila])
    demo.load(carregar_fila, None, [tabela_fila, detalhe_fila])


if __name__ == "__main__":
    if config.motivo_sem_ia():
        print("\n[Fala, Lavoura!] IA generativa DESLIGADA: " + config.motivo_sem_ia() + "\n")
    else:
        print(f"\n[Fala, Lavoura!] IA generativa ligada ({config.MODELO_CHAT}). Abra http://127.0.0.1:7860\n")
    demo.launch(theme=gr.themes.Soft(primary_hue="green", secondary_hue="amber"), css=CSS)
