# Atomic Decomposition Proxy

Proxy HTTP compatible con la API de OpenAI (`/v1/chat/completions`) que se coloca delante de un modelo LLM "upstream" (por defecto, DeepSeek) y, en vez de reenviar la conversación tal cual, **descompone cada instrucción en un árbol de subtareas atómicas, las resuelve una por una y luego sintetiza una respuesta final**.

La idea: modelos más pequeños o más baratos suelen fallar en tareas compuestas porque intentan resolverlo todo de un tirón. Este proxy fuerza un proceso de tres fases —planificar, ejecutar, sintetizar— para que cada paso sea lo bastante simple como para resolverse bien, manteniendo compatibilidad total con clientes que ya hablan el protocolo de OpenAI (incluye streaming SSE, `tool_calls`, contenido multimodal y `reasoning_content`).

## Video

<p align="center">
<b>1. Teoría</b> — cómo funciona el proceso de descomposición atómica, sin mostrar aún el script:<br><br>
<a href="https://www.youtube.com/watch?v=ruscNB4dLL4"><img src="https://img.youtube.com/vi/ruscNB4dLL4/hqdefault.jpg" alt="Teoría de la descomposición atómica"></a>
</p>

<p align="center">
<b>2. Demo</b> — el script en acción, probado en vivo:<br><br>
<a href="https://www.youtube.com/watch?v=OdK6iUHGamo"><img src="https://img.youtube.com/vi/OdK6iUHGamo/hqdefault.jpg" alt="Demo del script funcionando"></a>
</p>

## Cómo funciona

Cada turno del usuario pasa por tres fases, orquestadas por `AtomicDecompositionEngine` ([app/engine.py](app/engine.py)):

1. **Descomposición** — el modelo decide si la instrucción es atómica (resoluble en un solo paso) o si conviene dividirla en subtareas concretas y ordenadas. Se aplica recursivamente hasta una profundidad máxima configurable, construyendo un árbol de tareas.
2. **Ejecución de hojas atómicas** — cada tarea atómica del árbol se resuelve en su propia llamada al modelo, con el resultado de las tareas anteriores como contexto acumulado. Si el modelo necesita usar una herramienta (`tool_calls`), la ejecución se pausa y se le devuelve el `tool_calls` al cliente, tal como espera el protocolo de OpenAI.
3. **Síntesis final** — con todos los resultados atómicos ya resueltos, se genera la respuesta final que efectivamente se entrega al usuario (el resto del proceso se transmite como `reasoning_content`, no como la respuesta visible).

El detalle de cada fase (criterios de atomicidad, cómo se le explica al modelo que existen herramientas sin dárselas como ejecutables, reglas de seguridad ante prompt injection) vive en los prompts de [app/prompts/](app/prompts).

### Sesiones y pausa/reanudación

Como una tarea atómica o la síntesis pueden requerir `tool_calls`, el proxy necesita "recordar" en qué punto del árbol se quedó entre una petición HTTP y la siguiente (el cliente responde con el resultado de la herramienta en una request nueva). `SessionStore` ([app/session.py](app/session.py)) guarda ese estado en memoria, indexado por un hash encadenado del historial de mensajes, para poder:

- Reanudar exactamente donde quedó pausado, sin rehacer descomposición ni tareas ya resueltas.
- Detectar cuándo una request es un turno nuevo sobre una conversación ya completada (y sembrarlo con el resumen de turnos previos, en vez de redecomponer todo el historial crudo desde cero).
- Expirar sesiones por TTL y limitar cuántas se mantienen en memoria.

### Compatibilidad con el protocolo OpenAI

- Acepta `stream: true/false`, `tools`, `tool_choice`, contenido multimodal (texto + imágenes) y responde en el mismo formato (`chat.completion` / `chat.completion.chunk` vía SSE).
- El razonamiento interno del proxy (qué subtareas identificó, en qué va) se expone opcionalmente como `reasoning_content`, configurable con `EXPOSE_REASONING_CONTENT`.
- El `system` prompt real del caller nunca se descarta: se antepone como capa de autoridad sobre los prompts internos de cada fase.

## Estructura del proyecto

