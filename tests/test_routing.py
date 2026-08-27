"""Tests de F1 — Routing multi-modelo por especialidad."""
import pytest

from app.config import settings
from app.engine import AtomicDecompositionEngine, GoalContext
from app.routing import detect_specialty, resolve_model, resolve_synthesis_model
from app.upstream import UpstreamClient


def _engine(**kwargs) -> AtomicDecompositionEngine:
    client = UpstreamClient()
    return AtomicDecompositionEngine(client, model="base-model", **kwargs)


# ---------------------------------------------------------------------------
# detect_specialty (unidad)
# ---------------------------------------------------------------------------

def test_detect_vision_when_images_and_image_task():
    assert detect_specialty("describe la imagen adjunta", has_images=True) == "vision"


def test_no_vision_without_images():
    # Sin imágenes en el turno, nunca se rutea a visión aunque haya keywords.
    assert detect_specialty("describe la imagen", has_images=False) != "vision"


def test_detect_code():
    assert detect_specialty("implementa una función en python", has_images=False) == "code"


def test_detect_fast_summary():
    assert detect_specialty("resume este texto en pocas palabras", has_images=False) == "fast"


def test_detect_default():
    assert detect_specialty("cuál es la capital de francia", has_images=False) == "default"


def test_code_priority_over_fast():
    # "resume este código" tiene señal de código y de resumen → gana código.
    assert detect_specialty("resume este código python", has_images=False) == "code"


def test_word_boundary_avoids_false_positive():
    # "api" no debe disparar dentro de "rapid"; "class" no dentro de "classroom".
    assert detect_specialty("un rapid classroom de historia", has_images=False) == "default"


# ---------------------------------------------------------------------------
# resolve_model / resolve_synthesis_model (unidad)
# ---------------------------------------------------------------------------

def test_resolve_model_disabled_returns_base(monkeypatch):
    monkeypatch.setattr(settings, "specialty_routing", False)
    monkeypatch.setattr(settings, "code_model", "code-model")
    assert resolve_model("code", "base-model") == "base-model"


def test_resolve_model_enabled_uses_specialty(monkeypatch):
    monkeypatch.setattr(settings, "specialty_routing", True)
    monkeypatch.setattr(settings, "code_model", "code-model")
    assert resolve_model("code", "base-model") == "code-model"


def test_resolve_model_enabled_empty_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "specialty_routing", True)
    monkeypatch.setattr(settings, "code_model", "")
    assert resolve_model("code", "base-model") == "base-model"


def test_resolve_synthesis_model_enabled(monkeypatch):
    monkeypatch.setattr(settings, "specialty_routing", True)
    monkeypatch.setattr(settings, "synthesis_model", "synth-model")
    assert resolve_synthesis_model("base-model") == "synth-model"


def test_resolve_synthesis_model_disabled(monkeypatch):
    monkeypatch.setattr(settings, "specialty_routing", False)
    monkeypatch.setattr(settings, "synthesis_model", "synth-model")
    assert resolve_synthesis_model("base-model") == "base-model"


# ---------------------------------------------------------------------------
# Integración con el motor
# ---------------------------------------------------------------------------

async def test_routing_disabled_uses_base_model_everywhere(fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "specialty_routing", False)
    fake_upstream.queue_completion(content='{"atomic": true, "subtasks": []}')
    fake_upstream.queue_stream(pieces=["ok"])
    fake_upstream.queue_stream(pieces=["final"])

    engine = _engine()
    engine.goal_ctx = GoalContext(caller_system="", turn_instruction="implementa una función", prior_context="")
    async for _ in engine.run():
        pass

    # Las 3 fases (descomposición, hoja, síntesis) usan el modelo base.
    assert all(r["model"] == "base-model" for r in fake_upstream.received)


async def test_routing_enabled_code_leaf_uses_code_model(fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "specialty_routing", True)
    monkeypatch.setattr(settings, "code_model", "code-model")

    # Root no-atómico con 1 subtarea de código (lista de strings). Con depth=1
    # el hijo se vuelve atómico sin llamar al upstream.
    fake_upstream.queue_completion(
        content='{"atomic": false, "subtasks": ["implementa una función en python"]}'
    )
    fake_upstream.queue_stream(pieces=["def f(): pass"])
    fake_upstream.queue_stream(pieces=["final"])

    engine = _engine()
    engine.goal_ctx = GoalContext(caller_system="", turn_instruction="escribe código", prior_context="")
    async for _ in engine.run():
        pass

    # received[0]=descomposición (base), received[1]=hoja de código (code-model),
    # received[2]=síntesis (base).
    assert fake_upstream.received[0]["model"] == "base-model"
    assert fake_upstream.received[1]["model"] == "code-model"
    assert fake_upstream.received[2]["model"] == "base-model"


async def test_routing_enabled_vision_leaf_uses_vision_model(fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "specialty_routing", True)
    monkeypatch.setattr(settings, "vision_model", "vision-model")

    image_part = {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}}
    fake_upstream.queue_completion(
        content='{"atomic": false, "subtasks": ["describe la imagen"]}'
    )
    fake_upstream.queue_stream(pieces=["un gato"])
    fake_upstream.queue_stream(pieces=["final"])

    engine = _engine()
    engine.goal_ctx = GoalContext(
        caller_system="", turn_instruction="describe la imagen", prior_context="",
        image_parts=[image_part],
    )
    async for _ in engine.run():
        pass

    assert fake_upstream.received[1]["model"] == "vision-model"


async def test_routing_enabled_synthesis_uses_synthesis_model(fake_upstream, monkeypatch):
    monkeypatch.setattr(settings, "specialty_routing", True)
    monkeypatch.setattr(settings, "synthesis_model", "synth-model")

    fake_upstream.queue_completion(content='{"atomic": true, "subtasks": []}')
    fake_upstream.queue_stream(pieces=["ok"])
    fake_upstream.queue_stream(pieces=["final"])

    engine = _engine()
    engine.goal_ctx = GoalContext(caller_system="", turn_instruction="haz algo", prior_context="")
    async for _ in engine.run():
        pass

    # received[2] es la síntesis → debe usar synthesis_model.
    assert fake_upstream.received[2]["model"] == "synth-model"
