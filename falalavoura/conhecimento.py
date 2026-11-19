"""Base de conhecimento e busca híbrida (o "R" do RAG).

Pipeline de recuperação:
  1. pergunta do agricultor  ->  Dicionário da Roça (expansão de consulta)
  2. busca lexical BM25 (implementada aqui, funciona sem internet)
  3. busca semântica com embeddings do Gemini (quando existe chave)
  4. fusão das duas listas com Reciprocal Rank Fusion (RRF)
  5. bônus para trechos da cultura que o agricultor está plantando
  6. medida de "força da evidência" para o agente saber quando NÃO sabe
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import config
from .texto import normalizar, slug, tokens


@dataclass
class Trecho:
    id: str              # ex.: "milho#lagarta-do-cartucho"
    doc: str             # nome do arquivo sem extensão
    titulo_doc: str
    cultura: str         # milho, feijao, ... ou "geral"
    secao: str
    texto: str
    referencias: str = ""

    @property
    def texto_indexado(self) -> str:
        # O título da ficha e da seção entram no índice: ajudam muito o BM25.
        return f"{self.titulo_doc}. {self.secao}. {self.texto}"


@dataclass
class Resultado:
    trecho: Trecho
    score: float
    rank_bm25: int | None = None
    rank_denso: int | None = None
    detalhes: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Leitura e divisão das fichas em trechos (chunking por seção)
# ---------------------------------------------------------------------------
def carregar_trechos(pasta: Path = config.PASTA_BASE) -> list[Trecho]:
    trechos = []
    for arq in sorted(pasta.glob("*.md")):
        linhas = arq.read_text(encoding="utf-8").splitlines()
        titulo, meta, secao, corpo = arq.stem, {}, None, []

        def fechar():
            if secao and corpo:
                texto = " ".join(l.strip() for l in corpo if l.strip())
                trechos.append(Trecho(
                    id=f"{arq.stem}#{slug(secao)}", doc=arq.stem,
                    titulo_doc=titulo, cultura=meta.get("cultura", "geral"),
                    secao=secao, texto=texto, referencias=meta.get("referencias", ""),
                ))

        for linha in linhas:
            if linha.startswith("# "):
                titulo = linha[2:].strip()
            elif linha.startswith("> ") and ":" in linha and secao is None:
                chave, valor = linha[2:].split(":", 1)
                meta[chave.strip()] = valor.strip()
            elif linha.startswith("## "):
                fechar()
                secao, corpo = linha[3:].strip(), []
            elif secao:
                corpo.append(linha)
        fechar()
    return trechos


def carregar_dicionario(pasta: Path = config.PASTA_BASE) -> dict[str, str]:
    dados = json.loads((pasta / "dicionario_da_roca.json").read_text(encoding="utf-8"))
    return {normalizar(k): v for k, v in dados.items() if not k.startswith("_")}


def expandir_consulta(consulta: str, dicionario: dict[str, str]) -> tuple[str, list[str]]:
    """Acrescenta termos técnicos quando acha expressões populares na pergunta."""
    norm = normalizar(consulta)
    achados = [chave for chave in dicionario if re.search(rf"\b{re.escape(chave)}", norm)]
    extras = " ".join(dicionario[c] for c in achados)
    return (f"{consulta} {extras}".strip(), achados)


# ---------------------------------------------------------------------------
# BM25 (Okapi) feito à mão
# ---------------------------------------------------------------------------
class BM25:
    def __init__(self, documentos: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(d) for d in documentos]
        self.tamanhos = [len(d) for d in documentos]
        self.media = sum(self.tamanhos) / max(1, len(documentos))
        n = len(documentos)
        df = Counter(t for d in documentos for t in set(d))
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def pontuar(self, consulta: list[str]) -> np.ndarray:
        notas = np.zeros(len(self.docs))
        for i, (freq, tam) in enumerate(zip(self.docs, self.tamanhos)):
            s = 0.0
            for termo in consulta:
                if termo not in freq:
                    continue
                f = freq[termo]
                s += self.idf[termo] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * tam / self.media))
            notas[i] = s
        return notas


# ---------------------------------------------------------------------------
# Buscador híbrido
# ---------------------------------------------------------------------------
class Buscador:
    def __init__(self, usar_embeddings: bool | None = None):
        self.trechos = carregar_trechos()
        self.dicionario = carregar_dicionario()
        self.tokens_trechos = [tokens(t.texto_indexado) for t in self.trechos]
        self.bm25 = BM25(self.tokens_trechos)
        self.embedder = None
        self.matriz = None
        self._cache_consultas: dict[str, np.ndarray] = {}
        if usar_embeddings is None:
            usar_embeddings = config.tem_chave()
        if usar_embeddings:
            self._preparar_embeddings()

    # ===== embeddings com cache em disco (economiza cota da API) =====
    def _preparar_embeddings(self):
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        self.embedder = GoogleGenerativeAIEmbeddings(model=config.MODELO_EMBEDDING, google_api_key=config.GOOGLE_API_KEY)
        textos = [t.texto_indexado for t in self.trechos]
        assinatura = hashlib.sha256(("|".join(textos) + config.MODELO_EMBEDDING).encode()).hexdigest()
        cache = config.ARQ_CACHE_EMBEDDINGS
        if cache.exists():
            dados = np.load(cache, allow_pickle=False)
            if str(dados["assinatura"]) == assinatura:
                self.matriz = dados["matriz"]
                return
        vetores = np.array(self.embedder.embed_documents(textos), dtype=np.float32)
        self.matriz = vetores / np.linalg.norm(vetores, axis=1, keepdims=True)
        np.savez(cache, matriz=self.matriz, assinatura=np.array(assinatura))

    @property
    def tem_denso(self) -> bool:
        return self.matriz is not None

    def _similaridades(self, consulta: str) -> np.ndarray:
        if consulta not in self._cache_consultas:
            for tentativa in range(4):
                try:
                    vetor = self.embedder.embed_query(consulta)
                    break
                except Exception as erro:  # cota por minuto do plano gratuito: espera e tenta de novo
                    if "429" not in str(erro) or tentativa == 3:
                        raise
                    time.sleep(45)
            q = np.array(vetor, dtype=np.float32)
            self._cache_consultas[consulta] = q / np.linalg.norm(q)
        return self.matriz @ self._cache_consultas[consulta]

    def _similaridades_com_prazo(self, consulta: str, segundos: float = 30) -> np.ndarray:
        """Mesma coisa, mas desiste se a API não responder no prazo (internet do campo...)."""
        if consulta in self._cache_consultas:
            return self._similaridades(consulta)
        ex = ThreadPoolExecutor(max_workers=1)
        try:
            return ex.submit(self._similaridades, consulta).result(timeout=segundos)
        finally:
            ex.shutdown(wait=False)  # não fica esperando a chamada travada

    # ===== busca =====
    def buscar(self, consulta: str, cultura: str = "", k: int = config.TOP_K,
               modo: str = "hibrido", usar_dicionario: bool = True,
               bonus_posicoes: int = config.BONUS_CULTURA_POSICOES) -> tuple[list[Resultado], dict]:
        """Retorna (resultados, diagnostico).

        modo: "bm25", "denso" ou "hibrido". Sem chave, "hibrido" vira "bm25".
        """
        expandida, achados = expandir_consulta(consulta, self.dicionario) if usar_dicionario else (consulta, [])
        toks = tokens(expandida)
        if modo != "bm25" and not self.tem_denso:
            modo = "bm25"

        rankings: dict[str, list[int]] = {}
        notas_bm25 = self.bm25.pontuar(toks)
        if modo in ("bm25", "hibrido"):
            rankings["bm25"] = [i for i in np.argsort(-notas_bm25) if notas_bm25[i] > 0]
        sims = None
        if modo in ("denso", "hibrido"):
            try:
                sims = self._similaridades_com_prazo(expandida)
                rankings["denso"] = list(np.argsort(-sims))
            except Exception:
                # Degradação graciosa: sem embeddings (rede ruim, cota), segue só com BM25.
                if modo == "denso":
                    raise
                modo = "bm25 (denso indisponível)"

        # Reciprocal Rank Fusion: soma 1/(60 + posição) de cada lista
        fusao: dict[int, float] = {}
        for lista in rankings.values():
            for pos, idx in enumerate(lista):
                fusao[idx] = fusao.get(idx, 0.0) + 1.0 / (config.RRF_K + pos + 1)

        # Bônus para a cultura do agricultor, equivalente a "subir N posições".
        # (A 1ª versão dava um bônus fixo de meio 1º lugar e PIOROU o Hit@1 de
        # 0,82 para 0,61 na avaliação: qualquer trecho da cultura passava na frente.)
        cultura_n = normalizar(cultura) if cultura else ""
        if cultura_n and bonus_posicoes > 0:
            bonus = (1.0 / (config.RRF_K + 1) - 1.0 / (config.RRF_K + 1 + bonus_posicoes)) * len(rankings)
            for idx in fusao:
                if self.trechos[idx].cultura == cultura_n:
                    fusao[idx] += bonus

        ordem = sorted(fusao, key=fusao.get, reverse=True)[:k]
        resultados = []
        for idx in ordem:
            r = Resultado(trecho=self.trechos[idx], score=round(fusao[idx], 5))
            if "bm25" in rankings and idx in rankings["bm25"]:
                r.rank_bm25 = rankings["bm25"].index(idx) + 1
            if "denso" in rankings:
                r.rank_denso = rankings["denso"].index(idx) + 1
                r.detalhes["similaridade"] = round(float(sims[idx]), 3)
            resultados.append(r)

        forca, cobertura = self._forca(tokens(consulta), toks, resultados, sims)
        diagnostico = {
            "modo": modo,
            "termos_do_dicionario": achados,
            "forca_evidencia": forca,
            "cobertura_lexical": cobertura,
        }
        return resultados, diagnostico

    def _forca(self, toks_orig: list[str], toks_exp: list[str], resultados: list[Resultado], sims) -> tuple[str, float]:
        """Classifica a evidência como forte, media ou fraca.

        Cobertura = fração dos termos da consulta (original ou expandida pelo
        dicionário) que aparecem num mesmo trecho recuperado; vale o melhor
        trecho. É uma medida lexical, simples e explicável. A similaridade
        semântica só pode "promover" uma evidência fraca para média.
        """
        if not resultados or not toks_exp:
            return "fraca", 0.0
        melhor, melhor_sim = 0.0, 0.0
        for r in resultados:
            idx = self.trechos.index(r.trecho)
            presentes = set(self.tokens_trechos[idx])
            for toks in (toks_orig, toks_exp):
                unicos = set(toks)
                if unicos:
                    melhor = max(melhor, len(unicos & presentes) / len(unicos))
            if sims is not None:
                melhor_sim = max(melhor_sim, float(sims[idx]))
        if melhor >= 0.5:
            return "forte", round(melhor, 2)
        if melhor >= 0.3 or melhor_sim >= 0.75:
            return "media", round(melhor, 2)
        return "fraca", round(melhor, 2)


def formatar_para_llm(resultados: list[Resultado], diagnostico: dict) -> str:
    """Texto que volta para o agente como resultado da ferramenta."""
    if diagnostico["forca_evidencia"] == "fraca":
        cab = ("EVIDÊNCIA FRACA: a base de conhecimento não tem informação clara sobre isso. "
               "Diga com honestidade que não sabe e sugira procurar a Emater/técnico. Não invente.\n")
    else:
        cab = f"Evidência {diagnostico['forca_evidencia']}. Use só o que está abaixo e cite os ids entre colchetes.\n"
    partes = [cab]
    for r in resultados:
        partes.append(f"[{r.trecho.id}] ({r.trecho.titulo_doc} > {r.trecho.secao})\n{r.trecho.texto}\n")
    return "\n".join(partes)