```
app/
  main.py       Endpoints FastAPI, parseo de requests, streaming SSE
  engine.py     Motor de las 3 fases (descomposición, ejecución, síntesis)
  session.py    Persistencia de sesiones en memoria (pausa/reanudación)
  upstream.py   Cliente HTTP hacia el modelo upstream (OpenAI-compatible)
  content.py    Utilidades para separar/recomponer contenido multimodal
  schemas.py    Modelos Pydantic del request/response (formato OpenAI)
  sse.py        Helpers para construir chunks de streaming SSE
  config.py     Configuración vía variables de entorno (.env)
  prompts/      Prompts de cada fase, en Markdown
tests/          Suite de pytest (unitarios + end-to-end con upstream fake)
run.py          Arranca el servidor con uvicorn
```

## Requisitos

- Python 3.9+
- Un endpoint upstream compatible con la API de chat completions de OpenAI (por defecto, DeepSeek)

## Descarga

Desde una terminal, ubicado en la ruta donde quieras tener el proyecto:

```bash
git clone https://github.com/Nichonauta/atomic_ai.git
cd atomic_ai
```

## Instalación y ejecución

Crea un entorno virtual e instala las dependencias:

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate   # Linux / macOS
pip install -r requirements.txt
```

Copia `.env.example` a `.env` y completa tus valores (variables detalladas en [Configuración](#configuración)):

```bash
cp .env.example .env
```

Arranca el servidor:

```bash
python run.py
```

En Windows también puedes usar `run.bat`, que activa el entorno virtual y arranca el servidor.

El proxy queda disponible en `http://127.0.0.1:8000` (o el host/puerto configurado), exponiendo:

- `POST /v1/chat/completions` — endpoint principal, compatible con clientes OpenAI
- `GET /v1/models` — lista el modelo configurado
- `GET /healthz` — healthcheck

Apunta cualquier cliente compatible con la API de OpenAI (SDK oficial, agentes de código, etc.) a esta URL como `base_url`.

## Configuración

Variables de entorno disponibles en `.env`:

