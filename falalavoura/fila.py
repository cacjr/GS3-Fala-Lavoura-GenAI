"""Fila do técnico (human in the loop).

Casos de risco viram uma "ficha" que um técnico de ATER valida. Na solução
completa isso alimenta o painel da Emater/cooperativa; aqui é um arquivo
JSONL local, já anonimizado.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from . import config
from .guardrails import anonimizar

PRIORIDADES = {"vermelho": "alta", "amarelo": "media", "verde": "baixa"}


def registrar(pergunta: str, perfil: dict, semaforo: str, motivo: str,
              resumo_ia: str, evidencias: list[str], descricao_imagem: str = "") -> dict:
    ficha = {
        "id": uuid.uuid4().hex[:8],
        "quando": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "prioridade": "máxima" if "emergência" in motivo.lower() else PRIORIDADES.get(semaforo, "media"),
        "semaforo": semaforo,
        # Só dados da roça. Nada de nome, CPF ou telefone.
        "municipio": perfil.get("cidade", ""),
        "cultura": perfil.get("cultura", ""),
        "dias_apos_plantio": perfil.get("dias_apos_plantio"),
        "pergunta": anonimizar(pergunta),
        "o_que_a_foto_mostra": anonimizar(descricao_imagem),
        "motivo_do_encaminhamento": motivo,
        "resposta_dada_pela_ia": anonimizar(resumo_ia),
        "fontes_consultadas": evidencias,
        "status": "aguardando técnico",
    }
    with open(config.ARQ_FILA_TECNICO, "a", encoding="utf-8") as f:
        f.write(json.dumps(ficha, ensure_ascii=False) + "\n")
    return ficha


def listar() -> list[dict]:
    if not config.ARQ_FILA_TECNICO.exists():
        return []
    linhas = config.ARQ_FILA_TECNICO.read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in reversed(linhas) if l.strip()]


def ficha_em_markdown(ficha: dict) -> str:
    return (f"**Ficha #{ficha['id']}** · {ficha['quando']} · prioridade **{ficha['prioridade']}**\n\n"
            f"- **Município:** {ficha['municipio'] or 'não informado'} · **Cultura:** {ficha['cultura']} "
            f"· **Dias após plantio:** {ficha['dias_apos_plantio']}\n"
            f"- **Pergunta:** {ficha['pergunta']}\n"
            + (f"- **O que a foto mostra:** {ficha['o_que_a_foto_mostra']}\n" if ficha["o_que_a_foto_mostra"] else "")
            + f"- **Por que veio para você:** {ficha['motivo_do_encaminhamento']}\n"
            f"- **Fontes consultadas pela IA:** {', '.join(ficha['fontes_consultadas']) or 'nenhuma'}\n"
            f"- **Status:** {ficha['status']}")
