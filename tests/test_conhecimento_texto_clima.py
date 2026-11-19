import pytest

from falalavoura.clima import gerar_alertas
from falalavoura.conhecimento import Buscador, expandir_consulta
from falalavoura.texto import flesch_pt, normalizar, radical, tokens


@pytest.fixture(scope="module")
def buscador():
    return Buscador(usar_embeddings=False)


def test_base_carregada_com_ids_unicos(buscador):
    ids = [t.id for t in buscador.trechos]
    assert len(ids) >= 60
    assert len(ids) == len(set(ids))


def test_dicionario_da_roca_traduz_expressoes(buscador):
    expandida, achados = expandir_consulta("meu tomate ta com fundo preto", buscador.dicionario)
    assert "fundo preto" in achados
    assert "podridao apical" in expandida


@pytest.mark.parametrize("pergunta,cultura,esperado", [
    ("tem bicho comendo a folha do milho e uma serragem no cartucho", "milho", "milho#lagarta-do-cartucho"),
    ("meu tomate ta com o fundo preto", "tomate", "tomate#podridao-apical-fundo-preto"),
    ("como pego dinheiro do banco pra roça", "milho", "politicas_publicas#pronaf-credito-rural"),
    ("posso comer mandioca brava cozida?", "mandioca", "mandioca#mandioca-brava-e-seguranca-dos-alimentos"),
])
def test_busca_acha_o_trecho_certo(buscador, pergunta, cultura, esperado):
    resultados, diag = buscador.buscar(pergunta, cultura)
    assert resultados[0].trecho.id == esperado
    assert diag["forca_evidencia"] in ("forte", "media")


def test_busca_reconhece_quando_nao_sabe(buscador):
    _, diag = buscador.buscar("como plantar quinoa no cerrado?", "milho")
    assert diag["forca_evidencia"] == "fraca"


def test_texto_normaliza_e_reduz():
    assert normalizar("Feijão Ação") == "feijao acao"
    assert radical("lagartinhas") == radical("lagarta")
    assert "lagart" in tokens("lagarta-do-cartucho")


def test_flesch_texto_simples_e_mais_facil():
    simples = "Tô com sede. Me rega cedo. A chuva vem sábado."
    dificil = ("A evapotranspiração potencial da cultura, determinada pelo coeficiente de cultivo "
               "multiplicado pela evapotranspiração de referência, condiciona a necessidade hídrica.")
    assert flesch_pt(simples) > 75
    assert flesch_pt(dificil) < 25


def test_alertas_de_clima():
    dias = [
        {"data": "d1", "tmin": 2.0, "tmax": 18, "chuva_mm": 0, "rajada_kmh": 20, "umidade_pct": 60},
        {"data": "d2", "tmin": 20, "tmax": 37, "chuva_mm": 0, "rajada_kmh": 70, "umidade_pct": 40},
        {"data": "d3", "tmin": 20, "tmax": 30, "chuva_mm": 80, "rajada_kmh": 30, "umidade_pct": 90},
    ]
    tipos = {a["tipo"] for a in gerar_alertas(dias)}
    assert {"geada", "calor intenso", "vento forte", "chuva forte"} <= tipos


def test_sem_emojis():
    from falalavoura.texto import sem_emojis
    assert sem_emojis("\U0001F331 A lavoura diz: oi \u2705") == "A lavoura diz: oi "
