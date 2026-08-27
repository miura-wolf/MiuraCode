"""Tests de F3 — Ejecución paralela de hojas atómicas independientes."""
import pytest

from app.config import settings
from app.engine import AtomicDecompositionEngine, GoalContext
from app.upstream import UpstreamClient


def _engine(**kwargs) -> AtomicDecompositionEngine:
    client = UpstreamClient()
    return AtomicDecompositionEngine(client, model="base-model", **kwargs)


async def test_parallel_disabled_by_default_runs_sequential(fake_upstream):
    # Sin activar parallel_leaves, dos hojas se ejecutan secuencialmente.
    fake_upstream.queue_completion(content='{"atomic": false, "subtasks": ["tarea uno", "tarea dos"]}')
    fake_upstream.queue_stream(pieces=["resultado uno"])
    fake_upstream.queue_stream(pieces=["resultado dos"])
    fake_upstream.queue_stream(pieces=["final"])

    engine = _engine()
    engine.goal_ctx = GoalContext(caller_system="", turn_instruction="haz dos cosas", prior_context="")
    events = [e async for e in engine.run()]

    reasoning_text = "".join(p for k, p in events if k == "reasoning")
    assert "en paralelo" not in reasoning_text
    assert len(engine.results) == 2
    content_text = "".join(p for k, p in events if k == "content")
    assert content_text == "final"


async def test_parallel_executes_multiple_leaves(fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "parallel_leaves", True)
    fake_upstream.queue_completion(content='{"atomic": false, "subtasks": ["tarea uno", "tarea dos"]}')
    fake_upstream.queue_stream(pieces=["resultado uno"])
    fake_upstream.queue_stream(pieces=["resultado dos"])
    fake_upstream.queue_stream(pieces=["final"])

    engine = _engine()
    engine.goal_ctx = GoalContext(caller_system="", turn_instruction="haz dos cosas", prior_context="")
    events = [e async for e in engine.run()]

    # Ambas hojas se ejecutaron; sus resultados están presentes (orden no
    # determinista por la concurrencia, por eso comparamos como conjunto).
    leaf_results = {leaf.result for leaf in engine.leaves}
    assert leaf_results == {"resultado uno", "resultado dos"}
    assert len(engine.results) == 2

    # 1 descomposición + 2 hojas + 1 síntesis.
    assert len(fake_upstream.received) == 4
    # La síntesis (última request) ve ambos resultados como contexto.
    synthesis_user = fake_upstream.received[3]["messages"][1]["content"]
    assert "resultado uno" in synthesis_user and "resultado dos" in synthesis_user

    content_text = "".join(p for k, p in events if k == "content")
    assert content_text == "final"


async def test_parallel_emits_progress_reasoning(fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "parallel_leaves", True)
    fake_upstream.queue_completion(content='{"atomic": false, "subtasks": ["a", "b"]}')
    fake_upstream.queue_stream(pieces=["ra"])
    fake_upstream.queue_stream(pieces=["rb"])
    fake_upstream.queue_stream(pieces=["final"])

    engine = _engine()
    engine.goal_ctx = GoalContext(caller_system="", turn_instruction="haz dos", prior_context="")
    events = [e async for e in engine.run()]

    reasoning_text = "".join(p for k, p in events if k == "reasoning")
    assert "en paralelo" in reasoning_text


async def test_parallel_falls_back_to_sequential_with_tools(fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "parallel_leaves", True)
    fake_upstream.queue_completion(content='{"atomic": false, "subtasks": ["tarea uno", "tarea dos"]}')
    fake_upstream.queue_stream(pieces=["resultado uno"])
    fake_upstream.queue_stream(pieces=["resultado dos"])
    fake_upstream.queue_stream(pieces=["final"])

    # Con tools activas debe volver al modo secuencial (sin "en paralelo").
    engine = _engine(tools=[{"type": "function", "function": {"name": "leer"}}])
    engine.goal_ctx = GoalContext(caller_system="", turn_instruction="haz dos cosas", prior_context="")
    events = [e async for e in engine.run()]

    reasoning_text = "".join(p for k, p in events if k == "reasoning")
    assert "en paralelo" not in reasoning_text
    assert len(engine.results) == 2


async def test_parallel_single_leaf_stays_sequential(fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "parallel_leaves", True)
    fake_upstream.queue_completion(content='{"atomic": true, "subtasks": []}')
    fake_upstream.queue_stream(pieces=["resultado"])
    fake_upstream.queue_stream(pieces=["final"])

    engine = _engine()
    engine.goal_ctx = GoalContext(caller_system="", turn_instruction="haz algo", prior_context="")
    events = [e async for e in engine.run()]

    reasoning_text = "".join(p for k, p in events if k == "reasoning")
    assert "en paralelo" not in reasoning_text
    content_text = "".join(p for k, p in events if k == "content")
    assert content_text == "final"
