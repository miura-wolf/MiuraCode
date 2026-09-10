from __future__ import annotations

"""Tests F7 — investigación web (Gigaxity Deep Research) como fallback del RAG.

Cubren el cliente ``app/web_research.py`` y su integración en
``engine._fetch_knowledge``: activación por config, degradación silenciosa ante
cualquier fallo, auto-aprendizaje del resultado y formato del bloque de contexto.
Se aísla el servicio externo con respx apuntando a un host ficticio, igual que
el fake del upstream OpenAI-compatible.
"""

import httpx
import pytest
import respx

from app import db
from app.config import settings
from app.engine import AtomicDecompositionEngine
from app.metrics import metrics
from app.upstream import UpstreamClient
from app.web_research import WebResearchClient

RESEARCH_URL = "http://fake-research.test"


@pytest.fixture
def fake_research(monkeypatch):
    """Activa la F7 apuntando a un host ficticio que solo respx conoce."""
    monkeypatch.setattr(settings, "web_research_base_url", RESEARCH_URL)
    monkeypatch.setattr(settings, "web_research_enabled", True)
    monkeypatch.setattr(settings, "web_research_auto_learn", True)
    with respx.mock(base_url=RESEARCH_URL, assert_all_called=False) as router:
        yield router


def _engine() -> AtomicDecompositionEngine:
    return AtomicDecompositionEngine(client=UpstreamClient(), model="test-model")


