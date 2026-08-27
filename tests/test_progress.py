"""Tests de F4 — Streaming con progreso del árbol."""
import json

import pytest

from app import sse
from app.config import settings
from app.engine import AtomicDecompositionEngine, GoalContext
from app.upstream import UpstreamClient


def _engine(**kwargs) -> AtomicDecompositionEngine:
    client = UpstreamClient()
    return AtomicDecompositionEngine(client, model="base-model", **kwargs)


def _progress_events(events):
    return [p for k, p in events if k == "progress"]


# ---------------------------------------------------------------------------
# Nivel motor: el engine emite eventos de progreso
# ---------------------------------------------------------------------------

async def test_engine_emits_progress_lifecycle(fake_upstream):
    fake_upstream.queue_completion(content='{"atomic": false, "subtasks": ["tarea uno"]}')
    fake_upstream.queue_stream(pieces=["resultado"])
    fake_upstream.queue_stream(pieces=["final"])

    engine = _engine()
    engine.goal_ctx = GoalContext(caller_system="", turn_instruction="haz algo", prior_context="")
    events = [e async for e in engine.run()]

    progress = _progress_events(events)
    types = [p["type"] for p in progress]
    assert "phase_started" in types
    assert "phase_done" in types
    assert "leaf_started" in types
    assert "leaf_done" in types
    assert "done" in types
    # La síntesis anuncia su fase.
    assert any(p["type"] == "phase_started" and p["phase"] == "synthesis" for p in progress)
    # La descomposición informa cuántas hojas produjo.
    decomp_done = next(p for p in progress if p["type"] == "phase_done" and p["phase"] == "decomposition")
    assert decomp_done["leaf_count"] == 1


async def test_progress_leaf_started_carries_model(fake_upstream):
    fake_upstream.queue_completion(content='{"atomic": true, "subtasks": []}')
    fake_upstream.queue_stream(pieces=["ok"])
    fake_upstream.queue_stream(pieces=["final"])

    engine = _engine()
    engine.goal_ctx = GoalContext(caller_system="", turn_instruction="haz algo", prior_context="")
    events = [e async for e in engine.run()]

    leaf_started = [p for p in _progress_events(events) if p["type"] == "leaf_started"]
    assert len(leaf_started) == 1
    assert leaf_started[0]["model"] == "base-model"


async def test_progress_parallel_emits_leaf_done_per_leaf(fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "parallel_leaves", True)
    fake_upstream.queue_completion(content='{"atomic": false, "subtasks": ["a", "b"]}')
    fake_upstream.queue_stream(pieces=["ra"])
    fake_upstream.queue_stream(pieces=["rb"])
    fake_upstream.queue_stream(pieces=["final"])

    engine = _engine()
    engine.goal_ctx = GoalContext(caller_system="", turn_instruction="haz dos", prior_context="")
    events = [e async for e in engine.run()]

    progress = _progress_events(events)
    leaf_done = [p for p in progress if p["type"] == "leaf_done"]
    assert len(leaf_done) == 2
    # El evento de fase de ejecución refleja que fue en paralelo.
    exec_started = next(p for p in progress if p["type"] == "phase_started" and p["phase"] == "execution")
    assert exec_started["parallel"] is True


# ---------------------------------------------------------------------------
# Nivel SSE: el builder produce un chunk válido con campo progress
# ---------------------------------------------------------------------------

def test_progress_chunk_is_valid_sse_with_progress_field():
    line = sse.progress_chunk("m", {"type": "leaf_done", "index": 0, "total": 1}, "chatcmpl-x")
    assert line.startswith("data: ")
    assert line.endswith("\n\n")
    obj = json.loads(line[len("data:"):].strip())
    assert obj["object"] == "chat.completion.chunk"
    assert obj["progress"] == {"type": "leaf_done", "index": 0, "total": 1}
    assert obj["choices"] == []


# ---------------------------------------------------------------------------
# Nivel HTTP: el stream incluye/omite progreso según el flag
# ---------------------------------------------------------------------------

def _parse_progress_from_sse(text: str) -> list[dict]:
    progress = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            continue
        obj = json.loads(data)
        if "progress" in obj:
            progress.append(obj["progress"])
    return progress


async def test_http_sse_includes_progress_when_enabled(client, fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "emit_progress_events", True)
    fake_upstream.queue_completion(content='{"atomic": true, "subtasks": []}')
    fake_upstream.queue_stream(pieces=["resultado"])
    fake_upstream.queue_stream(pieces=["final"])

    payload = {"messages": [{"role": "user", "content": "hola"}], "stream": True}
    resp = await client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200

    progress = _parse_progress_from_sse(resp.text)
    types = [p["type"] for p in progress]
    assert "phase_started" in types
    assert "leaf_started" in types
    assert "leaf_done" in types
    assert "done" in types


async def test_http_sse_omits_progress_when_disabled(client, fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "emit_progress_events", False)
    fake_upstream.queue_completion(content='{"atomic": true, "subtasks": []}')
    fake_upstream.queue_stream(pieces=["resultado"])
    fake_upstream.queue_stream(pieces=["final"])

    payload = {"messages": [{"role": "user", "content": "hola"}], "stream": True}
    resp = await client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    assert _parse_progress_from_sse(resp.text) == []