| Variable | Descripción | Default |
|---|---|---|
| `UPSTREAM_BASE_URL` | URL base del modelo upstream | `https://api.deepseek.com` |
| `UPSTREAM_API_KEY` | API key del upstream | *(vacío)* |
| `UPSTREAM_MODEL` | Modelo a usar si el request no especifica uno | `deepseek-v4-flash` |
| `MAX_DECOMPOSITION_DEPTH` | Profundidad máxima del árbol de subtareas | `3` |
| `MAX_TOOL_ROUNDS_PER_PHASE` | Límite de rondas de `tool_calls` por fase | `25` |
| `PROXY_HOST` / `PROXY_PORT` | Dirección donde escucha el proxy | `127.0.0.1:8000` |
| `SESSION_TTL_SECONDS` | Tiempo de vida de una sesión pausada | `1800` |
| `MAX_SESSIONS` | Máximo de sesiones en memoria | `200` |
| `EXPOSE_REASONING_CONTENT` | Si se expone el proceso interno como `reasoning_content` | `true` |
| `EMBEDDINGS_BASE_URL` | Servidor OpenAI-compatible de embeddings (`/v1/embeddings`, p. ej. llama-server con `--embedding`). Vacío = búsqueda solo por keywords | *(vacío)* |
| `EMBEDDINGS_MODEL` | Nombre de modelo enviado al servidor de embeddings | `qwen3-embedding` |
| `EMBEDDINGS_TIMEOUT_SECONDS` | Timeout de cada llamada al embedder | `30` |
| `HYBRID_SEARCH` | Fusiona keywords (FTS5) + similitud coseno vía RRF en la recuperación de conocimiento | `true` |
| `HYBRID_CANDIDATES` | Cuántos candidatos toma cada vía antes de fusionarlos | `6` |
| `AUTO_LEARN_KNOWLEDGE` | Auto-aprendizaje: guardar hojas/síntesis exitosas en la knowledge base con dedupe | `true` |
| `ADMIN_TOKEN` | Token exigido en header `X-Admin-Token` para `/v1/knowledge*`. Vacío = confía en localhost | *(vacío)* |
| `SPECIALTY_ROUTING` | Activa el routing multi-modelo por especialidad (F1) | `false` |
| `VISION_MODEL` | Modelo para hojas de visión (solo si el turno trae imágenes). Vacío = modelo base | *(vacío)* |
| `CODE_MODEL` | Modelo para hojas de código/programación. Vacío = modelo base | *(vacío)* |
| `FAST_MODEL` | Modelo rápido para resúmenes/traducciones/listados. Vacío = modelo base | *(vacío)* |
| `SYNTHESIS_MODEL` | Modelo para la síntesis final. Vacío = modelo base | *(vacío)* |
| `UPSTREAM_MAX_RETRIES` | Reintentos de transporte ante error transitorio (timeout, conexión, 5xx, 429) | `2` |
| `UPSTREAM_RETRY_BACKOFF_SECONDS` | Espera base entre reintentos (backoff lineal) | `0.5` |
| `FALLBACK_MODEL` | Modelo de respaldo usado en los reintentos. Vacío = el mismo modelo | *(vacío)* |
| `PARALLEL_LEAVES` | Ejecuta en paralelo las hojas atómicas sin tools (`asyncio.gather`). Con tools vuelve a secuencial | `false` |
| `EMIT_PROGRESS_EVENTS` | Emite chunks SSE extra con campo `progress` (progreso del árbol) para clientes agénticos | `false` |
| `WEB_RESEARCH_BASE_URL` | URL del servicio Gigaxity Deep Research (F7). Vacío = investigación web desactivada | *(vacío)* |
| `WEB_RESEARCH_ENABLED` | Interruptor adicional de la investigación web (F7) | `true` |
| `WEB_RESEARCH_TIMEOUT_SECONDS` | Timeout (s) de la llamada al servicio de investigación | `90` |
| `WEB_RESEARCH_TOP_K` | Nº de fuentes que pide la investigación web | `8` |
| `WEB_RESEARCH_PRESET` | Preset de investigación (`fast`/`balanced`/`deep`) | `fast` |
| `WEB_RESEARCH_REASONING_EFFORT` | Esfuerzo de razonamiento de la síntesis (`low`/`medium`/`high`) | `medium` |
| `WEB_RESEARCH_AUTO_LEARN` | Auto-aprende la síntesis web en la KB (`source=web_research`) | `true` |
| `WEB_RESEARCH_MAX_CONCURRENCY` | Máximo de investigaciones web simultáneas | `2` |
| `UPSTREAM_RPM` | Tope de llamadas HTTP/min (ventana deslizante de 60s) compartido por TODAS las fases del proxy (descomposición, hojas, síntesis, reintentos F2 y passthrough F8). Pensado para free-tiers con tope por minuto (NVIDIA NIM ~45 RPM → `40`). El tope es de la cuenta del upstream, no de este proceso: si este proxy y Gigaxity apuntan a la misma cuenta, repartan (p. ej. `20`+`20`). `0` = desactivado | `0` |
| `PASSTHROUGH_MODELS` | Modelos (coma-separados) reenviados al upstream TAL CUAL — una sola llamada, sin descomposición/RAG/sesiones (carril `miura-fast`). Vacío = ninguno | *(vacío)* |

### Metadatos de la base de conocimiento (F5)

Cada entrada de la KB guarda ahora metadatos de procedencia y ciclo de vida:

| Campo | Significado |
|---|---|
| `source` | `manual` (POST admin), `auto_learn` (auto-aprendizaje del motor) |
| `updated_at` | última escritura de la entrada |
| `vector_updated_at` | cuándo se vectorizó por última vez (para saber si el vector está obsoleto) |
| `parent_id` | relación con otra entrada (grafo de conocimiento) |
| `version` | versión de la entrada (empieza en 1) |

Las bases creadas antes de F5 se **migran automáticamente** al abrirse (ALTER
TABLE idempotente; las filas existentes reciben los defaults). `GET
/v1/knowledge/stats` añade el desglose `by_source`.

### Endpoints de conocimiento (RAG)

Además del chat, el proxy expone administración de su base de conocimiento:

- `POST /v1/knowledge` — insertar `{description, content, category}` (vectoriza best-effort si hay embedder)
- `GET /v1/knowledge?q=...&limit=` — búsqueda híbrida; sin `q` lista lo reciente (con flag `has_vector`)
- `GET /v1/knowledge/stats` — total, desglose por categoría y cobertura vectorial
- `POST /v1/knowledge/backfill` — vectoriza entradas que quedaron sin embedding
- `DELETE /v1/knowledge/{id}` — poda quirúrgica (útil para limpiar auto-aprendizajes malos)
- `GET /v1/stats` — observabilidad (F6): contadores y latencias del motor + estado de la KB

