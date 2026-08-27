from __future__ import annotations

"""Capa de servicio de la base de conocimiento (RAG).

Combina dos vías de recuperación:
- FTS5 (keywords): rápido y sin dependencias.
- Semántica: similitud coseno contra vectores persistidos en SQLite,
  calculados con un servidor OpenAI-compatible de embeddings (p. ej.
  llama-server con Qwen3-Embedding en otro puerto).

La fusión usa Reciprocal Rank Fusion (RRF). La vía semántica degrada
silenciosamente a solo-keywords si el servidor de embeddings no está
disponible — nunca bloquea el flujo principal del proxy."""

from typing import Any

from . import db
from .config import settings


# ------------------------------------------------------------------
# Escritura (con vectorización best-effort)
# ------------------------------------------------------------------

async def save_entry(description: str, content: str, category: str = "general") -> dict[str, Any]:
    """Guarda una entrada e intenta vectorizarla. Devuelve {"id", "embedded"}.
    Si el embedder no está disponible, la entrada queda guardada igualmente
    (participará solo por keywords)."""
    entry_id = await db.save_knowledge(description, content, category)
    embedded = False

    if settings.embeddings_base_url:
        from .embeddings import embed_document_safely

        blob, dim = await embed_document_safely(f"{description}\n{content}")
        if blob is not None:
            await db.upsert_knowledge_vec(entry_id, dim, blob)
            embedded = True

    return {"id": entry_id, "embedded": embedded}


async def delete_entry(entry_id: int) -> bool:
    """Elimina una entrada (fila + FTS + vector). True si existía."""
    return await db.delete_knowledge(entry_id)


async def description_exists(description: str) -> bool:
    """Anti-duplicado para auto-aprendizaje: igualdad exacta tras normalizar
    espacios. Evita guardar dos veces la misma solución; los near-duplicates
    se podan a mano vía DELETE admin."""
    normalized = " ".join((description or "").split())
    if not normalized:
        return False
    return await db.knowledge_description_count(normalized) > 0


async def backfill_vectors(batch_size: int = 32) -> dict[str, int]:
    """Vectoriza todas las entradas que aún no tienen vector persistido."""
    if not settings.embeddings_base_url:
        from .embeddings import EmbeddingError

        raise EmbeddingError("embeddings_base_url no está configurado")

    rows = await db.list_entries_without_vec()
    stats = {"total_missing": len(rows), "embedded": 0, "failed": 0}

    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        texts = [f"{r['description']}\n{r['content']}" for r in chunk]
        ids = [r["id"] for r in chunk]
        try:
            from .embeddings import embed_texts, vec_to_blob

            vectors = await embed_texts(texts)
        except Exception:
            stats["failed"] += len(ids)
            continue
        for row_id, vec in zip(ids, vectors):
            await db.upsert_knowledge_vec(row_id, len(vec), vec_to_blob(vec))
            stats["embedded"] += 1
    return stats


__all__ = [
    "backfill_vectors",
    "delete_entry",
    "description_exists",
    "save_entry",
    "search_hybrid",
]


# ------------------------------------------------------------------
# Lectura: fusión FTS ∪ semántica vía RRF
# ------------------------------------------------------------------

def _rrf_fuse(*rankings: list[int], k: int = 60, limit: int = 3) -> list[int]:
    """Reciprocal Rank Fusion sobre listas de ids ordenadas por relevancia.
    score(id) = Σ 1 / (k + posición). Devuelve los ids fusionados top-limit."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for pos, entry_id in enumerate(ranking):
            scores[entry_id] = scores.get(entry_id, 0.0) + 1.0 / (k + pos + 1)
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [entry_id for entry_id, _ in ordered[:limit]]


async def _semantic_ranking(query: str) -> Optional[list[dict[str, Any]]]:
    """Ranking por similitud coseno. Devuelve [{knowledge_id, similarity}]
    ordenado, o None si la vía semántica no está disponible o falla."""
    if not (settings.embeddings_base_url and settings.hybrid_search):
        return None
    try:
        from .embeddings import blob_to_vec, cosine_similarity, embed_query

        query_vec = await embed_query(query)
    except Exception:
        return None

    try:
        stored = await db.fetch_all_vectors()
    except Exception:
        return None

    scored: list[tuple[float, int]] = []
    for row in stored:
        if row["dim"] != len(query_vec):
            continue
        sim = cosine_similarity(query_vec, blob_to_vec(row["vec"]))
        scored.append((sim, row["knowledge_id"]))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    candidates = max(3, settings.hybrid_candidates)
    return [
        {"knowledge_id": entry_id, "similarity": round(sim, 6)}
        for sim, entry_id in scored[:candidates]
    ]


async def search_hybrid(query: str, limit: int = 3) -> list[dict[str, Any]]:
    """Búsqueda de conocimiento: keywords (FTS5) + semántica (coseno),
    fusionadas por RRF. Mantiene el formato de salida de db.search_knowledge
    para consumo transparente del motor."""

    async def _fts() -> list[dict[str, Any]]:
        try:
            return await db.search_knowledge(query, limit=max(limit, settings.hybrid_candidates))
        except Exception:
            return []

    fts_rows = await _fts()
    semantic_rows = await _semantic_ranking(query)

    # Vía semántica no disponible → comportamiento original.
    if not semantic_rows:
        return fts_rows[:limit]

    candidates = max(limit, settings.hybrid_candidates)
    needed_ids = list({row["id"] for row in fts_rows} | {row["knowledge_id"] for row in semantic_rows})
    by_id = await db.get_entries_by_ids(needed_ids)

    seen: set[int] = set()
    fts_ranked: list[int] = []
    for row in fts_rows[:candidates]:
        if row["id"] not in seen:
            seen.add(row["id"])
            fts_ranked.append(row["id"])

    fused_ids = _rrf_fuse(
        fts_ranked,
        [row["knowledge_id"] for row in semantic_rows],
        limit=candidates,
    )

    semantic_scores = {row["knowledge_id"]: row["similarity"] for row in semantic_rows}
    results: list[dict[str, Any]] = []
    for entry_id in fused_ids:
        entry = by_id.get(entry_id)
        if entry is None:
            continue
        enriched = dict(entry)
        enriched["similarity"] = semantic_scores.get(entry_id)
        results.append(enriched)
    return results[:limit]

