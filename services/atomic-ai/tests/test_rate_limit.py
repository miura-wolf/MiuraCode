"""Limitador RPM del upstream — invariantes de la ventana deslizante y del
cableado en UpstreamClient.

Por qué lado cliente: el free-tier de NVIDIA NIM rechaza ráfagas alrededor de
~45 RPM con ``503 ResourceExhausted``, y el bucle de reintentos de la F2
repite cada intento rechazado, así que un turno descompuesto (descomposición
+ N hojas + síntesis = muchas llamadas HTTP) revienta la cuota de la CUENTA.
El limitador espera un hueco en vez de dejar que el upstream responda 503.

Estos tests fijan el contrato: desactivado (rpm=0) es un verdadero no-op y es
el default del código distribuido; la ventana desliza (sin ráfaga 2x en el
borde del minuto); toda llamada HTTP del UpstreamClient gasta de un único
presupuesto por proceso — incluidos los reintentos de la F2 y el carril
passthrough de la F8; y una llamada abortada deja de esperar de inmediato, sin
consumir hueco.
"""

import asyncio
import time

import pytest

from app.config import Settings, settings
from app.rate_limit import (
    SlidingWindowRateLimiter,
    WINDOW_SECONDS,
    reset_rate_limiter,
)
from app.upstream import UpstreamClient


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Cada test arranca con la caché del limitador limpia.

    El limitador es por proceso a propósito (un proceso = un presupuesto
    contra el upstream), así que la contaminación entre tests es la única fuga
    que este fixture cierra: sin él, un test que activara rpm=10 dejaría al
    siguiente esperando tras timestamps viejos."""
    reset_rate_limiter()
    yield
    reset_rate_limiter()


class TestDisabledByDefault:

    def test_shipped_default_is_zero(self):
        """Afirmar el default del CAMPO, no el valor vivo de settings: pydantic
        carga el .env del desarrollador (p. ej. UPSTREAM_RPM=40 para el perfil
        NIM), así que `settings.upstream_rpm` lee configuración de despliegue,
        no el código que se distribuye."""
        assert Settings.model_fields["upstream_rpm"].default == 0

    async def test_disabled_is_noop(self):
        lim = SlidingWindowRateLimiter(rpm=0)
        assert lim.enabled is False
        assert await lim.acquire() == 0.0


class TestSlidingWindowArithmetic:

    async def test_admits_within_budget_without_waiting(self):
        lim = SlidingWindowRateLimiter(rpm=5, window_s=WINDOW_SECONDS)
        waited = [await lim.acquire() for _ in range(5)]
        assert waited == [0.0] * 5

    async def test_sixth_call_waits_for_the_oldest_to_age_out(self):
        lim = SlidingWindowRateLimiter(rpm=2, window_s=0.2)
        await lim.acquire()
        await lim.acquire()
        start = time.monotonic()
        waited = await lim.acquire()
        elapsed = time.monotonic() - start
        # La tercera llamada esperó ~una ventana a que la primera saliera.
        assert waited > 0.05
        assert elapsed >= waited * 0.9

    async def test_window_slides_no_boundary_burst(self):
        """La ventana deslizante NO debe admitir cuota fresca en el borde del
        minuto como sí lo haría una ventana fija — 2rpm significa a lo sumo 2
        envíos en CUALQUIER slice de 60s, no 2 al final del minuto N y 2 más
        justo después."""
        lim = SlidingWindowRateLimiter(rpm=2, window_s=0.2)
        await lim.acquire()          # envío A en t=0
        await asyncio.sleep(0.1)
        await lim.acquire()          # envío B en t=0.1
        # En t≈0.21: A (t=0) ya salió de la ventana, B (t=0.1) sigue dentro
        # hasta t=0.31, así que hay UN hueco libre (no dos).
        await asyncio.sleep(0.11)
        start = time.monotonic()
        await lim.acquire()          # admitido sin esperar una ventana entera
        assert time.monotonic() - start < 0.05

    async def test_cancelled_acquire_consumes_no_slot(self):
        """Cancel-safe: una llamada abortada deja de esperar enseguida y no
        consume presupuesto (un hueco reservado que nadie usa es cuota regalada
        contra el tope del upstream)."""
        lim = SlidingWindowRateLimiter(rpm=1, window_s=WINDOW_SECONDS)
        assert await lim.acquire() == 0.0
        task = asyncio.create_task(lim.acquire())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # La ventana quedó intacta: sigue habiendo exactamente 1 envío dentro.
        assert len(lim._sent) == 1


class TestUpstreamBudgetWiring:

    async def test_every_upstream_call_draws_from_one_budget(self, fake_upstream, monkeypatch):
        """Toda llamada HTTP del UpstreamClient gasta del mismo presupuesto por
        proceso: con rpm=2, la tercera llamada espera (ventana acortada para
        el test) en vez de dispararse contra el upstream."""
        monkeypatch.setattr(settings, "upstream_rpm", 2)
        reset_rate_limiter()
        client = UpstreamClient()
        client._rate_limiter.window_s = 0.15
        for i in range(3):
            fake_upstream.queue_completion(content=f"respuesta {i}")
        messages = [{"role": "user", "content": "x"}]
        start = time.monotonic()
        first = await client.complete(messages, model="m")
        second = await client.complete(messages, model="m")
        third = await client.complete(messages, model="m")
        elapsed = time.monotonic() - start
        assert (first, second, third) == ("respuesta 0", "respuesta 1", "respuesta 2")
        # La tercera esperó a que la primera saliera de la ventana.
        assert elapsed >= 0.1
        assert len(fake_upstream.received) == 3

    async def test_each_retry_attempt_consumes_budget(self, fake_upstream, monkeypatch):
        """El bucle de reintentos de la F2 es precisamente el amplificador de
        ráfagas contra un upstream con tope: cada INTENTO HTTP pasa por
        acquire(), no cada request del caller."""
        monkeypatch.setattr(settings, "upstream_rpm", 1)
        monkeypatch.setattr(settings, "upstream_max_retries", 1)
        reset_rate_limiter()
        client = UpstreamClient()
        client._rate_limiter.window_s = 0.15
        fake_upstream.queue_error(status_code=500)
        fake_upstream.queue_completion(content="tras el retry")
        messages = [{"role": "user", "content": "x"}]
        start = time.monotonic()
        result = await client.complete(messages, model="m")
        elapsed = time.monotonic() - start
        assert result == "tras el retry"
        # El reintento esperó su hueco de presupuesto, no lo robó.
        assert elapsed >= 0.1
        assert len(fake_upstream.received) == 2

    async def test_disabled_limiter_never_blocks_a_call(self, fake_upstream):
        """rpm=0 (el default que fija el conftest) es un no-op verdadero:
        el limiter queda deshabilitado y acquire() no espera nada (se afirma
        el estado del limiter, no el reloj — el overhead de httpx/respx
        haría una aserción de wall-time frágil)."""
        client = UpstreamClient()
        assert client._rate_limiter.enabled is False
        assert await client._rate_limiter.acquire() == 0.0
        for i in range(3):
            fake_upstream.queue_completion(content=f"r{i}")
        messages = [{"role": "user", "content": "x"}]
        for i in range(3):
            assert await client.complete(messages, model="m") == f"r{i}"
        # Ninguna espera registrada: el no-op es real.
        assert client._rate_limiter.waited_calls == 0


class TestNIMFreeTierProfile:

    def test_documented_profile_stays_under_the_cap(self):
        """El free-tier de NIM rechaza ráfagas alrededor de ~45 RPM; el perfil
        recomendado (40) debe quedar por debajo con margen. El default
        distribuido se afirma vía el CAMPO (model_fields), inmune al .env del
        desarrollador — ese archivo es configuración de despliegue. Ojo: el
        tope es de la CUENTA del upstream; si este proxy y otro proceso (p. ej.
        Gigaxity) apuntan a la misma cuenta, hay que repartir (20+20)."""
        lim = SlidingWindowRateLimiter(rpm=40)
        assert lim.rpm < 45
        assert Settings.model_fields["upstream_rpm"].default == 0
