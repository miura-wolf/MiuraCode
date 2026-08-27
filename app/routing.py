"""F1 — Routing multi-modelo por especialidad.

Detecta la especialidad de una tarea atómica (visión, código, resumen rápido o
por defecto) a partir de su descripción, y resuelve qué modelo del arsenal
local debe ejecutarla. La clasificación es puramente determinística
(heurística de palabras clave con fronteras de palabra) para no añadir
fragilidad de LLM en el paso de routing: si el detector se equivoca, el
peor caso es usar un modelo subóptimo, nunca romper el flujo.

Reglas de diseño:
- La especialidad "vision" solo se activa si el turno trae imágenes Y la tarea
  la referencia (de nada sirve routear a un modelo de visión sin imágenes).
- Prioridad de clasificación: vision > code > fast > default.
- resolve_model() mapea especialidad -> modelo concreto; si el modelo de esa
  especialidad no está configurado (vacío), cae al modelo base del turno, así
  que el sistema degrada con elegancia si solo hay un modelo disponible.
"""
from __future__ import annotations

import re
from typing import Literal

from .config import settings

Specialty = Literal["vision", "code", "fast", "default"]

# Palabras clave por especialidad (español + inglés). Intencionalmente
# conservadoras: solo clasifican cuando hay señal clara.
_VISION_KEYWORDS = (
    "imagen", "imágenes", "foto", "fotos", "fotografía", "captura", "screenshot",
    "qué ves", "que ves", "describe la imagen", "describe la foto",
    "mira la", "observa la", "ilustración", "dibujo", "visualiza",
    "picture", "image", "photo",
)
_CODE_KEYWORDS = (
    "código", "codigo", "función", "funcion", "clase", "método", "metodo",
    "python", "javascript", "typescript", "java", "sql", "html", "css",
    "implementa", "programa", "script", "algoritmo", "refactor", "bug",
    "depura", "debug", "compila", "endpoint", "api", "regex",
    "prueba unitaria", "unit test", "code", "function", "class",
)
_FAST_KEYWORDS = (
    "resume", "resumen", "resumí", "sintetiza", "síntesis", "breve",
    "en pocas palabras", "enumera", "lista los", "titula", "título",
    "traduce", "puntos clave", "summary", "summarize", "bullet",
)


def _compile(keywords: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(
        re.compile(r"\b" + re.escape(k) + r"\b", re.IGNORECASE) for k in keywords
    )


_VISION_RE = _compile(_VISION_KEYWORDS)
_CODE_RE = _compile(_CODE_KEYWORDS)
_FAST_RE = _compile(_FAST_KEYWORDS)


def _any_match(regexes: tuple[re.Pattern[str], ...], text: str) -> bool:
    return any(rx.search(text) for rx in regexes)


def detect_specialty(task: str, has_images: bool = False) -> Specialty:
    """Devuelve la especialidad de una tarea atómica según su descripción.

    Prioridad: vision (solo si hay imágenes y la tarea la referencia) > code
    > fast > default. Clasifica por la *naturaleza* de la tarea, no por la
    disponibilidad de modelos — esa degradación la hace resolve_model().
    """
    if has_images and _any_match(_VISION_RE, task):
        return "vision"
    if _any_match(_CODE_RE, task):
        return "code"
    if _any_match(_FAST_RE, task):
        return "fast"
    return "default"


def resolve_model(specialty: Specialty, base_model: str) -> str:
    """Mapea especialidad -> modelo concreto. Si el routing está desactivado o
    el modelo de la especialidad no está configurado, devuelve el modelo base."""
    if not settings.specialty_routing:
        return base_model
    mapping = {
        "vision": settings.vision_model,
        "code": settings.code_model,
        "fast": settings.fast_model,
    }
    chosen = mapping.get(specialty, "")
    return chosen or base_model


def resolve_synthesis_model(base_model: str) -> str:
    """Modelo para la síntesis final. Vacío o routing desactivado = modelo base."""
    if not settings.specialty_routing:
        return base_model
    return settings.synthesis_model or base_model
