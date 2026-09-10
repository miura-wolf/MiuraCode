import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    upstream_base_url: str = "https://api.deepseek.com"
    upstream_api_key: str = ""
    upstream_model: str = "deepseek-v4-flash"

    max_decomposition_depth: int = 3
    max_tool_rounds_per_phase: int = 25

    proxy_host: str = "127.0.0.1"
    proxy_port: int = 8000

    request_timeout_seconds: float = 120.0

    session_ttl_seconds: float = 1800.0
    max_sessions: int = 200

    expose_reasoning_content: bool = True

    database_path: str = "atomic_ai.db"

    # Servidor local de embeddings (OpenAI-compatible /v1/embeddings).
    # Vacío = la búsqueda de conocimiento usa solo keywords (FTS5).
    embeddings_base_url: str = ""
    embeddings_model: str = "qwen3-embedding"
    embeddings_timeout_seconds: float = 30.0

    # Búsqueda híbrida: fusiona resultados FTS5 (keywords) y similitud coseno
    # contra vectores persistidos. Requiere embeddings_base_url configurado.
    hybrid_search: bool = True
    hybrid_candidates: int = 6

    # Auto-aprendizaje: guardar resultados exitosos de hojas/síntesis en la
    # base de conocimiento para reutilizarlos en tareas futuras similares.
    auto_learn_knowledge: bool = True

    # Protección opcional de los endpoints admin (/v1/knowledge*). Vacío =
    # sin token extra (confía en localhost).
    admin_token: str = ""

    # F1 — Routing multi-modelo por especialidad. Cuando está activo, el motor
    # asigna un modelo distinto a cada hoja atómica según su especialidad
    # detectada (visión, código, resumen rápido) en lugar de usar un único
    # modelo para todo el turno. Cada modelo de especialidad vacío = usa el
    # modelo base del turno. La descomposición (Fase 1) siempre usa el modelo
    # base porque planificar es la tarea más exigente.
    specialty_routing: bool = False
    vision_model: str = ""
    code_model: str = ""
    fast_model: str = ""
    synthesis_model: str = ""

    # F2 — Resiliencia: reintentos y fallback ante fallos del upstream.
    # Cuántos reintentos de transporte hacer ante un error transitorio
    # (timeout, conexión, 5xx, 429). 0 = sin reintentos. El backoff es lineal:
    # base * (intento). Los 4xx no transitorios (auth, bad request, modelo no
    # encontrado) nunca se reintentan.
    upstream_max_retries: int = 2
    upstream_retry_backoff_seconds: float = 0.5
    # Modelo de respaldo: si está configurado, los reintentos (intento > 0)
    # usan este modelo en vez del original. Vacío = reintentar con el mismo.
    fallback_model: str = ""

    # F3 — Ejecución paralela de hojas atómicas independientes. Cuando está
    # activo y no hay tools activas, las hojas atómicas se ejecutan en paralelo
    # (asyncio.gather) en vez de secuencialmente, lo que da un speedup real en
    # tareas con varias subtareas independientes. Asume que las subtareas no
    # dependen unas de otras. Con tools activas se vuelve automáticamente al
    # modo secuencial (la pausa/reanudación de tool_calls es secuencial).
    parallel_leaves: bool = False

    # F4 — Streaming con progreso del árbol. Cuando está activo, el stream SSE
    # emite chunks extra con un campo `progress` (phase_started/leaf_started/
    # leaf_done/phase_done/done) para que los clientes agénticos muestren
    # progreso real. Los clientes OpenAI estándar ignoran ese campo, así que es
    # retrocompatible.
    emit_progress_events: bool = False

    # F7 — Investigación web (deep research) como fallback del RAG local. Cuando
    # la base de conocimiento local no devuelve nada (miss), el motor llama a un
    # servicio acompañante Gigaxity Deep Research (REST) para obtener una síntesis
    # web con citas e inyectarla al contexto de la hoja atómica. La feature queda
    # desactivada mientras ``web_research_base_url`` esté vacío. El servicio se
    # despliega aparte (ver ../gigaxity-deep-research) apuntando a NIM + SearXNG.
    web_research_base_url: str = ""
    web_research_enabled: bool = True
    web_research_timeout_seconds: float = 90.0
    web_research_top_k: int = 8
    web_research_preset: str = "fast"
    web_research_reasoning_effort: str = "medium"
    web_research_auto_learn: bool = True
    web_research_max_concurrency: int = 2

    # Limitador RPM del upstream (lado cliente, ventana deslizante de 60s).
    # Tope de llamadas HTTP por minuto compartido por TODAS las fases del
    # proxy (descomposición, hojas, síntesis, reintentos F2 y passthrough).
    # Pensado para free-tiers con tope por minuto (NVIDIA NIM ~45 RPM → 40).
    # 0 = desactivado (default: un upstream local como llama.cpp no tiene
    # tope). Ver app/rate_limit.py.
    upstream_rpm: int = 0

    # Carril passthrough: modelos (coma-separados) que se reenvían al
    # upstream con UNA sola llamada — sin descomposición, sin RAG y sin
    # sesiones. Es el carril de latencia mínima para chat directo (p. ej.
    # "miura-fast"). Cada entrada es "carril" (se reenvía el nombre tal
    # cual) o "carril=modelo" (mapeo a un modelo real del upstream, para
    # cuando éste no conoce el alias, p. ej. "miura-fast=Qwen3.5-4B").
    # Vacío = ninguno. Sus llamadas pasan por el mismo presupuesto
    # UPSTREAM_RPM que el resto.
    passthrough_models: str = ""

    def resolved_api_key(self) -> str:
        return self.upstream_api_key or os.environ.get("DEEPSEEK_API_KEY", "")


settings = Settings()
