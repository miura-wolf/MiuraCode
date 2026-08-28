from __future__ import annotations

"""F7 — Cliente de investigación web (Gigaxity Deep Research, REST).

Cuando la base de conocimiento local no tiene respuesta (miss del RAG), el
motor puede llamar a un servicio acompañante ``gigaxity-deep-research`` para
obtener una síntesis web con citas. Este módulo encapsula esa llamada.

Sigue el mismo contrato de degradación silenciosa que la capa de embeddings:
NUNCA bloquea ni rompe el flujo principal del proxy — cualquier fallo (servicio
caído, timeout, error HTTP, respuesta vacía) se traduce en ``None`` y el motor
continúa exactamente igual que si la feature no existiera.

El servicio externo se configura por URL base (``WEB_RESEARCH_BASE_URL``);
mientras esté vacía la feature queda desactivada y no se hace ninguna llamada.
Solo depende de ``httpx`` (ya presente en requirements.txt).
"""

import asyncio
import time
from typing import Any, Optional

import httpx

from .config import settings
from .metrics import metrics

# Gigaxity antepone este marcador cuando su quality-gate no pudo verificar las
# citas (falso negativo habitual cuando el modelo de síntesis cita con 【N】 de
# ancho completo y el verificador solo reconoce [N]); la síntesis útil sigue
# debajo del marcador. Se usa para quedarse únicamente con la síntesis real.
_UNVERIFIED_MARKER = "(unverified output below, for debugging)"


class WebResearchClient:
    """Cliente mínimo contra ``POST /api/v1/research`` de Gigaxity."""

    def __init__(self) -> None:
        # Semaphore para no lanzar N síntesis web en paralelo cuando varias hojas
        # fallen a la vez (F3 paralelo) y saturar el free-tier del LLM/search. Se
        # crea de forma perezosa y ligado al event loop actual (pytest-asyncio
        # estrena loop por test, y un Semaphore ligado a un loop muerto fallaría).
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._semaphore_loop: Optional[asyncio.AbstractEventLoop] = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._semaphore is None or self._semaphore_loop is not loop:
            self._semaphore_loop = loop
            self._semaphore = asyncio.Semaphore(max(1, settings.web_research_max_concurrency))
        return self._semaphore

    @property
    def enabled(self) -> bool:
        return bool(settings.web_research_base_url) and settings.web_research_enabled

    async def research(self, query: str) -> Optional[dict[str, Any]]:
        """Investiga ``query`` en la web. Devuelve el dict de Gigaxity
        (``content``, ``citations``, ``sources``, ...) o ``None`` si la feature
        está desactivada, la respuesta llega vacía o cualquier cosa falla."""
        if not self.enabled or not (query or "").strip():
            return None

        metrics.inc("web_research_queries")
        base_url = settings.web_research_base_url.rstrip("/")
        payload = {
            "query": query,
            "top_k": settings.web_research_top_k,
            "preset": settings.web_research_preset,
            "reasoning_effort": settings.web_research_reasoning_effort,
        }
        started = time.monotonic()
        try:
            async with self._get_semaphore():
                async with httpx.AsyncClient(timeout=settings.web_research_timeout_seconds) as client:
                    resp = await client.post(f"{base_url}/api/v1/research", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
        except Exception:
            metrics.inc("web_research_errors")
            return None
        finally:
            metrics.observe("web_research", time.monotonic() - started)

        content = (data.get("content") or "").strip() if isinstance(data, dict) else ""
        if not content:
            metrics.inc("web_research_misses")
            return None
        metrics.inc("web_research_hits")
        return data

    @staticmethod
    def _strip_verification_wrapper(content: str) -> str:
        """Si Gigaxity devolvió la síntesis envuelta en su aviso de 'verification
        FAILED' (falso negativo frecuente cuando el modelo cita con 【N】), extrae
        la síntesis real de debajo del marcador; sin marcador, devuelve el
        contenido tal cual. Así el prompt no recibe el encabezado 'FAILED'."""
        idx = content.find(_UNVERIFIED_MARKER)
        if idx == -1:
            return content.strip()
        return content[idx + len(_UNVERIFIED_MARKER) :].strip()

    @staticmethod
    def format_for_context(data: dict[str, Any]) -> str:
        """Convierte la respuesta de Gigaxity en un bloque de texto listo para
        inyectar en ``{knowledge}``: la síntesis (limpia del aviso de verificación
        si lo hubiera) y, al final, la lista de fuentes para trazabilidad. Usa las
        citas estructuradas si existen; si no (p. ej. el modelo citó con 【N】 y el
        parser de Gigaxity no las reconoció), cae a la lista cruda de ``sources``."""
        content = WebResearchClient._strip_verification_wrapper(
            (data.get("content") or "").strip()
        )
        lines: list[str] = ["### Investigación web (fuentes externas, con citas)", content]

        citations = data.get("citations") or []
        if citations:
            lines.append("")
            lines.append("Fuentes:")
            for c in citations:
                if not isinstance(c, dict):
                    continue
                number = c.get("number", "")
                title = (c.get("title") or "").strip()
                url = (c.get("url") or "").strip()
                label = f"[{number}] " if number not in ("", None) else ""
                if title and url:
                    lines.append(f"- {label}{title} — {url}")
                elif url:
                    lines.append(f"- {label}{url}")
            return "\n".join(lines)

        sources = data.get("sources") or []
        if sources:
            lines.append("")
            lines.append("Fuentes:")
            for s in sources:
                if not isinstance(s, dict):
                    continue
                title = (s.get("title") or "").strip()
                url = (s.get("url") or "").strip()
                if title and url:
                    lines.append(f"- {title} — {url}")
                elif url:
                    lines.append(f"- {url}")
        return "\n".join(lines)


# Instancia única compartida por todo el proceso (como ``metrics``/``settings``).
web_research = WebResearchClient()


__all__ = ["WebResearchClient", "web_research"]
