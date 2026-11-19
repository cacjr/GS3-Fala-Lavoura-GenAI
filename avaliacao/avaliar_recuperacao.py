"""Avaliação da recuperação (o "R" do RAG) com estudo de ablação.

Compara configurações para mostrar o quanto cada peça ajuda:
  A) BM25 puro                         (sem dicionário, sem bônus de cultura)
  B) BM25 + Dicionário da Roça
  C) BM25 + Dicionário + bônus de cultura
  D) Embeddings Gemini + Dicionário + bônus          (precisa de chave)
  E) Híbrido RRF (BM25 + embeddings) + Dicionário + bônus  (precisa de chave)

Métricas: Hit@1, Hit@3, MRR (perguntas dentro do escopo) e acerto do
detector de "não sei" (perguntas fora do escopo devem dar evidência fraca).

Rodar:  python avaliacao/avaliar_recuperacao.py
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from falalavoura import config  # noqa: E402
from falalavoura.conhecimento import Buscador  # noqa: E402

PERGUNTAS = json.loads((RAIZ / "avaliacao" / "perguntas_recuperacao.json").read_text(encoding="utf-8"))
SAIDA = RAIZ / "avaliacao" / "resultados"
SAIDA.mkdir(parents=True, exist_ok=True)

CONFIGS = [
    ("A) BM25 puro", dict(modo="bm25", usar_dicionario=False, com_cultura=False)),
    ("B) BM25 + dicionário", dict(modo="bm25", usar_dicionario=True, com_cultura=False)),
    ("C) BM25 + dicionário + cultura", dict(modo="bm25", usar_dicionario=True, com_cultura=True)),
    ("D) Embeddings + dicionário + cultura", dict(modo="denso", usar_dicionario=True, com_cultura=True)),
    ("E) Híbrido RRF + dicionário + cultura", dict(modo="hibrido", usar_dicionario=True, com_cultura=True)),
]


def avaliar(buscador: Buscador, modo: str, usar_dicionario: bool, com_cultura: bool):
    hits1 = hits3 = rr = n = 0
    fora_ok = fora_n = falso_nao_sei = 0
    detalhes = []
    for q in PERGUNTAS:
        res, diag = buscador.buscar(q["pergunta"], q["cultura"] if com_cultura else "", k=5,
                                    modo=modo, usar_dicionario=usar_dicionario)
        ids = [r.trecho.id for r in res]
        if q["esperados"]:
            n += 1
            pos = next((i + 1 for i, x in enumerate(ids) if x in q["esperados"]), None)
            hits1 += pos == 1
            hits3 += bool(pos and pos <= 3)
            rr += 1 / pos if pos else 0
            falso_nao_sei += diag["forca_evidencia"] == "fraca"
            detalhes.append({"pergunta": q["pergunta"], "posicao_correta": pos, "top3": ids[:3],
                             "forca": diag["forca_evidencia"]})
        else:
            fora_n += 1
            fora_ok += diag["forca_evidencia"] == "fraca"
            detalhes.append({"pergunta": q["pergunta"], "fora_do_escopo": True, "forca": diag["forca_evidencia"],
                             "top3": ids[:3]})
    return {
        "Hit@1": round(hits1 / n, 3), "Hit@3": round(hits3 / n, 3), "MRR": round(rr / n, 3),
        "Fora do escopo detectado": f"{fora_ok}/{fora_n}",
        "'Não sei' indevido (dentro do escopo)": f"{falso_nao_sei}/{n}",
    }, detalhes


def main():
    buscador = Buscador()
    linhas, todos_detalhes = [], {}
    for nome, cfg in CONFIGS:
        if cfg["modo"] != "bm25" and not buscador.tem_denso:
            print(f"{nome}: pulado (sem GOOGLE_API_KEY)")
            continue
        metricas, det = avaliar(buscador, **cfg)
        linhas.append({"Configuração": nome, **metricas})
        todos_detalhes[nome] = det
        print(nome, metricas)

    n_dentro = sum(1 for q in PERGUNTAS if q["esperados"])
    cab = list(linhas[0].keys())
    md = [f"# Avaliação da recuperação\n",
          f"{n_dentro} perguntas dentro do escopo + {len(PERGUNTAS) - n_dentro} fora do escopo, "
          f"escritas no jeito de falar do agricultor. Base com {len(buscador.trechos)} trechos. "
          f"Modelo de embedding: `{config.MODELO_EMBEDDING}`.\n",
          "| " + " | ".join(cab) + " |", "|" + "---|" * len(cab)]
    md += ["| " + " | ".join(str(l[c]) for c in cab) + " |" for l in linhas]

    melhor = linhas[-1]["Configuração"]
    md.append(f"\n## Erros da configuração {melhor}\n")
    for d in todos_detalhes[melhor]:
        if d.get("fora_do_escopo"):
            if d["forca"] != "fraca":
                md.append(f"- (fora do escopo, mas evidência **{d['forca']}**) “{d['pergunta']}” → {d['top3']}")
        elif d["posicao_correta"] != 1:
            md.append(f"- “{d['pergunta']}”: correto na posição {d['posicao_correta']} · top3 {d['top3']}")
    (SAIDA / "recuperacao.md").write_text("\n".join(md), encoding="utf-8")
    (SAIDA / "recuperacao_detalhes.json").write_text(json.dumps(todos_detalhes, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nRelatório salvo em {SAIDA / 'recuperacao.md'}")


if __name__ == "__main__":
    main()
