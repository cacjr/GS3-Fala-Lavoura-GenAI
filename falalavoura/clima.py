"""Clima ao vivo pela API Open-Meteo (gratuita e sem chave) + alertas.

Se a internet falhar, usa um arquivo de previsão de exemplo e avisa
claramente que os dados não são reais (nunca finge que são).
"""
from __future__ import annotations

import json
import time

import requests

from . import config
from .texto import normalizar

URL_GEO = "https://geocoding-api.open-meteo.com/v1/search"
URL_PREVISAO = "https://api.open-meteo.com/v1/forecast"
VARIAVEIS = ("temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,"
             "et0_fao_evapotranspiration,wind_gusts_10m_max,relative_humidity_2m_mean")

UFS = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão",
    "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará",
    "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima",
    "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins",
}

_cache: dict[str, tuple[float, dict]] = {}
VALIDADE_CACHE_S = 3600


def geocodificar(cidade: str) -> dict:
    """'Petrolina, PE' -> {nome, uf, lat, lon}. A UF ajuda a desempatar cidades com mesmo nome."""
    nome, _, uf = cidade.partition(",")
    uf = uf.strip().upper()
    r = requests.get(URL_GEO, params={"name": nome.strip(), "count": 10, "language": "pt",
                                      "countryCode": "BR", "format": "json"}, timeout=10)
    r.raise_for_status()
    resultados = r.json().get("results") or []
    if not resultados:
        raise ValueError(f"Não encontrei a cidade '{cidade}'.")
    if uf in UFS:
        filtrados = [x for x in resultados if normalizar(x.get("admin1", "")) == normalizar(UFS[uf])]
        resultados = filtrados or resultados
    x = resultados[0]
    return {"nome": x["name"], "estado": x.get("admin1", ""), "lat": x["latitude"], "lon": x["longitude"]}


def _previsao_exemplo() -> dict:
    dados = json.loads(config.ARQ_CLIMA_EXEMPLO.read_text(encoding="utf-8"))
    dados["dados_de_exemplo"] = True
    dados["aviso"] = ("SEM INTERNET: usando previsão de EXEMPLO salva no projeto. "
                      "Não use esses números para decidir nada na roça.")
    return dados


def previsao(cidade: str, dias: int = 7) -> dict:
    chave = f"{normalizar(cidade)}|{dias}"
    if chave in _cache and time.time() - _cache[chave][0] < VALIDADE_CACHE_S:
        return _cache[chave][1]
    try:
        local = geocodificar(cidade)
        r = requests.get(URL_PREVISAO, params={
            "latitude": local["lat"], "longitude": local["lon"], "daily": VARIAVEIS,
            "timezone": "America/Sao_Paulo", "forecast_days": dias}, timeout=10)
        r.raise_for_status()
        d = r.json()["daily"]
        resultado = {
            "local": f"{local['nome']} ({local['estado']})",
            "fonte": "Open-Meteo (modelos meteorológicos globais), consultado agora",
            "dados_de_exemplo": False,
            "dias": [
                {"data": d["time"][i],
                 "tmax": d["temperature_2m_max"][i], "tmin": d["temperature_2m_min"][i],
                 "chuva_mm": d["precipitation_sum"][i] or 0.0,
                 "prob_chuva_pct": d["precipitation_probability_max"][i],
                 "et0_mm": d["et0_fao_evapotranspiration"][i] or 0.0,
                 "rajada_kmh": d["wind_gusts_10m_max"][i],
                 "umidade_pct": d["relative_humidity_2m_mean"][i]}
                for i in range(len(d["time"]))
            ],
        }
    except ValueError:
        raise
    except Exception:
        resultado = _previsao_exemplo()
    resultado["alertas"] = gerar_alertas(resultado["dias"])
    _cache[chave] = (time.time(), resultado)
    return resultado


def gerar_alertas(dias: list[dict]) -> list[dict]:
    """Regras simples e explicáveis (limiares das fichas de clima extremo)."""
    alertas = []
    for d in dias:
        if d["tmin"] is not None and d["tmin"] <= 3:
            alertas.append({"tipo": "geada", "data": d["data"], "severidade": "alta" if d["tmin"] <= 1 else "media",
                            "detalhe": f"mínima de {d['tmin']} °C"})
        if d["tmax"] is not None and d["tmax"] >= 35:
            alertas.append({"tipo": "calor intenso", "data": d["data"], "severidade": "alta" if d["tmax"] >= 38 else "media",
                            "detalhe": f"máxima de {d['tmax']} °C"})
        if d["chuva_mm"] >= 50:
            alertas.append({"tipo": "chuva forte", "data": d["data"], "severidade": "alta",
                            "detalhe": f"{d['chuva_mm']} mm no dia"})
        if d.get("rajada_kmh") and d["rajada_kmh"] >= 60:
            alertas.append({"tipo": "vento forte", "data": d["data"], "severidade": "media",
                            "detalhe": f"rajadas de {d['rajada_kmh']} km/h"})

    secos = 0
    for d in dias:
        secos = secos + 1 if d["chuva_mm"] < 1 else 0
        if secos == 5:
            alertas.append({"tipo": "sequência seca", "data": d["data"], "severidade": "media",
                            "detalhe": "5 dias seguidos sem chuva relevante"})

    umidos = [d for d in dias if d["chuva_mm"] >= 1 and (d.get("umidade_pct") or 0) >= 80
              and d["tmin"] is not None and d["tmin"] >= 12 and d["tmax"] <= 28]
    if len(umidos) >= 3:
        alertas.append({"tipo": "clima favorável a doenças de fungos", "data": umidos[0]["data"], "severidade": "media",
                        "detalhe": f"{len(umidos)} dias úmidos e amenos na semana"})
    return alertas


def resumo_para_llm(prev: dict) -> str:
    linhas = [f"Local: {prev['local']} | Fonte: {prev['fonte']}"]
    if prev.get("dados_de_exemplo"):
        linhas.append(prev["aviso"])
    for d in prev["dias"]:
        linhas.append(f"{d['data']}: {d['tmin']}-{d['tmax']} °C, chuva {d['chuva_mm']} mm "
                      f"({d['prob_chuva_pct']}%), ET0 {d['et0_mm']} mm, umidade {d.get('umidade_pct')}%")
    if prev["alertas"]:
        linhas.append("ALERTAS: " + "; ".join(f"{a['tipo']} em {a['data']} ({a['detalhe']})" for a in prev["alertas"]))
    else:
        linhas.append("Nenhum alerta de clima extremo na semana.")
    return "\n".join(linhas)
