"""A lavoura fala de verdade: texto -> áudio (acessibilidade para quem lê pouco)."""
from __future__ import annotations

import re
import tempfile

from .texto import sem_emojis


def texto_para_fala(resposta_md: str) -> str:
    """Limpa a resposta para soar natural quando lida em voz alta."""
    texto = re.split(r"\*\*De onde tirei isso", sem_emojis(resposta_md))[0]  # fontes não precisam ser lidas
    texto = re.sub(r"\[[^\]]*#[^\]]*\]", "", texto)             # tira [milho#...]
    texto = re.sub(r"[*_#>`|]", "", texto)                       # tira markdown
    texto = texto.replace("A lavoura diz:", "").replace("O que fazer agora:", ". O que fazer agora.")
    texto = texto.replace("Como ter certeza:", ". Como ter certeza.")
    texto = re.sub(r"^\s*-\s*", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def gerar_audio(resposta_md: str) -> str | None:
    """Gera um mp3 com gTTS (voz do Google Tradutor, sotaque brasileiro)."""
    texto = texto_para_fala(resposta_md)
    if not texto:
        return None
    try:
        from gtts import gTTS

        arq = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        arq.close()
        gTTS(texto, lang="pt", tld="com.br").save(arq.name)
        return arq.name
    except Exception:
        return None  # sem internet o app continua funcionando, só sem áudio
