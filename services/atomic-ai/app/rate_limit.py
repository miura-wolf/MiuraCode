"""Limitador RPM del upstream (lado cliente, ventana deslizante de 60s).

Los upstreams alojados limitan las peticiones por minuto — el free-tier de
NVIDIA NIM rechaza ráfagas alrededor de ~45 RPM con ``503 ResourceExhausted``
— y el bucle de reintentos de la F2 empeora la ráfaga: cada intento rechazado
vuelve a dispararse, así que un turno descompuesto (descomposición + N hojas
+ síntesis = muchas llamadas HTTP) revienta la cuota de la cuenta.

El limitador es deliberadamente LADO CLIENTE y una única instancia por
proceso compartida por TODA llamada HTTP que hace ``UpstreamClient``:

* un proceso del proxy = un presupuesto de peticiones contra el upstream,
  sin importar cuántas requests concurrentes entren — cada intento HTTP
  (incluidos los reintentos de la F2 y el carril passthrough) pasa por
  ``acquire()``;
* ``UPSTREAM_RPM <= 0`` lo desactiva por completo (el default: un upstream
  local como llama.cpp no tiene tope por minuto). Para un upstream con tope,
  p. ej. NIM free-tier (~45 RPM), ``UPSTREAM_RPM=40`` deja margen.

Por qué ventana DESLIZANTE y no fija: una ventana fija admite la cuota
completa al final del minuto N y otra completa al inicio del N+1 — una ráfaga
2x justo en el borde, exactamente el patrón que dispara los topes por minuto.
La ventana deslizante reparte el consumo esperando a que la petición más
antigua salga de los últimos 60 segundos.

Nota de presupuesto: el tope es de la CUENTA del upstream, no de este proceso.
Si este proxy y otro proceso (p. ej. Gigaxity Deep Research) apuntan a la
misma cuenta, repartan el presupuesto entre ambos (p. ej. 20+20 bajo ~45 RPM).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Deque

from .config import settings

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60.0


class SlidingWindowRateLimiter:
    """Limitador asíncrono de ventana deslizante para un presupuesto por minuto.

    La ventana es un deque de timestamps monótonos de envío. ``acquire()``
    admite una llamada cuando hay menos de ``rpm`` entradas más jóvenes que la
    ventana; si no, duerme hasta que la entrada más antigua salga y vuelve a
    comprobar. Toda la comprobación y el registro ocurren bajo un lock de
    asyncio, así que los llamadores concurrentes hacen cola en vez de
    disputarse — N ``acquire()`` simultáneos nunca admiten más de lo que el
    presupuesto permite en cualquier ventana de 60 segundos.

    ``acquire()`` es además deliberadamente cancel-safe: solo espera en
    ``sleep`` y en el lock, así que una request abortada (cliente que se
    desconecta) deja de esperar inmediatamente y no consume hueco.
    """

    def __init__(self, rpm: int = 0, window_s: float = WINDOW_SECONDS):
        self.rpm = int(rpm)
        self.window_s = float(window_s)
        self._lock = asyncio.Lock()
        self._sent: Deque[float] = deque(maxlen=max(1, self.rpm)) if self.rpm > 0 else deque()
        # Observabilidad barata: cuántas llamadas tuvieron que esperar y cuánto
        # en total. Para tests y debugging ad-hoc; sin plomería de métricas.
        self.waited_calls: int = 0
        self.waited_total_s: float = 0.0

    @property
    def enabled(self) -> bool:
        return self.rpm > 0

    def _prune(self, now: float) -> None:
        """Descarta los timestamps que ya salieron de la ventana."""
        cutoff = now - self.window_s
        sent = self._sent
        while sent and sent[0] <= cutoff:
            sent.popleft()

    async def acquire(self) -> float:
        """Espera hasta que haya un hueco libre; devuelve los segundos esperados.

        Devuelve 0.0 inmediato cuando está desactivado — el camino
        desactivado debe quedar sin asignaciones ni locks para que el default
        sea un verdadero no-op.
        """
        if not self.enabled:
            return 0.0

        waited = 0.0
        while True:
            async with self._lock:
                now = time.monotonic()
                self._prune(now)
                if len(self._sent) < self.rpm:
                    self._sent.append(now)
                    if waited > 0:
                        self.waited_calls += 1
                        self.waited_total_s += waited
                        logger.info(
                            "rate limiter: llamada admitida tras esperar %.2fs "
                            "(rpm=%d, waited_calls=%d)",
                            waited, self.rpm, self.waited_calls,
                        )
                    return waited
                # Ventana llena: dormir hasta que la petición MÁS ANTIGUA salga.
                # Dormir FUERA del lock — retenerlo bloquearía hasta las
                # admisiones que ya tienen hueco.
                sleep_s = self._sent[0] + self.window_s - now
            await asyncio.sleep(max(0.0, sleep_s))
            waited += max(0.0, sleep_s)


_limiter: SlidingWindowRateLimiter | None = None


def get_rate_limiter() -> SlidingWindowRateLimiter:
    """Limitador por proceso para el upstream (construido perezosamente).

    Perezoso (no se construye al importar) para que los tests que fijan
    ``settings.upstream_rpm`` puedan llamar ``reset_rate_limiter()`` y observar
    el nuevo valor, y para que el mero import del módulo nunca asigne
    primitivas de asyncio.
    """
    global _limiter
    if _limiter is None:
        _limiter = SlidingWindowRateLimiter(rpm=settings.upstream_rpm)
    return _limiter


def reset_rate_limiter() -> None:
    """Suelta el limitador cacheado para que la próxima llamada relea settings.

    Hook de test/despliegue: los settings se leen una vez por proceso a
    propósito (un cambio de config a mitad de ejecución aplicándose a unas
    llamadas y a otras no es peor que un reinicio), así que esto existe para
    tests y reconfiguración deliberada.
    """
    global _limiter
    _limiter = None
