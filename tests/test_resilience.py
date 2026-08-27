"""Tests de F2 — Fallback + retry resiliente."""
import pytest

from app.config import settings
from app.engine import AtomicDecompositionEngine, GoalContext
from app.upstream import UpstreamClient, UpstreamError


def _engine(**kwargs) -> AtomicDecompositionEngine:
    client = UpstreamClient()
    return AtomicDecompositionEngine(client, model="base-model", **kwargs)


# ---------------------------------------------------------------------------
# Retry de transporte en el cliente (complete)
# ---------------------------------------------------------------------------

async def test_complete_retries_on_500_then_succeeds(fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "upstream_max_retries", 2)
    fake_upstream.queue_error(500)
    fake_upstream.queue_completion(content="ok")

    client = UpstreamClient()
    result = await client.complete([{"role": "user", "content": "hola"}], model="m")
    assert result == "ok"
    assert len(fake_upstream.received) == 2  # 1 fallo + 1 éxito


async def test_complete_raises_after_exhausting_retries(fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "upstream_max_retries", 2)
    fake_upstream.queue_error(500)
    fake_upstream.queue_error(500)
    fake_upstream.queue_error(500)

    client = UpstreamClient()
    with pytest.raises(UpstreamError):
        await client.complete([{"role": "user", "content": "hola"}], model="m")
    assert len(fake_upstream.received) == 3  # intento inicial + 2 reintentos


async def test_complete_no_retry_on_client_error_400(fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "upstream_max_retries", 2)
    fake_upstream.queue_error(400)

    client = UpstreamClient()
    with pytest.raises(UpstreamError):
        await client.complete([{"role": "user", "content": "hola"}], model="m")
    assert len(fake_upstream.received) == 1  # un 4xx no transitorio no se reintenta


async def test_fallback_model_used_on_retry(fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "upstream_max_retries", 2)
    monkeypatch.setattr(settings, "fallback_model", "fallback-model")
    fake_upstream.queue_error(500)
    fake_upstream.queue_completion(content="ok")

    client = UpstreamClient()
    await client.complete([{"role": "user", "content": "hola"}], model="primary-model")
    assert fake_upstream.received[0]["model"] == "primary-model"
    assert fake_upstream.received[1]["model"] == "fallback-model"


# ---------------------------------------------------------------------------
# Retry de transporte en el cliente (stream)
# ---------------------------------------------------------------------------

async def test_stream_retries_on_500_then_succeeds(fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "upstream_max_retries", 2)
    fake_upstream.queue_error(500)
    fake_upstream.queue_stream(pieces=["hola"])

    client = UpstreamClient()
    pieces = [p async for p in client.stream([{"role": "user", "content": "x"}], model="m")]
    assert "".join(pieces) == "hola"
    assert len(fake_upstream.received) == 2


# ---------------------------------------------------------------------------
# Reintento de descomposición ante JSON roto
# ---------------------------------------------------------------------------

async def test_decomposition_json_repair_retry_succeeds(fake_upstream, monkeypatch):
    # 1ª descomposición devuelve prosa (JSON roto) → reintento reforzado → JSON válido.
    fake_upstream.queue_completion(content="perdón, no sé responder en JSON")
    fake_upstream.queue_completion(content='{"atomic": true, "subtasks": []}')
    fake_upstream.queue_stream(pieces=["resultado"])
    fake_upstream.queue_stream(pieces=["final"])

    engine = _engine()
    engine.goal_ctx = GoalContext(caller_system="", turn_instruction="haz algo", prior_context="")
    events = [e async for e in engine.run()]

    # Dos llamadas de descomposición (la original + el reintento reforzado):
    # son las únicas que llevan response_format (json_mode).
    decomposition_calls = [r for r in fake_upstream.received if r.get("response_format")]
    assert len(decomposition_calls) == 2
    content_text = "".join(p for k, p in events if k == "content")
    assert content_text == "final"


async def test_decomposition_persistent_broken_json_falls_back_to_atomic(fake_upstream, monkeypatch):
    # Ambas descomposiciones devuelven prosa → fallback a tarea atómica plana.
    fake_upstream.queue_completion(content="no soy json")
    fake_upstream.queue_completion(content="sigo sin ser json")
    fake_upstream.queue_stream(pieces=["resultado atomico"])
    fake_upstream.queue_stream(pieces=["final"])

    engine = _engine()
    engine.goal_ctx = GoalContext(caller_system="", turn_instruction="haz algo", prior_context="")
    events = [e async for e in engine.run()]

    content_text = "".join(p for k, p in events if k == "content")
    assert content_text == "final"
    # El motor trató la tarea como atómica tras agotar el reintento.
    assert engine.root.is_atomic is True
