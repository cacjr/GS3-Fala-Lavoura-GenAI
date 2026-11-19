from datetime import date

import pytest

from falalavoura import agronomia as ag


def test_curva_kc_milho_segue_fao56():
    milho = ag.obter_cultura("Milho")
    assert ag.kc_no_dia(milho, 0) == pytest.approx(0.30)
    assert ag.kc_no_dia(milho, 20) == pytest.approx(0.30)            # fim da fase inicial
    assert ag.kc_no_dia(milho, 37.5) == pytest.approx(0.75)          # meio da rampa 0,30 -> 1,20
    assert ag.kc_no_dia(milho, 60) == pytest.approx(1.20)            # fase intermediária
    assert ag.kc_no_dia(milho, 125) == pytest.approx(0.60)           # fim do ciclo
    assert ag.kc_no_dia(milho, 300) == pytest.approx(0.60)           # depois do ciclo


def test_fase_critica_do_milho_no_florescimento():
    fase = ag.fase_da_cultura("milho", 62)
    assert fase["fase"] == "intermediaria"
    assert fase["fase_critica_para_agua"] is True


def test_aceita_acento_e_maiuscula():
    assert ag.obter_cultura("Feijão").nome == "feijão"
    with pytest.raises(ValueError):
        ag.obter_cultura("quinoa")


def test_chuva_efetiva():
    assert ag.chuva_efetiva(1.5) == 0
    assert ag.chuva_efetiva(10) == pytest.approx(8)


def test_balanco_hidrico_conferido_a_mao():
    # Alface com 40 dias (Kc = 1,0), 2 dias secos com ET0 = 10 mm, solo começa com 7,5 mm (metade de 15).
    # Dia 1: 7,5 - 10 = -2,5 -> irrigar 2,5 mm. Dia 2: 0 - 10 -> irrigar 10 mm. Total 12,5 mm.
    prev = [{"data": "d1", "et0_mm": 10, "chuva_mm": 0}, {"data": "d2", "et0_mm": 10, "chuva_mm": 0}]
    r = ag.balanco_hidrico("alface", 40, prev, area_m2=10, sistema="Gotejamento")
    assert r["irrigacao_necessaria_mm"] == pytest.approx(12.5)
    # Gotejamento 90%: 12,5 / 0,9 = 13,9 L/m², x 10 m² = 139 L
    assert r["litros_por_m2_no_periodo"] == pytest.approx(13.9, abs=0.05)
    assert r["litros_total_no_periodo"] == 139
    assert r["estado_da_lavoura"] == "com muita sede"


def test_chuva_forte_nao_pede_irrigacao():
    prev = [{"data": f"d{i}", "et0_mm": 4, "chuva_mm": 30} for i in range(5)]
    r = ag.balanco_hidrico("milho", 60, prev, area_m2=100)
    assert r["irrigacao_necessaria_mm"] == 0
    assert r["estado_da_lavoura"] == "com água demais"


def test_dias_desde_plantio():
    assert ag.dias_desde("01/11/2026", hoje=date(2026, 11, 12)) == 11
    assert ag.dias_desde("2026-11-01", hoje=date(2026, 11, 12)) == 11
    with pytest.raises(ValueError):
        ag.dias_desde("ontem")