También existe `backfill_embeddings.py` para vectorizar la KB desde consola:
`python backfill_embeddings.py` (con el servidor de embeddings arriba).

### Routing multi-modelo por especialidad (F1)

Por defecto el proxy usa **un único modelo** para todas las fases del turno. Con
`SPECIALTY_ROUTING=true` se convierte en un orquestador heterogéneo: cada **hoja
atómica** se clasifica por especialidad (heurística determinística de palabras
clave en [app/routing.py](app/routing.py)) y se envía al modelo más adecuado del
arsenal local:

| Especialidad | Se detecta cuando… | Modelo usado |
|---|---|---|
| `vision` | el turno trae imágenes **y** la tarea la referencia | `VISION_MODEL` |
| `code` | la tarea habla de código/programación | `CODE_MODEL` |
| `fast` | la tarea es resumen/traducción/listado breve | `FAST_MODEL` |
| `default` | cualquier otra | modelo base del turno |

Reglas importantes:

- La **descomposición (Fase 1)** nunca se rutea: planificar es la tarea más
  exigente y se queda siempre en el cerebro principal (modelo base).
- La **síntesis final** usa `SYNTHESIS_MODEL` si está definido, si no el base.
- Cualquier modelo de especialidad **vacío** cae al modelo base, así el sistema
  funciona igual con un solo modelo y mejora al añadir más.
- El routing respeta el `model` que envíe el cliente como **base del turno**;
  solo deriva hojas concretas a otros modelos.
- Requiere un upstream que sirva varios modelos (p. ej. `llama-server` en modo
  router con `--models-max >1`).

### Resiliencia: reintentos y fallback (F2)

El proxy no se cae ante fallos puntuales del upstream:

- **Retry de transporte** — ante un error transitorio (timeout, conexión,
  `5xx`, `429`) reintenta hasta `UPSTREAM_MAX_RETRIES` veces con backoff lineal.
  Los `4xx` no transitorios (auth, bad request, modelo no encontrado) **no** se
  reintentan: reintentar no los arregla. Cubre tanto llamadas de descomposición
  (no-streaming) como el arranque de los streams de ejecución/síntesis.
- **Modelo de respaldo** — si `FALLBACK_MODEL` está configurado, los reintentos
  (intento > 0) usan ese modelo en vez del original: si tu cerebro principal se
  satura, un modelo más ligero pero disponible puede sacar el turno adelante.
- **Reparación de JSON de descomposición** — si la Fase 1 devuelve algo que no es
  JSON válido, se hace un único reintento con un prompt de formato reforzado; si
  aun así falla, la tarea se trata como **atómica plana** (se ejecuta directa,
  sin descomponer) en vez de romper el turno.

### Ejecución paralela de hojas (F3)

Con `PARALLEL_LEAVES=true`, cuando una tarea se descompone en varias subtareas
**independientes** y no hay tools activas, las hojas atómicas se ejecutan en
paralelo con `asyncio.gather` en vez de una por una (speedup de 2-3x en tareas
con varias ramas sueltas). Detalles:

- Cada hoja paralela corre su propia llamada al upstream y su resultado se
  recoge en el orden original para que la síntesis sea determinista.
- El streaming token-a-token de cada hoja se sacrifica en modo paralelo (las
  hojas se bufferizan y se emite un evento de progreso al terminar cada una);
  la síntesis final sí sigue streameando.
- Si hay **tools activas** o una sola hoja, el motor vuelve automáticamente al
  modo secuencial (la pausa/reanudación de `tool_calls` es secuencial por
  construcción).
- Es opt-in y asume que las subtareas no dependen entre sí; si tu tarea es una
  cadena de pasos dependientes, déjalo desactivado.

### Streaming con progreso del árbol (F4)

Por defecto el proxy es opaco entre request y request. Con
`EMIT_PROGRESS_EVENTS=true`, el stream SSE emite chunks extra con un campo
`progress` (fuera del protocolo OpenAI estándar, por lo que los clientes
normales lo ignoran) para que los **clientes agénticos** muestren progreso real:

| Evento `progress.type` | Cuándo se emite |
|---|---|
| `phase_started` | arranca descomposición / ejecución / síntesis (con `phase`, `leaf_count`, `parallel`) |
| `phase_done` | termina la descomposición (con `leaf_count`) |
| `leaf_started` | arranca una hoja atómica (con `index`, `total`, `description`, `model`) |
| `leaf_done` | termina una hoja atómica (con `index`, `total`, `description`) |
| `done` | el turno completó (no se emite si queda pausado en `tool_calls`) |

