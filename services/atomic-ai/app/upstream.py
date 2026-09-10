import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Optional

import httpx

from .config import settings

# Códigos HTTP que consideramos transitorios (reintentables). Los 4xx restantes
# (auth, bad request, modelo no encontrado...) no se reintentan: reintentar no
# va a arreglarlos.
_TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}


class UpstreamError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _is_transient(exc: Exception) -> bool:
    """True si el fallo es transitorio (timeout, conexión, 5xx/429) y por tanto
    tiene sentido reintentar."""
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, UpstreamError) and exc.status_code in _TRANSIENT_STATUS:
        return True
    return False


class UpstreamClient:
    def __init__(self) -> None:
        self._base_url = settings.upstream_base_url.rstrip("/")
        self._api_key = settings.resolved_api_key()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _model_for_attempt(self, model: str, attempt: int) -> str:
        """F2: en los reintentos (intento > 0) usa el modelo de respaldo si está
        configurado; si no, repite el modelo original."""
        if attempt > 0 and settings.fallback_model:
            return settings.fallback_model
        return model

    def _build_payload(
        self,
        model: str,
        messages: list[dict[str, Any]],
        json_mode: bool,
        tools: Optional[list[dict[str, Any]]],
        tool_choice: Optional[Any],
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        return payload

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        json_mode: bool = False,
    ) -> str:
        message = await self.complete_raw(messages, model, json_mode=json_mode)
        return message.get("content") or ""

    async def complete_raw(
        self,
        messages: list[dict[str, Any]],
        model: str,
        json_mode: bool = False,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
    ) -> dict[str, Any]:
        attempts = max(1, settings.upstream_max_retries + 1)
        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            payload = self._build_payload(
                self._model_for_attempt(model, attempt),
                messages,
                json_mode,
                tools,
                tool_choice,
                stream=False,
            )
            try:
                async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                    resp = await client.post(
                        f"{self._base_url}/v1/chat/completions",
                        headers=self._headers(),
                        json=payload,
                    )
                if resp.status_code >= 400:
                    raise UpstreamError(
                        f"Upstream error {resp.status_code}: {resp.text}",
                        status_code=resp.status_code,
                    )
                data = resp.json()
                choice = data["choices"][0]
                message = choice["message"]
                message.setdefault("finish_reason", choice.get("finish_reason"))
                return message
            except Exception as exc:  # clasificamos justo debajo
                if not _is_transient(exc):
                    raise
                last_exc = exc
            if attempt < attempts - 1:
                await asyncio.sleep(settings.upstream_retry_backoff_seconds * (attempt + 1))
        raise UpstreamError(f"Upstream indisponible tras {attempts} intentos: {last_exc}")

    async def _stream_raw_chunks(
        self,
        messages: list[dict[str, Any]],
        model: str,
        json_mode: bool = False,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        attempts = max(1, settings.upstream_max_retries + 1)
        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            payload = self._build_payload(
                self._model_for_attempt(model, attempt),
                messages,
                json_mode,
                tools,
                tool_choice,
                stream=True,
            )
            client = httpx.AsyncClient(timeout=settings.request_timeout_seconds)
            response = None
            try:
                request = client.build_request(
                    "POST",
                    f"{self._base_url}/v1/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
                response = await client.send(request, stream=True)
                if response.status_code >= 400:
                    body = await response.aread()
                    raise UpstreamError(
                        f"Upstream error {response.status_code}: {body.decode()}",
                        status_code=response.status_code,
                    )
            except Exception as exc:
                if response is not None:
                    await response.aclose()
                await client.aclose()
                if not _is_transient(exc):
                    raise
                last_exc = exc
                if attempt < attempts - 1:
                    await asyncio.sleep(settings.upstream_retry_backoff_seconds * (attempt + 1))
                continue
            # Conexión establecida y status OK: a partir de aquí ya no se
            # reintenta (un fallo a mitad de stream se propaga al consumidor).
            try:
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break
                    chunk = json.loads(data_str)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    yield choices[0]
            finally:
                await response.aclose()
                await client.aclose()
            return
        raise UpstreamError(f"Upstream indisponible tras {attempts} intentos: {last_exc}")

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        json_mode: bool = False,
    ) -> AsyncIterator[str]:
        async for choice in self._stream_raw_chunks(messages, model, json_mode=json_mode):
            piece = choice.get("delta", {}).get("content")
            if piece:
                yield piece

    async def stream_raw(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        async for choice in self._stream_raw_chunks(
            messages, model, tools=tools, tool_choice=tool_choice
        ):
            yield {
                "delta": choice.get("delta", {}),
                "finish_reason": choice.get("finish_reason"),
            }
