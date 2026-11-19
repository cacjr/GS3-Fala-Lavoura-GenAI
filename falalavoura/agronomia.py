"""Cálculos agronômicos determinísticos.

Princípio do projeto: "a IA não faz conta, a IA conta a história".
Números (fase da planta, litros de água) saem daqui, de código testável,
e o modelo generativo só transforma isso em conversa. Assim evitamos que o
LLM invente valores.

Referência dos coeficientes: FAO Irrigation and Drainage Paper 56
(Allen et al., 1998), tabelas 11 e 12, com durações ajustadas para
ciclos típicos de agricultura familiar no Brasil.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .texto import normalizar


@dataclass(frozen=True)
class Fase:
    chave: str          # inicial, desenvolvimento, intermediaria, final
    dias: int
    descricao: str
    critica: bool = False


@dataclass(frozen=True)
class Cultura:
    nome: str
    fases: tuple[Fase, ...]
    kc_ini: float
    kc_mid: float
    kc_fim: float
    armazenamento_mm: float  # água útil que a zona da raiz segura (aproximação)

    @property
    def ciclo(self) -> int:
        return sum(f.dias for f in self.fases)


CULTURAS: dict[str, Cultura] = {
    "milho": Cultura("milho", (
        Fase("inicial", 20, "germinação e plantinha nova (até umas 4 folhas)"),
        Fase("desenvolvimento", 35, "crescimento das folhas; época da adubação de cobertura"),
        Fase("intermediaria", 40, "pendoamento, cabelo da espiga e enchimento dos grãos", critica=True),
        Fase("final", 30, "maturação e secagem dos grãos"),
    ), 0.30, 1.20, 0.60, 45),
    "feijao": Cultura("feijão", (
        Fase("inicial", 15, "germinação e primeiras folhas"),
        Fase("desenvolvimento", 25, "crescimento das ramas e folhas"),
        Fase("intermediaria", 35, "florescimento e formação das vagens", critica=True),
        Fase("final", 20, "maturação e secagem das vagens"),
    ), 0.40, 1.15, 0.35, 30),
    "mandioca": Cultura("mandioca", (
        Fase("inicial", 30, "brotação das manivas e enraizamento", critica=True),
        Fase("desenvolvimento", 60, "formação das hastes e folhas", critica=True),
        Fase("intermediaria", 150, "engrossamento das raízes"),
        Fase("final", 60, "maturação e repouso"),
    ), 0.30, 0.80, 0.30, 50),
    "tomate": Cultura("tomate", (
        Fase("inicial", 30, "pegamento das mudas após o transplante"),
        Fase("desenvolvimento", 40, "crescimento e início da florada"),
        Fase("intermediaria", 40, "florada e formação dos frutos", critica=True),
        Fase("final", 25, "maturação e colheita dos frutos"),
    ), 0.60, 1.15, 0.80, 30),
    "alface": Cultura("alface", (
        Fase("inicial", 15, "pegamento das mudas após o transplante"),
        Fase("desenvolvimento", 20, "crescimento das folhas", critica=True),
        Fase("intermediaria", 15, "formação da cabeça", critica=True),
        Fase("final", 5, "ponto de colheita"),
    ), 0.70, 1.00, 0.95, 15),
}

EFICIENCIA_IRRIGACAO = {
    "gotejamento": 0.90,
    "aspersao": 0.75,
    "mangueira ou regador": 0.65,
}


def obter_cultura(nome: str) -> Cultura:
    chave = normalizar(nome).strip()
    if chave not in CULTURAS:
        raise ValueError(f"Cultura '{nome}' não cadastrada. Opções: {', '.join(CULTURAS)}")
    return CULTURAS[chave]


def dias_desde(data_plantio: str, hoje: date | None = None) -> int:
    """Aceita 'dd/mm/aaaa' ou 'aaaa-mm-dd'."""
    hoje = hoje or date.today()
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return (hoje - datetime.strptime(data_plantio.strip(), formato).date()).days
        except ValueError:
            continue
    raise ValueError("Data do plantio inválida. Use o formato dd/mm/aaaa.")


def kc_no_dia(cultura: Cultura, dap: int) -> float:
    """Curva do Kc da FAO-56: constante, rampa, constante, rampa."""
    ini, dev, mid, fim = (f.dias for f in cultura.fases)
    if dap <= ini:
        return cultura.kc_ini
    if dap <= ini + dev:
        return cultura.kc_ini + (dap - ini) / dev * (cultura.kc_mid - cultura.kc_ini)
    if dap <= ini + dev + mid:
        return cultura.kc_mid
    if dap <= cultura.ciclo:
        return cultura.kc_mid + (dap - ini - dev - mid) / fim * (cultura.kc_fim - cultura.kc_mid)
    return cultura.kc_fim


def fase_da_cultura(nome: str, dap: int) -> dict:
    cultura = obter_cultura(nome)
    if dap < 0:
        return {"cultura": cultura.nome, "erro": "data de plantio no futuro"}
    acumulado = 0
    for i, fase in enumerate(cultura.fases):
        if dap <= acumulado + fase.dias:
            dias_restantes = acumulado + fase.dias - dap
            proxima = cultura.fases[i + 1] if i + 1 < len(cultura.fases) else None
            return {
                "cultura": cultura.nome,
                "dias_apos_plantio": dap,
                "fase": fase.chave,
                "descricao_fase": fase.descricao,
                "fase_critica_para_agua": fase.critica,
                "dias_ate_proxima_fase": dias_restantes,
                "proxima_fase": proxima.descricao if proxima else "colheita",
                "proxima_fase_e_critica": bool(proxima and proxima.critica),
                "kc_hoje": round(kc_no_dia(cultura, dap), 2),
                "ciclo_aproximado_dias": cultura.ciclo,
                "progresso_ciclo_pct": round(100 * dap / cultura.ciclo),
            }
        acumulado += fase.dias
    return {
        "cultura": cultura.nome, "dias_apos_plantio": dap, "fase": "ciclo concluido",
        "descricao_fase": "passou do ciclo típico: provavelmente em ponto de colheita",
        "fase_critica_para_agua": False, "kc_hoje": cultura.kc_fim,
        "ciclo_aproximado_dias": cultura.ciclo, "progresso_ciclo_pct": 100,
    }


def chuva_efetiva(chuva_mm: float) -> float:
    """Chuvinha abaixo de 2 mm quase não chega na raiz; acima disso, 80% aproveita."""
    return 0.0 if chuva_mm < 2 else 0.8 * chuva_mm


def balanco_hidrico(nome: str, dap: int, previsao: list[dict], area_m2: float = 0,
                    sistema: str = "gotejamento", umidade_inicial: float = 0.5) -> dict:
    """Balanço hídrico diário tipo "balde" para os próximos dias.

    previsao: lista de {"data", "et0_mm", "chuva_mm"} (vem do clima.py).
    Premissa: o solo começa com metade da água útil (umidade_inicial=0,5),
    porque o app não tem sensor de umidade. Isso é dito ao usuário.
    """
    cultura = obter_cultura(nome)
    cap = cultura.armazenamento_mm
    agua = umidade_inicial * cap
    dias, total_irr, total_etc, total_chuva, total_excesso = [], 0.0, 0.0, 0.0, 0.0

    for i, d in enumerate(previsao):
        kc = kc_no_dia(cultura, dap + i)
        etc = d["et0_mm"] * kc
        pe = chuva_efetiva(d["chuva_mm"])
        agua += pe
        excesso = max(0.0, agua - cap)
        agua = min(agua, cap)
        agua -= etc
        irr = 0.0
        if agua < 0:
            irr, agua = -agua, 0.0
        dias.append({
            "data": d["data"], "kc": round(kc, 2), "consumo_planta_mm": round(etc, 1),
            "chuva_mm": d["chuva_mm"], "chuva_aproveitada_mm": round(pe, 1),
            "irrigar_mm": round(irr, 1), "agua_no_solo_pct": round(100 * agua / cap),
        })
        total_irr += irr
        total_etc += etc
        total_chuva += d["chuva_mm"]
        total_excesso += excesso

    sistema_n = normalizar(sistema)
    eficiencia = next((v for k, v in EFICIENCIA_IRRIGACAO.items() if k.split()[0] in sistema_n), None)
    litros_m2 = total_irr / eficiencia if eficiencia else total_irr  # 1 mm = 1 L/m²

    if total_irr == 0 and total_excesso > 20:
        estado = "com água demais"
    elif total_irr == 0:
        estado = "com água na medida"
    elif total_irr < 0.3 * total_etc:
        estado = "com um pouco de sede"
    else:
        estado = "com muita sede"

    resumo = {
        "cultura": cultura.nome,
        "periodo_dias": len(previsao),
        "estado_da_lavoura": estado,
        "consumo_total_planta_mm": round(total_etc, 1),
        "chuva_prevista_total_mm": round(total_chuva, 1),
        "irrigacao_necessaria_mm": round(total_irr, 1),
        "litros_por_m2_no_periodo": round(litros_m2, 1),
        "sistema": sistema,
        "eficiencia_sistema": eficiencia,
        "excesso_de_chuva_mm": round(total_excesso, 1),
        "dias": dias,
        "premissas": [
            "método FAO-56: consumo da planta = ET0 x Kc",
            "solo começa com metade da água útil (sem sensor de umidade)",
            "chuva abaixo de 2 mm não conta; acima disso, 80% é aproveitada",
            f"água útil na zona da raiz do(a) {cultura.nome}: {cap:.0f} mm",
        ],
    }
    if area_m2 and area_m2 > 0:
        resumo["area_m2"] = area_m2
        resumo["litros_total_no_periodo"] = round(litros_m2 * area_m2)
        dias_com_rega = sum(1 for x in dias if x["irrigar_mm"] > 0)
        resumo["dias_com_rega"] = dias_com_rega
        if dias_com_rega:
            resumo["litros_por_dia_de_rega"] = round(litros_m2 * area_m2 / dias_com_rega)
    return resumo
