import json
from typing import Any, Optional

from .schemas import ChatCompletionChunk, ChunkChoice, DeltaMessage


def format_sse(chunk: ChatCompletionChunk) -> str:
    return f"data: {chunk.model_dump_json()}\n\n"


def reasoning_chunk(model: str, text: str, chunk_id: str) -> str:
    chunk = ChatCompletionChunk(
        id=chunk_id,
        model=model,
        choices=[ChunkChoice(delta=DeltaMessage(reasoning_content=text))],
    )
    return format_sse(chunk)


def content_chunk(model: str, text: str, chunk_id: str) -> str:
    chunk = ChatCompletionChunk(
        id=chunk_id,
        model=model,
        choices=[ChunkChoice(delta=DeltaMessage(content=text))],
    )
    return format_sse(chunk)


def role_chunk(model: str, chunk_id: str) -> str:
    chunk = ChatCompletionChunk(
        id=chunk_id,
        model=model,
        choices=[ChunkChoice(delta=DeltaMessage(role="assistant"))],
    )
    return format_sse(chunk)


def raw_delta_chunk(model: str, delta: dict[str, Any], chunk_id: str) -> str:
    chunk = ChatCompletionChunk(
        id=chunk_id,
        model=model,
        choices=[
            ChunkChoice(
                delta=DeltaMessage(
                    content=delta.get("content"),
                    reasoning_content=delta.get("reasoning_content"),
                    tool_calls=delta.get("tool_calls"),
                )
            )
        ],
    )
    return format_sse(chunk)


def final_chunk(model: str, chunk_id: str, finish_reason: Optional[str] = "stop") -> str:
    chunk = ChatCompletionChunk(
        id=chunk_id,
        model=model,
        choices=[ChunkChoice(delta=DeltaMessage(), finish_reason=finish_reason)],
    )
    return format_sse(chunk)


def done() -> str:
    return "data: [DONE]\n\n"


def progress_chunk(model: str, progress: dict[str, Any], chunk_id: str) -> str:
    """F4: chunk SSE de progreso para clientes agénticos. Lleva un campo extra
    `progress` (fuera del protocolo OpenAI estándar) que los clientes normales
    ignoran y los agénticos pueden parsear para mostrar progreso real del árbol
    (phase_started/leaf_started/leaf_done/phase_done/done). Se construye como
    JSON crudo para no alterar el schema pydantic compatible con OpenAI."""
    payload = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [],
        "progress": progress,
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
