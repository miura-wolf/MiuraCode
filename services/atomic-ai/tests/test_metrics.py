from __future__ import annotations

from app.metrics import Metrics, metrics


# ------------------------------------------------------------------
# Acumulador en memoria (unidad)
# ------------------------------------------------------------------


def test_metrics_inc_and_snapshot():
    m = Metrics()
    m.inc("leaves_executed")
    m.inc("leaves_executed", 2)
    m.inc("tool_calls", 3)
    snap = m.snapshot()
    assert snap["counters"]["leaves_executed"] == 3
    assert snap["counters"]["tool_calls"] == 3
    assert snap["latency"] == {}


def test_metrics_observe_latency_stats():
    m = Metrics()
    m.observe("leaf_execution", 1.0)
    m.observe("leaf_execution", 3.0)
    lat = m.snapshot()["latency"]["leaf_execution"]
    assert lat["count"] == 2
    assert lat["total_s"] == 4.0
    assert lat["avg_s"] == 2.0
    assert lat["max_s"] == 3.0


def test_metrics_reset_clears_state():
    m = Metrics()
    m.inc("a")
    m.observe("b", 0.5)
    m.reset()
    snap = m.snapshot()
    assert snap["counters"] == {}
    assert snap["latency"] == {}


def test_metrics_snapshot_is_a_copy():
    m = Metrics()
    m.inc("a")
    snap = m.snapshot()
    snap["counters"]["a"] = 999
    assert m.snapshot()["counters"]["a"] == 1


# ------------------------------------------------------------------
# Endpoint /v1/stats (integración con el pipeline completo)
# ------------------------------------------------------------------


async def test_stats_endpoint_reflects_pipeline_metrics(client, fake_upstream):
    # Un turno atómico sin subtareas: descomposición + 1 hoja + síntesis.
    fake_upstream.queue_completion(content='{"atomic": true, "subtasks": []}')
    fake_upstream.queue_stream(pieces=["resultado de la hoja"])
    fake_upstream.queue_stream(pieces=["respuesta final"])

    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "test-model", "messages": [{"role": "user", "content": "haz algo"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "respuesta final"

    stats = await client.get("/v1/stats")
    assert stats.status_code == 200
    body = stats.json()

    counters = body["counters"]
    # Una hoja descompuesta y ejecutada, por la vía secuencial (PARALLEL_LEAVES off).
    assert counters["leaves_decomposed"] == 1
    assert counters["leaves_executed"] == 1
    assert counters["sequential_executions"] == 1
    assert counters.get("parallel_executions", 0) == 0
    # La hoja consultó la base de conocimiento (RAG) al menos una vez.
    assert counters["rag_queries"] >= 1

    latency = body["latency"]
    # Las tres fases midieron latencia.
    assert latency["decomposition"]["count"] == 1
    assert latency["leaf_execution"]["count"] == 1
    assert latency["synthesis"]["count"] == 1

    # El snapshot incluye también el estado de la base de conocimiento.
    assert "knowledge" in body
    assert "total" in body["knowledge"]


async def test_stats_endpoint_requires_admin_token(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "secret-token")

    # Sin header → 403.
    denied = await client.get("/v1/stats")
    assert denied.status_code == 403

    # Con header correcto → 200.
    ok = await client.get("/v1/stats", headers={"X-Admin-Token": "secret-token"})
    assert ok.status_code == 200
    assert "counters" in ok.json()
