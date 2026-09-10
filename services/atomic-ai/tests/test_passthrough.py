"""F8 — Carril passthrough: modelos que se reenvían al upstream TAL CUAL.

Contrato que fijan estos tests:
- PASSTHROUGH_MODELS vacío (default) → ningún carril, el proxy se comporta
  exactamente como antes (un modelo cualquiera no cambia de carril).
- El payload relayado preserva mensajes/tools/temperature/max_tokens SIN
  aplanar ni reescribir — una sola llamada HTTP, sin descomposición/RAG.
- No-stream: se devuelve la respuesta COMPLETA del upstream (id/usage...).
- Stream: los BYTES SSE del upstream se relayan verbatim (mismo chunk-id).
- El error del upstream se relaya como 502 igual que en el carril orquestado.
- Sin sesiones: los passthrough no dejan estado en el store.
"""

from app.config import settings
from app.main import _is_passthrough_model


class TestLaneDetection:

    def test_mapping_syntax_lane_detected_and_resolved(self, monkeypatch):
        """F8: la forma "carril=modelo" registra el carril para la detección y
        el mapa resuelve al modelo real del upstream."""
        from app.main import _passthrough_map

        monkeypatch.setattr(settings, "passthrough_models", "miura-fast=Qwen3.5-4B")
        assert _is_passthrough_model("miura-fast") is True
        assert _is_passthrough_model("MIURA-FAST") is True
        assert _is_passthrough_model("Qwen3.5-4B") is False
        assert _passthrough_map() == {"miura-fast": "Qwen3.5-4B"}

    def test_mapping_survives_spaces_and_multiple_lanes(self, monkeypatch):
        from app.main import _passthrough_map

        monkeypatch.setattr(
            settings, "passthrough_models", " miura-fast = Qwen3.5-4B , gemma-fast =Gemma4-E2B, plain-lane"
        )
        lane_map = _passthrough_map()
        assert lane_map == {
            "miura-fast": "Qwen3.5-4B",
            "gemma-fast": "Gemma4-E2B",
            "plain-lane": None,
        }
        assert _is_passthrough_model("plain-lane") is True
        assert _is_passthrough_model("gemma-fast") is True

    def test_shipped_default_is_empty(self):
        """Afirmar el default del CAMPO, no el valor vivo (patrón del resto del
        suite): el .env del desarrollador puede cargar carriles."""
        from app.config import Settings

        assert Settings.model_fields["passthrough_models"].default == ""

    def test_no_lanes_configured_no_model_is_passthrough(self):
        assert settings.passthrough_models == ""
        assert _is_passthrough_model("miura-fast") is False
        assert _is_passthrough_model("cualquiera") is False

    def test_configured_lane_matches_case_insensitive(self, monkeypatch):
        monkeypatch.setattr(settings, "passthrough_models", "miura-fast, otro")
        assert _is_passthrough_model("miura-fast") is True
        assert _is_passthrough_model("MIURA-FAST") is True
        assert _is_passthrough_model(" Miura-Fast ") is True
        assert _is_passthrough_model("otro") is True
        # Coincidencia exacta: prefijos/casi-iguales NO cuentan.
        assert _is_passthrough_model("miura-fast-2") is False
        assert _is_passthrough_model("miura") is False

    def test_empty_model_is_never_passthrough(self, monkeypatch):
        monkeypatch.setattr(settings, "passthrough_models", "miura-fast")
        assert _is_passthrough_model("") is False
        assert _is_passthrough_model(None) is False