Ejemplo de chunk: `{"object":"chat.completion.chunk","choices":[],"progress":{"type":"leaf_done","index":0,"total":2,...}}`.

### Observabilidad / métricas (F6)

El proxy lleva un registro **ligero y en memoria** (sin dependencias externas,
[app/metrics.py](app/metrics.py)) de lo que hace el motor en cada turno, expuesto
en `GET /v1/stats` (protegido por `X-Admin-Token` como el resto de endpoints
admin). El snapshot incluye:

- **Contadores** — hojas descompuestas (`leaves_decomposed`) y ejecutadas
  (`leaves_executed`), ejecuciones paralelas vs secuenciales
  (`parallel_executions` / `sequential_executions`), rondas y llamadas de tools
  (`tool_call_rounds` / `tool_calls`), consultas/aciertos/fallos de RAG
  (`rag_queries` / `rag_hits` / `rag_misses`) y de investigación web
  (`web_research_queries` / `web_research_hits` / `web_research_misses` /
  `web_research_errors`).
- **Latencias por fase** — `decomposition`, `leaf_execution` y `synthesis`, cada
  una con `count`, `total_s`, `avg_s` y `max_s`.
- **Estado de la KB** — el mismo desglose que `GET /v1/knowledge/stats`, bajo la
  clave `knowledge`.

Ejemplo: `{"uptime_s": 12.3, "counters": {"leaves_decomposed": 3, ...}, "latency": {"synthesis": {"count": 1, "avg_s": 0.42, ...}}, "knowledge": {...}}`.

Al ser acumuladores en memoria de un solo proceso, se reinician al reiniciar el
proxy; es intencionalmente simple (no Prometheus) porque el proxy es local.

### Investigación web de respaldo (F7)

Cuando la base de conocimiento local **no tiene respuesta** para una hoja
atómica (miss del RAG), el proxy puede llamar a un servicio acompañante
**Gigaxity Deep Research** ([app/web_research.py](app/web_research.py)) que
busca en la web (SearXNG/Tavily/LinkUp) y **sintetiza una respuesta con citas**
usando un modelo OpenAI-compatible (p. ej. NVIDIA NIM). La síntesis y sus
fuentes se inyectan en el contexto `{knowledge}` de la hoja, igual que una
solución previa de la KB.

- **Activación** — configura `WEB_RESEARCH_BASE_URL` (p. ej.
  `http://127.0.0.1:8090`). Mientras esté vacía, la feature queda desactivada y
  el miss se resuelve como siempre.
- **Degradación silenciosa** — servicio caído, timeout, error HTTP o respuesta
  vacía se traducen en "sin investigación web"; el flujo principal nunca se
  rompe ni se bloquea.
- **Auto-aprendizaje** — con `WEB_RESEARCH_AUTO_LEARN=true` la síntesis se
  guarda como entrada de la KB (`source=web_research`), de modo que la próxima
  consulta similar la resuelve el RAG local sin volver a la web.
- **Métricas** — `web_research_queries` / `web_research_hits` /
  `web_research_misses` / `web_research_errors` y latencia `web_research`,
  visibles en `GET /v1/stats`.

#### Puesta en marcha del servicio acompañante (Gigaxity)

