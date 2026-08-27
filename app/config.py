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

    def resolved_api_key(self) -> str:
        return self.upstream_api_key or os.environ.get("DEEPSEEK_API_KEY", "")


settings = Settings()
