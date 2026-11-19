"""Quando a cota gratuita acaba nos dois modelos, o app responde no modo sem IA."""


def test_cota_esgotada_cai_no_modo_sem_ia():
    import app

    def sem_cota(*_a, **_k):
        raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")

    original = app.fl.perguntar
    app.fl.perguntar = sem_cota
    try:
        saida = app.responder("quando eu planto feijão?", None, None, [], "Campinas, SP", "feijao", "",
                              100, "gotejamento", "Dona", "Agricultor", False)
    finally:
        app.fl.perguntar = original
    resposta = saida[0][-1]["content"]
    assert "Modo sem IA generativa" in resposta and "cota gratuita" in resposta
