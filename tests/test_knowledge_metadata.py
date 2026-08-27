"""Tests de F5 — Metadatos y grafo en la base de conocimiento."""
import pytest

from app import db
from app.config import settings
from app.engine import AtomicDecompositionEngine, GoalContext
from app.upstream import UpstreamClient


async def test_save_knowledge_stores_source_and_version():
    kid = await db.save_knowledge(
        "Receta de despliegue", "helm upgrade --install mi-app", "docs", source="admin"
    )
    rows = await db.list_knowledge(limit=10)
    entry = next(r for r in rows if r["id"] == kid)
    assert entry["source"] == "admin"
    assert entry["version"] == 1
    assert entry["updated_at"] is not None
    assert entry["parent_id"] is None


async def test_vector_updated_at_set_when_embedded():
    kid = await db.save_knowledge(
        "Entrada a vectorizar", "contenido de prueba para vectorizar", "general"
    )
    rows = await db.list_knowledge(limit=10)
    entry = next(r for r in rows if r["id"] == kid)
    assert entry["vector_updated_at"] is None

    await db.upsert_knowledge_vec(kid, 2, b"\x00" * 8)
    rows = await db.list_knowledge(limit=10)
    entry = next(r for r in rows if r["id"] == kid)
    assert entry["vector_updated_at"] is not None
    assert entry["has_vector"] == 1


async def test_parent_id_links_entries():
    parent = await db.save_knowledge("Tema principal", "contenido del tema principal", "docs")
    child = await db.save_knowledge(
        "Subtema derivado", "contenido del subtema relacionado", "docs", parent_id=parent
    )
    rows = await db.list_knowledge(limit=10)
    child_row = next(r for r in rows if r["id"] == child)
    assert child_row["parent_id"] == parent


async def test_stats_includes_by_source():
    await db.save_knowledge("Manual uno", "contenido manual uno", "docs", source="manual")
    await db.save_knowledge("Auto uno", "contenido auto uno", "code", source="auto_learn")
    await db.save_knowledge("Auto dos", "contenido auto dos", "code", source="auto_learn")
    stats = await db.knowledge_stats()
    assert stats["total"] == 3
    assert stats["by_source"]["manual"] == 1
    assert stats["by_source"]["auto_learn"] == 2


async def test_auto_learn_tags_source(fake_upstream):
    fake_upstream.queue_completion(content='{"atomic": true, "subtasks": []}')
    fake_upstream.queue_stream(pieces=["def sumar(a, b):\n    return a + b"])
    fake_upstream.queue_stream(pieces=["respuesta final"])

    engine = AtomicDecompositionEngine(UpstreamClient(), model="test-model")
    engine.goal_ctx = GoalContext(
        caller_system="", turn_instruction="Funcion sumar en Python", prior_context=""
    )
    async for _ in engine.run():
        pass

    rows = await db.list_knowledge(limit=50)
    auto = [r for r in rows if r["source"] == "auto_learn"]
    assert len(auto) >= 1


async def test_migration_adds_metadata_columns_to_legacy_db(tmp_path, monkeypatch):
    import aiosqlite as _aiosqlite

    legacy_path = str(tmp_path / "legacy.db")
    conn = await _aiosqlite.connect(legacy_path)
    # Schema antiguo: knowledge_base SIN las columnas de metadatos de F5.
    await conn.execute(
        "CREATE TABLE knowledge_base ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "description TEXT NOT NULL, "
        "category TEXT NOT NULL DEFAULT 'general', "
        "content TEXT NOT NULL, "
        "created_at REAL NOT NULL)"
    )
    await conn.execute(
        "INSERT INTO knowledge_base (description, category, content, created_at) "
        "VALUES ('entrada legada', 'general', 'contenido legado', 1.0)"
    )
    await conn.commit()
    await conn.close()

    monkeypatch.setattr(settings, "database_path", legacy_path)
    # Cualquier operación dispara _connect → migración idempotente.
    rows = await db.list_knowledge(limit=10)
    assert len(rows) == 1
    assert rows[0]["description"] == "entrada legada"
    # La migración rellena los metadatos con sus defaults.
    assert rows[0]["source"] == "manual"
    assert rows[0]["version"] == 1
    assert rows[0]["parent_id"] is None
    assert rows[0]["vector_updated_at"] is None