La F7 consume por HTTP un servicio aparte, **Gigaxity Deep Research**
(repo [`Gigaxity/gigaxity-deep-research`](https://github.com/Gigaxity/gigaxity-deep-research)).
Pasos validados para levantarlo junto al proxy:

```bash
git clone https://github.com/Gigaxity/gigaxity-deep-research.git
cd gigaxity-deep-research
python -m venv .venv
# Windows: .venv\Scripts\activate  |  Linux/macOS: source .venv/bin/activate
pip install -e .
cp .env.example .env    # y rellena NVIDIA_NIM_API_KEY
python -m src.main      # FastAPI en http://127.0.0.1:8090
```

`.env` mínimo de Gigaxity (configuración con la que se validó):

```env
NVIDIA_NIM_API_KEY=<tu key de https://build.nvidia.com>
NVIDIA_NIM_MODEL=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
SEARXNG_BASE_URL=https://search.noemaai.com
SEARXNG_ENGINES=duckduckgo,bing,wikipedia
PORT=8090
```

Y en el `.env` de **atomic_ai**, activa la F7 apuntando a ese servicio:

```env
WEB_RESEARCH_BASE_URL=http://127.0.0.1:8090
```

#### Notas de la validación real

- **Modelo** — se usa `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (el más
  ligero/rápido de NIM para síntesis). El free-tier de NVIDIA NIM puede devolver
  `503 ResourceExhausted` en picos; la F7 degrada en silencio y se reintenta en
  el próximo miss.
- **Búsqueda** — la instancia pública `search.noemaai.com` responde bien por
  JSON; sus engines más fiables son `duckduckgo`, `bing` y `wikipedia`.
- **Latencia** — una síntesis con quality-gate sobre ~10 fuentes tarda ~30-70s
  en el free-tier; por eso `WEB_RESEARCH_TIMEOUT_SECONDS` viene en `90`.
- **Citas** — el modelo a veces cita con corchetes de ancho completo `【N】` que
  Gigaxity no parsea; `format_for_context` compensa cayendo a las `sources`
  brutas, así que el contexto nunca se pierde.
- **End-to-end** — validado en vivo: un miss del RAG local disparó la
  investigación web y el bloque con citas se inyectó en `{knowledge}`
  (`web_research_hits=1`, ~28s).

### Carril passthrough (F8) — `miura-fast`

Cuando el modelo pedido en la request es uno de los carriles configurados en
`PASSTHROUGH_MODELS` (p. ej. `miura-fast`), el proxy **reenvía la request al
upstream TAL CUAL**: una sola llamada HTTP, sin descomposición atómica, sin
RAG, sin sesiones y sin reescribir los mensajes del caller. Es el carril de
latencia mínima para chat directo.

- **Detección** — coincidencia exacta (insensible a mayúsculas) contra la
  lista coma-separada; cualquier otro modelo sigue por el carril orquestado.
- **Payload preservado** — `messages`, `tools`, `tool_choice`,
  `temperature` y `max_tokens` viajan sin tocar; la respuesta no-stream es
  el JSON completo del upstream (id/usage/choices) y el stream relaya los
  bytes SSE verbatim (mismo chunk-id y cadencia).
- **Presupuesto compartido** — las llamadas passthrough consumen el mismo
  `UPSTREAM_RPM` que el resto del proxy (ver `app/rate_limit.py`).
- **Visibilidad** — los carriles aparecen en `GET /v1/models` y en `GET /`
  (`passthrough_models`).

## Upstream en la practica: lane local vs. NVIDIA NIM

El upstream por defecto es **NVIDIA NIM free tier** (motor orquestado con
`deepseek-v4-flash` + carriles `miura-fast`/`miura-reasoner`). El lane de
generacion con llama.cpp local (`Qwen3.5-4B-EmperoAI-Qwen3.8`) quedo
descartado tras pruebas en vivo: consume todo el presupuesto de tokens en
`reasoning_content` y emite contenido vacio (con y sin streaming, con
`max_tokens` 2048 y 8192). La evidencia numerica completa y la configuracion
resultante viven en
[docs/LOCAL_LLAMACPP_FINDINGS.md](docs/LOCAL_LLAMACPP_FINDINGS.md). El
llama-server local sigue vigente como servidor de **embeddings**
(`EMBEDDINGS_BASE_URL`, bge-m3).

## Tests
## Tests

```bash
pytest
```

La suite cubre el motor de descomposición, el manejo de sesiones, el contenido multimodal, los schemas, un flujo end-to-end contra un upstream simulado (`tests/test_fake_upstream.py`), los endpoints admin de conocimiento (`tests/test_knowledge_admin.py`), la búsqueda híbrida semántica con embedder simulado (`tests/test_hybrid_semantic.py`), el routing multi-modelo por especialidad (`tests/test_routing.py`), la resiliencia de reintentos/fallback (`tests/test_resilience.py`), la ejecución paralela de hojas (`tests/test_parallel.py`), el streaming con progreso del árbol (`tests/test_progress.py`), los metadatos/grafo de la base de conocimiento (`tests/test_knowledge_metadata.py`), la observabilidad/métricas (`tests/test_metrics.py`), la investigación web de respaldo (`tests/test_web_research.py`), el limitador RPM del upstream (`tests/test_rate_limit.py`) y el carril passthrough (`tests/test_passthrough.py`).
