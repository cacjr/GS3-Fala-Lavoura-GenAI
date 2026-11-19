"""Percepção multimodal com Gemini: foto da planta -> descrição de sintomas,
áudio do agricultor -> texto.

A foto NÃO vira diagnóstico direto. Ela vira uma descrição em texto que
depois passa pela busca na base (RAG). Assim a conclusão sempre vem das
fichas técnicas, e não da "imaginação" do modelo de visão.
"""
from __future__ import annotations

import io
import mimetypes
from pathlib import Path

from . import config, prompts


_CLIENTE = None


def _cliente():
    """Um cliente só para o app todo. (Criar um por chamada fazia o SDK fechar a
    conexão antes da resposta chegar: bug encontrado no teste de áudio.)"""
    global _CLIENTE
    if _CLIENTE is None:
        from google import genai
        from google.genai import types
        _CLIENTE = genai.Client(api_key=config.GOOGLE_API_KEY,
                                http_options=types.HttpOptions(timeout=60000))
    return _CLIENTE


def _gerar(conteudo: list) -> str:
    """Tenta o modelo principal e, se estiver fora do ar, o reserva."""
    erro_final = None
    for modelo in (config.MODELO_CHAT, config.MODELO_RESERVA):
        try:
            resp = _cliente().models.generate_content(model=modelo, contents=conteudo)
            return (resp.text or "").strip()
        except Exception as erro:
            erro_final = erro
    raise erro_final


def _bytes_imagem(caminho: str, lado_max: int = 1024) -> tuple[bytes, str]:
    """Reduz a foto (celular manda fotos enormes) para economizar dados e tokens."""
    from PIL import Image

    img = Image.open(caminho)
    img = img.convert("RGB")
    img.thumbnail((lado_max, lado_max))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


def descrever_imagem(caminho: str) -> str:
    from google.genai import types

    dados, mime = _bytes_imagem(caminho)
    return _gerar([types.Part.from_bytes(data=dados, mime_type=mime), prompts.VISAO])


def transcrever_audio(caminho: str) -> str:
    from google.genai import types

    mime = mimetypes.guess_type(caminho)[0] or "audio/wav"
    dados = Path(caminho).read_bytes()
    return _gerar([types.Part.from_bytes(data=dados, mime_type=mime), prompts.TRANSCRICAO])
