"""Configurações centrais do Fala, Lavoura!

Tudo que pode mudar entre computadores (chave, nome do modelo, limites da
API gratuita) fica em variáveis de ambiente, lidas do arquivo .env.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

PASTA_BASE = RAIZ / "base_conhecimento"
PASTA_DADOS = RAIZ / "dados"
PASTA_DADOS.mkdir(exist_ok=True)

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()

# Modelos (confira os nomes disponíveis no Google AI Studio e troque no .env se precisar)
MODELO_CHAT = os.getenv("MODELO_CHAT", "gemini-3.6-flash")
MODELO_FISCAL = os.getenv("MODELO_FISCAL", "gemini-3.5-flash-lite")  # cota diária separada do chat
# Usado automaticamente quando o principal está sobrecarregado (503) ou sem cota (429)
MODELO_RESERVA = os.getenv("MODELO_RESERVA", "gemini-3.1-flash-lite")
# Juiz da avaliação: de propósito um modelo DIFERENTE do que gera as respostas
MODELO_JUIZ = os.getenv("MODELO_JUIZ", "gemma-4-26b-a4b-it")
MODELO_EMBEDDING = os.getenv("MODELO_EMBEDDING", "gemini-embedding-001")

# O plano gratuito do Gemini limita requisições por minuto. O rate limiter do
# LangChain segura as chamadas para não estourar a cota.
REQUISICOES_POR_MINUTO = float(os.getenv("REQUISICOES_POR_MINUTO", "8"))
MAX_PASSOS_AGENTE = int(os.getenv("MAX_PASSOS_AGENTE", "5"))

# Busca
TOP_K = int(os.getenv("TOP_K", "4"))
RRF_K = 60  # constante da Reciprocal Rank Fusion (valor clássico do artigo original)
BONUS_CULTURA_POSICOES = int(os.getenv("BONUS_CULTURA_POSICOES", "1"))

ARQ_FILA_TECNICO = PASTA_DADOS / "fila_tecnico.jsonl"
ARQ_CACHE_EMBEDDINGS = PASTA_DADOS / "cache_embeddings.npz"
ARQ_CLIMA_EXEMPLO = PASTA_DADOS / "clima_exemplo.json"


def _faltando() -> list[str]:
    """Bibliotecas da IA generativa que não estão instaladas neste Python."""
    from importlib.util import find_spec

    pacotes = {"langchain_core": "langchain-core", "langchain_google_genai": "langchain-google-genai",
               "google.genai": "google-genai"}
    faltam = []
    for modulo, nome in pacotes.items():
        try:
            if find_spec(modulo) is None:
                faltam.append(nome)
        except ModuleNotFoundError:  # "google" inteiro ausente
            faltam.append(nome)
    return faltam


DEPENDENCIAS_FALTANDO = _faltando()


def motivo_sem_ia() -> str:
    """Explica, em português, por que a IA generativa está desligada (vazio = está ligada)."""
    if not GOOGLE_API_KEY:
        return "não encontrei a GOOGLE_API_KEY. Copie o .env.example para .env e coloque a sua chave."
    if DEPENDENCIAS_FALTANDO:
        return ("faltam bibliotecas neste Python (" + ", ".join(DEPENDENCIAS_FALTANDO) + "). "
                "Rode: pip install -r requirements.txt")
    return ""


def tem_chave() -> bool:
    """True quando a IA generativa pode ser usada: tem chave E as bibliotecas estão instaladas."""
    return not motivo_sem_ia()
