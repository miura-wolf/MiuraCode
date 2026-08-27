from __future__ import annotations

import pytest

from app.config import settings
from app.db import (
    delete_knowledge,
    get_entries_by_ids,
    knowledge_description_count,
    list_entries_without_vec,
    save_knowledge,
    search_knowledge,
    upsert_knowledge_vec,
)


# ------------------------------------------------------------------
# CRUD directo en db.py
# ------------------------------------------------------------------


async def test_delete_knowledge_removes_row_and_fts():
    kid = await save_knowledge("Manual de despliegue", "usar helm upgrade --install", "docs")
    assert await search_knowledge("despliegue") != []
    assert await delete_knowledge(kid) is True
    assert await search_knowledge("despliegue") == []
    assert await delete_knowledge(kid) is False  # segunda vez: ya no existe


async def test_description_count_exact_match():
    await save_knowledge("convencion naming python", "snake_case", "general")
    assert await knowledge_description_count("convencion naming python") == 1
    assert await knowledge_description_count("otra cosa distinta") == 0


async def test_vector_roundtrip_and_missing_list():
    k1 = await save_knowledge("entrada A", "contenido A largo para el test", "x")
    k2 = await save_knowledge("entrada B", "contenido B también largo", "x")
    await upsert_knowledge_vec(k1, 2, bytes(8))

    missing = await list_entries_without_vec()
    assert [r["id"] for r in missing] == [k2]

    by_id = await get_entries_by_ids([k1, k2])
    assert by_id[k1]["description"] == "entrada A"
    assert by_id[k2]["description"] == "entrada B"

    from app.db import fetch_all_vectors

    await upsert_knowledge_vec(k1, 3, bytes(12))  # upsert sobrescribe dim y vec
    vecs = await fetch_all_vectors()
    assert {v["knowledge_id"]: v["dim"] for v in vecs} == {k1: 3}


# ------------------------------------------------------------------
# Endpoints admin (/v1/knowledge*)
# ------------------------------------------------------------------


async def test_post_then_search_and_stats(client):
    resp = await client.post(
        "/v1/knowledge",
        json={
            "description": "Convención de naming del proyecto",
            "content": "snake_case para variables, PascalCase para clases",
            "category": "convenciones",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["embedded"] is False  # sin embedder en tests → solo keywords
    assert isinstance(body["id"], int)

    found = await client.get("/v1/knowledge", params={"q": "naming", "limit": 5})
    assert found.status_code == 200
    data = found.json()["data"]
    assert any(r["description"].startswith("Convención de naming") for r in data)

    stats = await client.get("/v1/knowledge/stats")
    s = stats.json()
    assert s["total"] >= 1
    assert s["by_category"].get("convenciones") >= 1
    assert s["with_vector"] == 0

    listing = await client.get("/v1/knowledge")
    assert listing.json()["mode"] == "recent"
    assert any(item["has_vector"] is not None for item in listing.json()["data"])


async def test_post_validation_error(client):
    resp = await client.post("/v1/knowledge", json={"description": "", "content": ""})
    assert resp.status_code == 422


async def test_delete_endpoint_404_when_absent(client):
    resp = await client.delete("/v1/knowledge/99999")
    assert resp.status_code == 404


async def test_admin_token_protection(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "secreto123")
    denied = await client.post("/v1/knowledge", json={"description": "d", "content": "c"})
    assert denied.status_code == 403
    allowed = await client.post(
        "/v1/knowledge",
        json={"description": "entrada protegida ok", "content": "contenido suficiente"},
        headers={"X-Admin-Token": "secreto123"},
    )
    assert allowed.status_code == 201


async def test_backfill_requires_embedder(client):
    resp = await client.post("/v1/knowledge/backfill")
    assert resp.status_code == 400
    assert "backfill falló" in resp.json()["detail"]


# ------------------------------------------------------------------
# Auto-aprendizaje del motor (_save_knowledge_safe vía run completo)
# ------------------------------------------------------------------


@pytest.fixture
def atomic_flow(fake_upstream):
    """Flujo clásico: decompose(no-atómica) -> 2 hojas atómicas -> síntesis."""
    fake_upstream.queue_completion(
        content='{"atomic": false, "subtasks": ["sumar dos numeros dados", "explicar el resultado obtenido con detalle"]}'
    )
    fake_upstream.queue_stream(pieces=["la suma es cuatro y ademas sigue siendo cuatro mas larguito"])
    fake_upstream.queue_stream(pieces=["explicando la suma con detalle suficiente para memorizar bien"])
    fake_upstream.queue_stream(pieces=["respuesta final combinada de las tareas atomicas previas listas"])
    return fake_upstream


async def test_autolearn_saves_leaf_and_synthesis(client, atomic_flow):
    done = await client.post(
        "/v1/chat/completions",
        json={
            "model": settings.upstream_model,
            "messages": [{"role": "user", "content": "suma dos y dos y explica el resultado completo"}],
            "stream": False,
        },
    )
    assert done.status_code == 200

    rows = (await client.get("/v1/knowledge", params={"limit": 50})).json()["data"]
    categories = {r["category"] for r in rows}
    assert "atomic_task_result" in categories
    assert "synthesis_result" in categories


async def test_autolearn_disabled_by_config(client, monkeypatch, atomic_flow):
    monkeypatch.setattr(settings, "auto_learn_knowledge", False)
    done = await client.post(
        "/v1/chat/completions",
        json={
            "model": settings.upstream_model,
            "messages": [{"role": "user", "content": "ejecutar otro flujo igual con contenido diferente"}],
            "stream": False,
        },
    )
    assert done.status_code == 200
    rows = (await client.get("/v1/knowledge")).json()["data"]
    assert rows == []


async def test_autolearn_does_not_duplicate_exact_descriptions(client, fake_upstream):
    def queue_full_flow():
        fake_upstream.queue_completion(
            content='{"atomic": false, "subtasks": ["sumar dos numeros dados", "explicar el resultado obtenido con detalle"]}'
        )
        fake_upstream.queue_stream(pieces=["la suma es cuatro y ademas sigue siendo cuatro mas larguito"])
        fake_upstream.queue_stream(pieces=["explicando la suma con detalle suficiente para memorizar bien"])
        fake_upstream.queue_stream(pieces=["respuesta final combinada de las tareas atomicas previas listas"])

    # Cada turno nuevo re-decomprime desde cero: cada uno necesita su propio flujo.
    queue_full_flow()
    queue_full_flow()

    body = {
        "model": settings.upstream_model,
        "messages": [{"role": "user", "content": "flujo identico repetido para probar el dedupe"}],
        "stream": False,
    }
    first_done = await client.post("/v1/chat/completions", json=body)
    assert first_done.status_code == 200
    first_total = (await client.get("/v1/knowledge/stats")).json()["total"]
    assert first_total > 0

    done = await client.post("/v1/chat/completions", json=body)
    assert done.status_code == 200

    descriptions = [
        r["description"]
        for r in (await client.get("/v1/knowledge", params={"limit": 100})).json()["data"]
    ]
    assert len(descriptions) == len(set(descriptions)), "no deben existir descripciones duplicadas"
    second_total = (await client.get("/v1/knowledge/stats")).json()["total"]
    assert second_total == first_total, "el turno repetido no debe guardar nada nuevo"

