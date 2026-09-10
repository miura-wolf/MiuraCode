from __future__ import annotations

import pytest

import app.embeddings as embeddings_module
import app.knowledge as knowledge_module
from app.db import fetch_all_vectors, save_knowledge, upsert_knowledge_vec
from app.embeddings import EmbeddingError, blob_to_vec, cosine_similarity, vec_to_blob


# ------------------------------------------------------------------
# Matemática pura (sin red)
# ------------------------------------------------------------------


def test_cosine_identical_is_one():
    v = [0.5, -1.25, 2.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)


def test_cosine_orthogonal_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 3.0]) == pytest.approx(0.0)


def test_cosine_mismatched_dims_or_empty_is_zero():
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_blob_roundtrip():
    original = [0.25, -3.75, 1024.125]
    restored = blob_to_vec(vec_to_blob(original))
    assert list(restored) == pytest.approx(original, rel=1e-6)


async def test_embed_query_requires_base_url():
    with pytest.raises(EmbeddingError):
        await embeddings_module.embed_query("hola")


# ------------------------------------------------------------------
# Búsqueda híbrida end-to-end con embedder falso (monkeypatched)
# ------------------------------------------------------------------


async def _fake_embedder(monkeypatch, query_vec, doc_dim):
    async def fake_embed_texts(texts):
        return [[*query_vec] for _ in texts]

    monkeypatch.setattr(embeddings_module, "embed_texts", fake_embed_texts)


async def test_semantic_only_hit(monkeypatch):
    """Entrada cuya superficie léxica NO comparte tokens con el query:
    FTS no la encuentra, pero su vector sí. La vía híbrida debe recuperarla."""
    monkeypatch.setattr(knowledge_module.settings, "embeddings_base_url", "http://fake-embed")
    monkeypatch.setattr(knowledge_module.settings, "hybrid_search", True)

    # FTS encuentra a la "trampa" por keywords; la target solo por vector.
    trap_id = await save_knowledge("manual deployment pipeline yaml", "usar helm chart del repo", "ops")
    target_id = await save_knowledge("receta familiar paella", "arroz bomba, azafran y fumet casero", "cocina")

    query_vec = [1.0, 0.0]
    await upsert_knowledge_vec(target_id, 2, vec_to_blob([1.0, 0.0]))
    await upsert_knowledge_vec(trap_id, 2, vec_to_blob([-1.0, 0.0]))  # opuesta: peor similitud
    await _fake_embedder(monkeypatch, query_vec, 2)

    results = await knowledge_module.search_hybrid("como cocinar comida espanola tradicional", limit=2)
    ids = [r["id"] for r in results]
    assert target_id in ids, "la entrada semánticamente relevante debe aparecer pese a no compartir keywords"
    sims = {r["id"]: r.get("similarity") for r in results}
    assert sims.get(target_id) == pytest.approx(1.0, abs=1e-4)

    # limpieza explícita del vector (delete_end-to-end ya cubierto en otro módulo)
    from app.db import clear_knowledge

    await clear_knowledge()


async def test_hybrid_degrades_to_fts_without_embedder(monkeypatch):
    monkeypatch.setattr(knowledge_module.settings, "embeddings_base_url", "")
    await save_knowledge("palabra clave unica qwertyuiop", "contenido igual de unico zxcvbnm", "x")
    results = await knowledge_module.search_hybrid("qwertyuiop")
    assert len(results) == 1 and results[0]["description"].startswith("palabra clave")


async def test_backfill_vectors_with_fake_embedder(monkeypatch):
    monkeypatch.setattr(knowledge_module.settings, "embeddings_base_url", "http://fake-embed")
    await save_knowledge("pendiente uno", "texto pendiente uno suficientemente completo", "a")
    await save_knowledge("pendiente dos", "texto pendiente dos igualmente largo", "a")

    calls: list[list[str]] = []

    async def fake_embed_texts(texts):
        calls.append(list(texts))
        return [[float(len(t))] * 4 for t in texts]

    monkeypatch.setattr(embeddings_module, "embed_texts", fake_embed_texts)
    stats = await knowledge_module.backfill_vectors(batch_size=10)

    assert stats["total_missing"] == 2 and stats["embedded"] == 2 and stats["failed"] == 0
    vecs = await fetch_all_vectors()
    assert len(vecs) == 2 and all(v["dim"] == 4 for v in vecs)