class TestPassthroughNoStream:

    async def test_single_call_relayed_verbatim(self, client, fake_upstream, monkeypatch):
        monkeypatch.setattr(settings, "passthrough_models", "miura-fast")
        fake_upstream.queue_completion(content="respuesta directa")

        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "miura-fast",
                "messages": [{"role": "user", "content": "hola"}],
                "temperature": 0.3,
                "max_tokens": 128,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # Respuesta COMPLETA del upstream (no solo el mensaje del proxy).
        assert body["choices"][0]["message"]["content"] == "respuesta directa"
        assert body["object"] == "chat.completion"

        # UNA sola llamada HTTP: sin descomposición, sin síntesis.
        assert len(fake_upstream.received) == 1
        sent = fake_upstream.received[0]
        assert sent["model"] == "miura-fast"
        # Los mensajes del caller viajan TAL CUAL (sin system prompts propios).
        assert sent["messages"] == [{"role": "user", "content": "hola"}]
        # temperature/max_tokens preservados.
        assert sent["temperature"] == 0.3
        assert sent["max_tokens"] == 128

    async def test_mapped_lane_sends_upstream_model(self, client, fake_upstream, monkeypatch):
        """F8: con "carril=modelo", el upstream recibe el modelo REAL — no el
        alias del carril — pero todo lo demás viaja intacto y el caller ve la
        respuesta completa como en el carril verbatim."""
        monkeypatch.setattr(settings, "passthrough_models", "miura-fast=Qwen3.5-4B")
        fake_upstream.queue_completion(content="respuesta mapeada")

        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "miura-fast",
                "messages": [{"role": "user", "content": "hola"}],
                "temperature": 0.2,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "respuesta mapeada"

        assert len(fake_upstream.received) == 1
        sent = fake_upstream.received[0]
        # El modelo que llega al upstream es el objetivo del mapeo…
        assert sent["model"] == "Qwen3.5-4B"
        # …y el resto del payload sigue siendo el del caller, tal cual.
        assert sent["messages"] == [{"role": "user", "content": "hola"}]
        assert sent["temperature"] == 0.2

    async def test_tools_and_tool_choice_preserved(self, client, fake_upstream, monkeypatch):
        monkeypatch.setattr(settings, "passthrough_models", "miura-fast")
        fake_upstream.queue_completion(
            content=None,
            tool_calls=[{"id": "call-1", "function": {"name": "get_time", "arguments": "{}"}}],
        )
        tools = [{"type": "function", "function": {"name": "get_time", "description": "hora"}}]

        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "miura-fast",
                "messages": [{"role": "user", "content": "qué hora es"}],
                "tools": tools,
                "tool_choice": "auto",
            },
        )
        assert resp.status_code == 200
        sent = fake_upstream.received[0]
        assert sent["tools"] == tools
        assert sent["tool_choice"] == "auto"
        # El tool_call del upstream viaja al caller intacto.
        assert resp.json()["choices"][0]["message"]["tool_calls"][0]["id"] == "call-1"

    async def test_upstream_error_relays_as_502(self, client, fake_upstream, monkeypatch):
        monkeypatch.setattr(settings, "passthrough_models", "miura-fast")
        fake_upstream.queue_error(status_code=500)

        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "miura-fast", "messages": [{"role": "user", "content": "x"}]},
        )
        assert resp.status_code == 502
        assert resp.json()["error"]["type"] == "upstream_error"

    async def test_no_session_state_is_created(self, client, fake_upstream, monkeypatch):
        """El carril passthrough no toca el store de sesiones: dos llamadas
        seguidas con el mismo historial no reanudan ni heredan nada."""
        monkeypatch.setattr(settings, "passthrough_models", "miura-fast")
        fake_upstream.queue_completion(content="uno")
        fake_upstream.queue_completion(content="dos")

        payload = {"model": "miura-fast", "messages": [{"role": "user", "content": "hola"}]}
        first = await client.post("/v1/chat/completions", json=payload)
        second = await client.post("/v1/chat/completions", json=payload)
        assert first.status_code == 200 and second.status_code == 200

        from app.main import session_store

        assert session_store._sessions == {}


class TestPassthroughStream:

    async def test_stream_relays_upstream_sse_verbatim(self, client, fake_upstream, monkeypatch):
        monkeypatch.setattr(settings, "passthrough_models", "miura-fast")
        fake_upstream.queue_stream(pieces=["hola", " ", "mundo"])

        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "miura-fast",
                "stream": True,
                "messages": [{"role": "user", "content": "x"}],
            },
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

        text = (await resp.aread()).decode()
        # El stream es el del UPSTREAM: cada pieza viaja como delta de content.
        assert '"content": "hola"' in text
        assert '"content": "mundo"' in text
        assert text.strip().endswith("data: [DONE]")
        # Una sola llamada HTTP.
        assert len(fake_upstream.received) == 1
        sent = fake_upstream.received[0]
        assert sent["stream"] is True
        assert sent["messages"] == [{"role": "user", "content": "x"}]

    async def test_stream_tool_calls_relayed(self, client, fake_upstream, monkeypatch):
        monkeypatch.setattr(settings, "passthrough_models", "miura-fast")
        fake_upstream.queue_stream(
            tool_calls=[{"id": "call-9", "function": {"name": "search", "arguments": '{"q": "a"}'}}]
        )

        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "miura-fast",
                "stream": True,
                "messages": [{"role": "user", "content": "x"}],
            },
        )
        assert resp.status_code == 200
        text = (await resp.aread()).decode()
        assert '"tool_calls"' in text
        assert "search" in text


class TestLaneVisibility:

    async def test_models_endpoint_lists_lanes(self, client, monkeypatch):
        monkeypatch.setattr(settings, "passthrough_models", "miura-fast")
        resp = await client.get("/v1/models")
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()["data"]]
        assert "miura-fast" in ids

    async def test_models_endpoint_without_lanes_unchanged(self, client):
        resp = await client.get("/v1/models")
        ids = [m["id"] for m in resp.json()["data"]]
        assert "miura-fast" not in ids
        assert ids == [settings.upstream_model]
