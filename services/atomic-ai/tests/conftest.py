from __future__ import annotations

import json
import uuid
from typing import Any, Optional

import httpx
import pytest
import respx

from app.config import settings


class FakeUpstream:
    """Cola de respuestas programadas para simular el upstream OpenAI-compatible.

    Cada test empuja una secuencia de respuestas con queue_completion()/queue_stream();
    el fake las devuelve en orden, una por cada request entrante, y guarda en
    `received` el payload JSON completo de cada request para poder inspeccionar
    qué se le mandó realmente al upstream (system prompt compuesto, mensajes
    acumulados en un resume, tool_choice normalizado, etc.).
    """

    def __init__(self) -> None:
        self.queue: list[dict[str, Any]] = []
        self.received: list[dict[str, Any]] = []

    def queue_completion(
        self, content: str = "", tool_calls: Optional[list[dict[str, Any]]] = None
    ) -> None:
        """Programa una respuesta no-streaming (la usa la fase de decomposición)."""
        self.queue.append({"kind": "completion", "content": content, "tool_calls": tool_calls})

    def queue_stream(
        self,
        pieces: Optional[list[str]] = None,
        tool_calls: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """Programa una respuesta streaming (ejecución atómica / síntesis).

        pieces: fragmentos de texto emitidos como deltas de content.
        tool_calls: si se da, lista de {"id","function":{"name","arguments"}} —
        se emiten como deltas de tool_calls troceados por índice, y el stream
        termina con finish_reason="tool_calls" en vez de "stop".
        """
        self.queue.append({"kind": "stream", "pieces": pieces or [], "tool_calls": tool_calls})

    def queue_error(self, status_code: int = 500) -> None:
        """Programa una respuesta de error HTTP (para tests de retry/fallback F2)."""
        self.queue.append({"kind": "error", "status_code": status_code})

    def _pop(self) -> dict[str, Any]:
        if not self.queue:
            raise AssertionError("FakeUpstream: no hay más respuestas programadas para esta request")
        return self.queue.pop(0)

    def handler(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.received.append(payload)
        programmed = self._pop()

        if programmed.get("kind") == "error":
            return httpx.Response(programmed["status_code"], text="upstream error")

        if payload.get("stream"):
            body = self._build_sse_body(programmed)
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=body
            )

        message: dict[str, Any] = {"role": "assistant", "content": programmed.get("content") or None}
        if programmed.get("tool_calls"):
            message["tool_calls"] = programmed["tool_calls"]
        return httpx.Response(
            200,
            json={
                "id": f"chatcmpl-{uuid.uuid4().hex}",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            },
        )

    def _build_sse_body(self, programmed: dict[str, Any]) -> bytes:
        lines: list[str] = []
        for piece in programmed.get("pieces", []):
            chunk = {"choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
            lines.append(f"data: {json.dumps(chunk)}\n\n")

        tool_calls = programmed.get("tool_calls")
        if tool_calls:
            for i, tc in enumerate(tool_calls):
                delta_tc = {
                    "index": i,
                    "id": tc.get("id"),
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                }
                chunk = {
                    "choices": [
                        {"index": 0, "delta": {"tool_calls": [delta_tc]}, "finish_reason": None}
                    ]
                }
                lines.append(f"data: {json.dumps(chunk)}\n\n")
            finish_reason = "tool_calls"
        else:
            finish_reason = "stop"

        final_chunk = {"choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]}
        lines.append(f"data: {json.dumps(final_chunk)}\n\n")
        lines.append("data: [DONE]\n\n")
        return "".join(lines).encode("utf-8")


@pytest.fixture(autouse=True)
def _fake_upstream_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla los tests del contenido real de .env: apunta el upstream a un host
    ficticio que solo respx conoce, sin importar qué backend tenga configurado
    el desarrollador localmente."""
    monkeypatch.setattr(settings, "upstream_base_url", "http://fake-upstream.test")


@pytest.fixture
def fake_upstream():
    upstream = FakeUpstream()
    with respx.mock(base_url="http://fake-upstream.test", assert_all_called=False) as router:
        router.post("/v1/chat/completions").mock(side_effect=upstream.handler)
        yield upstream


@pytest.fixture(autouse=True)
def _temp_database(tmp_path, monkeypatch):
    """Aísla cada test con su propia base de datos SQLite temporal."""
    db_path = str(tmp_path / "test_atomic_ai.db")
    monkeypatch.setattr(settings, "database_path", db_path)
    yield


@pytest.fixture(autouse=True)
def _isolate_rag_settings(monkeypatch):
    """Neutraliza lo que venga del .env real del desarrollador: sin embedder
    (la búsqueda será solo FTS salvo que un test active/monkee lo contrario)
    y admin sin token. Los tests específicos re-fijan estos valores."""
    # F6: las métricas son un singleton de módulo; se resetean entre tests para
    # que los contadores/latencias de un test no contaminen a otro.
    from app.metrics import metrics as _metrics

    _metrics.reset()
    monkeypatch.setattr(settings, "embeddings_base_url", "")
    monkeypatch.setattr(settings, "embeddings_model", "fake-embedder")
    monkeypatch.setattr(settings, "hybrid_search", True)
    monkeypatch.setattr(settings, "auto_learn_knowledge", True)
    monkeypatch.setattr(settings, "admin_token", "")
    # F1: neutralizar el routing por especialidad que pueda venir del .env real;
    # los tests que lo necesiten lo re-activan explícitamente.
    monkeypatch.setattr(settings, "specialty_routing", False)
    monkeypatch.setattr(settings, "vision_model", "")
    monkeypatch.setattr(settings, "code_model", "")
    monkeypatch.setattr(settings, "fast_model", "")
    monkeypatch.setattr(settings, "synthesis_model", "")
    # F2: reintentos sin espera para no ralentizar el suite y sin modelo de
    # respaldo salvo que un test lo active explícitamente.
    monkeypatch.setattr(settings, "upstream_max_retries", 2)
    monkeypatch.setattr(settings, "upstream_retry_backoff_seconds", 0.0)
    monkeypatch.setattr(settings, "fallback_model", "")
    # F3: ejecución paralela de hojas desactivada por defecto; los tests que la
    # necesiten la activan explícitamente.
    monkeypatch.setattr(settings, "parallel_leaves", False)
    # F4: eventos de progreso del árbol desactivados por defecto para no alterar
    # el SSE de los tests existentes; los tests de F4 los activan.
    monkeypatch.setattr(settings, "emit_progress_events", False)
    # F7: investigación web desactivada por defecto para que ningún test llame a
    # un servicio real por culpa del .env del desarrollador; los tests de F7 la
    # activan explícitamente apuntando a un host ficticio que solo respx conoce.
    monkeypatch.setattr(settings, "web_research_base_url", "")
    monkeypatch.setattr(settings, "web_research_enabled", True)
    monkeypatch.setattr(settings, "web_research_auto_learn", True)
    # F8: sin carriles passthrough por defecto (los tests que los necesitan los
    # activan explícitamente), ni limitador RPM (0 = desactivado, ninguna
    # llamada espera).
    monkeypatch.setattr(settings, "passthrough_models", "")
    monkeypatch.setattr(settings, "upstream_rpm", 0)
    yield


@pytest.fixture(autouse=True)
def _deterministic_decomposition_depth(monkeypatch):
    """Fija la profundidad de descomposición en 1 para que el test suite sea
    determinista e independiente del valor de MAX_DECOMPOSITION_DEPTH que el
    desarrollador tenga en su .env (archivo gitignored y variable por máquina).

    Los flujos de prueba del repo hacen una única descomposición (no-atómica
    → N hojas atómicas → síntesis), que equivale a profundidad 1; con un depth
    mayor el motor volvería a descomponer cada hoja recursivamente y el fake
    upstream agotaría su cola de respuestas programadas."""
    monkeypatch.setattr(settings, "max_decomposition_depth", 1)
    yield


@pytest.fixture(autouse=True)
def _reset_session_store():
    from app.main import session_store

    session_store._sessions.clear()
    yield
    session_store._sessions.clear()


@pytest.fixture(autouse=True)
def _reset_upstream_rate_limiter():
    """El limitador RPM del upstream es una instancia por proceso A PROPÓSITO
    (un proceso del proxy = un presupuesto contra el upstream), así que la
    contaminación entre tests es la única fuga que este fixture cierra: sin
    él, un test que activara upstream_rpm=2 dejaría al siguiente esperando
    tras timestamps viejos."""
    from app.rate_limit import reset_rate_limiter

    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture
async def client():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
