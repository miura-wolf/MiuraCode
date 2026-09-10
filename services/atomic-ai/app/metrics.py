from __future__ import annotations

"""F6 — Observabilidad / métricas.

Registro ligero, en memoria y sin dependencias externas, de contadores y
latencias del motor. Pensado para exponerse vía ``GET /v1/stats`` y para logs
estructurados. Es intencionalmente simple (dict + acumuladores) porque el proxy
es local y de un solo proceso; no justifica traer Prometheus ni similar.

Todo es thread/async seguro en la práctica porque las mutaciones son
operaciones atómicas de dict/list bajo el GIL y el proxy es single-process.
"""

import time
from typing import Any


class Metrics:
    """Acumulador de contadores y latencias por fase."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        # fase -> [suma_segundos, nº_muestras, máximo_segundos]
        self._latency: dict[str, list[float]] = {}
        self.started_at = time.time()

    # -- contadores -----------------------------------------------------
    def inc(self, name: str, amount: int = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + amount

    def get(self, name: str) -> int:
        return self._counters.get(name, 0)

    # -- latencias ------------------------------------------------------
    def observe(self, phase: str, seconds: float) -> None:
        bucket = self._latency.setdefault(phase, [0.0, 0, 0.0])
        bucket[0] += seconds
        bucket[1] += 1
        if seconds > bucket[2]:
            bucket[2] = seconds

    # -- snapshot -------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        latency: dict[str, dict[str, float]] = {}
        for phase, (total, count, mx) in self._latency.items():
            latency[phase] = {
                "count": count,
                "total_s": round(total, 4),
                "avg_s": round(total / count, 4) if count else 0.0,
                "max_s": round(mx, 4),
            }
        return {
            "uptime_s": round(time.time() - self.started_at, 1),
            "counters": dict(self._counters),
            "latency": latency,
        }

    def reset(self) -> None:
        self._counters.clear()
        self._latency.clear()
        self.started_at = time.time()


# Instancia única compartida por todo el proceso.
metrics = Metrics()


__all__ = ["Metrics", "metrics"]