def _gigaxity_response(content: str = "Síntesis sobre X [1].", citations=None) -> dict:
    return {
        "content": content,
        "citations": citations
        if citations is not None
        else [{"number": 1, "title": "Fuente Demo", "url": "https://example.com/x"}],
        "sources": [{"url": "https://example.com/x", "title": "Fuente Demo"}],
        "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    }


# ------------------------------------------------------------------
# Activación / desactivación por config
# ------------------------------------------------------------------


async def test_disabled_when_no_base_url():
    """Sin WEB_RESEARCH_BASE_URL (default del conftest) no se hace ninguna
    llamada y el miss se resuelve como antes de la F7."""
    engine = _engine()
    result = await engine._fetch_knowledge("consulta sin respuesta local qwerty")
    assert result == "(no hay soluciones previas relevantes)"
    assert metrics.get("rag_misses") == 1
    assert metrics.get("web_research_queries") == 0


async def test_local_hit_skips_web(fake_research):
    """Si la KB local responde, la investigación web ni se plantea."""
    route = fake_research.post("/api/v1/research").respond(200, json=_gigaxity_response())
    await db.save_knowledge(
        "quantumfluxwidget setup guide", "instalar con pip y configurar yaml", "ops"
    )
    engine = _engine()
    result = await engine._fetch_knowledge("quantumfluxwidget")
    assert "quantumfluxwidget setup guide" in result
    assert "Investigación web" not in result
    assert not route.called
    assert metrics.get("rag_hits") == 1
    assert metrics.get("web_research_queries") == 0


# ------------------------------------------------------------------
# Fallback sobre miss local
# ------------------------------------------------------------------


async def test_web_research_on_local_miss(fake_research):
    """Miss local + servicio sano → bloque de contexto con síntesis y fuentes."""
    route = fake_research.post("/api/v1/research").respond(200, json=_gigaxity_response())
    engine = _engine()
    result = await engine._fetch_knowledge("como funciona un transformador cuantico")
    assert "Investigación web" in result
    assert "Síntesis sobre X" in result
    assert "Fuente Demo" in result
    assert "https://example.com/x" in result
    assert route.called
    assert metrics.get("rag_misses") == 1
    assert metrics.get("web_research_queries") == 1
    assert metrics.get("web_research_hits") == 1


async def test_request_payload_carries_settings(fake_research, monkeypatch):
    """El body enviado refleja top_k/preset/reasoning_effort de settings."""
    import json as _json

    monkeypatch.setattr(settings, "web_research_top_k", 5)
    monkeypatch.setattr(settings, "web_research_preset", "fast")
    monkeypatch.setattr(settings, "web_research_reasoning_effort", "low")
    route = fake_research.post("/api/v1/research").respond(200, json=_gigaxity_response())
    engine = _engine()
    await engine._fetch_knowledge("payload de prueba para el servicio")
    body = _json.loads(route.calls.last.request.content)
    assert body["query"] == "payload de prueba para el servicio"
    assert body["top_k"] == 5
    assert body["preset"] == "fast"
    assert body["reasoning_effort"] == "low"


# ------------------------------------------------------------------
# Degradación silenciosa ante fallos
# ------------------------------------------------------------------


async def test_service_down_degrades(fake_research):
    fake_research.post("/api/v1/research").respond(500, text="boom")
    engine = _engine()
    result = await engine._fetch_knowledge("consulta que el servicio no puede resolver")
    assert result == "(no hay soluciones previas relevantes)"
    assert metrics.get("web_research_errors") == 1
    assert metrics.get("web_research_hits") == 0


async def test_connection_error_degrades(fake_research):
    fake_research.post("/api/v1/research").mock(side_effect=httpx.ConnectError("refused"))
    engine = _engine()
    result = await engine._fetch_knowledge("otra consulta sin servicio disponible")
    assert result == "(no hay soluciones previas relevantes)"
    assert metrics.get("web_research_errors") == 1


async def test_empty_content_degrades(fake_research):
    fake_research.post("/api/v1/research").respond(200, json={"content": "   ", "citations": []})
    engine = _engine()
    result = await engine._fetch_knowledge("consulta cuya sintesis llega vacia")
    assert result == "(no hay soluciones previas relevantes)"
    assert metrics.get("web_research_misses") == 1


# ------------------------------------------------------------------
# Auto-aprendizaje del resultado web
# ------------------------------------------------------------------


async def test_auto_learn_persists_web_research(fake_research):
    fake_research.post("/api/v1/research").respond(200, json=_gigaxity_response())
    engine = _engine()
    await engine._fetch_knowledge("tema nuevo que se autoaprende de la web")
    stats = await db.knowledge_stats()
    assert stats["by_source"].get("web_research") == 1
    entries = await db.list_knowledge(limit=10)
    web_entries = [e for e in entries if e["source"] == "web_research"]
    assert len(web_entries) == 1
    assert web_entries[0]["category"] == "web_research"


async def test_auto_learn_disabled_does_not_persist(fake_research, monkeypatch):
    monkeypatch.setattr(settings, "web_research_auto_learn", False)
    fake_research.post("/api/v1/research").respond(200, json=_gigaxity_response())
    engine = _engine()
    result = await engine._fetch_knowledge("tema que no debe persistir en la kb")
    assert "Investigación web" in result
    stats = await db.knowledge_stats()
    assert stats["by_source"].get("web_research", 0) == 0


# ------------------------------------------------------------------
# Formato del bloque de contexto
# ------------------------------------------------------------------


def test_format_for_context_with_citations():
    data = _gigaxity_response(
        content="Respuesta con citas [1] y [2].",
        citations=[
            {"number": 1, "title": "Primera", "url": "https://a.example"},
            {"number": 2, "title": "", "url": "https://b.example"},
        ],
    )
    block = WebResearchClient.format_for_context(data)
    assert "Respuesta con citas" in block
    assert "[1] Primera — https://a.example" in block
    assert "[2] https://b.example" in block


def test_format_for_context_without_citations():
    block = WebResearchClient.format_for_context({"content": "Solo texto.", "citations": []})
    assert "Solo texto." in block
    assert "Fuentes:" not in block


def test_format_for_context_falls_back_to_sources():
    """Sin citas estructuradas (el modelo citó con 【N】 y Gigaxity no las parseó)
    pero con fuentes crudas, se lista ``sources`` para no perder trazabilidad."""
    data = {
        "content": "Síntesis que cita con marcadores 【1】 y 【2】.",
        "citations": [],
        "sources": [
            {"title": "Primera fuente", "url": "https://a.example"},
            {"title": "", "url": "https://b.example"},
        ],
    }
    block = WebResearchClient.format_for_context(data)
    assert "Síntesis que cita con marcadores" in block
    assert "Fuentes:" in block
    assert "- Primera fuente — https://a.example" in block
    assert "- https://b.example" in block


def test_format_for_context_strips_verification_wrapper():
    """El aviso 'verification FAILED' de Gigaxity (falso negativo) se descarta y
    solo se inyecta la síntesis real que hay bajo el marcador."""
    wrapped = (
        "# Synthesis verification FAILED\n\n"
        "This output is not a reliable synthesis:\n"
        "- synthesis cites none of the 12 provided sources\n\n"
        "---\n"
        "(unverified output below, for debugging)\n\n"
        "La síntesis útil va aquí 【1】."
    )
    data = {"content": wrapped, "citations": [], "sources": [{"title": "F", "url": "https://f.example"}]}
    block = WebResearchClient.format_for_context(data)
    assert "La síntesis útil va aquí" in block
    assert "verification FAILED" not in block
    assert "not a reliable synthesis" not in block
