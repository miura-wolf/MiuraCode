from __future__ import annotations

import array
import asyncio
import math
from typing import Any, Optional

import httpx

from .config import settings


class EmbeddingError(Exception):
    pass


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Calcula embeddings vía un servidor OpenAI-compatible (`/v1/embeddings`,
    p. ej. llama-server con --embedding). Devuelve una lista de vectores, uno
    por texto, respetando el orden de entrada."""
    if not settings.embeddings_base_url:
        raise EmbeddingError("embeddings_base_url no está configurado")
    if not texts:
        return []

    url = settings.embeddings_base_url.rstrip("/") + "/v1/embeddings"
    payload = {"input": texts, "model": settings.embeddings_model}
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=settings.embeddings_timeout_seconds) as client:
                resp = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            last_error = EmbeddingError(
                f"no se pudo contactar el servidor de embeddings: {exc}"
            )
            resp = None

        # 503 "Loading model": el servidor acepta conexiones mientras el modelo
        # termina de cargar — reintentar en vez de fallar de inmediato.
        if resp is not None and resp.status_code == 503:
            last_error = EmbeddingError("servidor de embeddings cargando modelo (503)")
            await asyncio.sleep(2.0 * (attempt + 1))
            continue
        if resp is not None:
            break

    if resp is None or resp.status_code >= 400:
        detail = resp.text[:300] if resp is not None else str(last_error)
        raise EmbeddingError(f"embeddings error: {detail}")

    data: list[dict[str, Any]] = resp.json().get("data") or []
    ordered = sorted(data, key=lambda item: item.get("index", 0))
    vectors = [item.get("embedding") for item in ordered]
    if len(vectors) != len(texts) or any(v is None for v in vectors):
        raise EmbeddingError("respuesta de embeddings incompleta")
    return vectors  # type: ignore[return-value]


def _maybe_truncate(text: str, max_chars: int = 8000) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


# ------------------------------------------------------------------
# Conversión vector <-> BLOB persistible en SQLite
# ------------------------------------------------------------------

def vec_to_blob(vec: list[float]) -> bytes:
    """Serializa un vector como float32 little-endian para guardarlo en un
    BLOB SQLite (4 bytes por dimensión)."""
    return array.array("f", vec).tobytes()


def blob_to_vec(blob: bytes) -> array.array[float]:
    """Deserializa un BLOB generado por vec_to_blob a un array de floats."""
    arr: array.array[float] = array.array("f")
    arr.frombytes(blob)
    return arr


def cosine_similarity(
    a: "array.array[float] | list[float]", b: "array.array[float] | list[float]"
) -> float:
    """Similitud coseno entre dos vectores del mismo tamaño. Si difieren en
    tamaño (o tienen norma cero) devuelve 0.0 — nunca lanza."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


# ------------------------------------------------------------------
# Operaciones compuestas usadas por la capa de conocimiento
# ------------------------------------------------------------------

async def embed_query(query: str) -> list[float]:
    """Embedding de un único query (el caso más común en búsqueda)."""
    vectors = await embed_texts([_maybe_truncate(query)])
    return vectors[0]


async def embed_document_safely(
    text: str,
) -> tuple[Optional[bytes], int]:
    """Devuelve (blob, dim) para persistir; si el embedder no está disponible
    devuelve (None, 0) sin lanzar — la degradación elegante es política aquí."""
    try:
        vector = await embed_texts([_maybe_truncate(text)])
    except EmbeddingError:
        return None, 0
    blob = vec_to_blob(vector[0])
    return blob, len(vector[0])


__all__ = [
    "EmbeddingError",
    "blob_to_vec",
    "cosine_similarity",
    "embed_document_safely",
    "embed_query",
    "embed_texts",
    "vec_to_blob",
]
