# HANDOFF.md — Traspaso integral del ecosistema MiuraCode (proxy atomic-ai + TUI `miura`)

> **Qué es este documento.** Registro completo, verificable y accionable de todo lo que se buscó construir, lo que efectivamente se hizo (con evidencia: commits, medidas en vivo, procesos corriendo), el estado exacto del sistema al cierre del hito y el camino para mejorarlo. Escrito para dos audiencias a la vez: (a) un ingeniero senior de primer nivel (Microsoft/Google/Amazon/xAI/OpenAI/Anthropic) que retome el proyecto con **cero contexto previo**, y (b) otro agente de IA (Claude Code, ChatGPT/OpenCode, etc.) que continúe desde aquí sin preguntar nada.
>
> **Snapshot:** 2026-10-09 · **Rama:** `miuracode` (synced con origin) · **Trabajo realizado por:** usuario (propietario/dirección) + Cline (agente de código, backend/infra).
> **Regla de mantenimiento:** este archivo se versiona en la raíz del monorepo y se actualiza al cerrar cada hito. No existe fuente de verdad más completa que este documento.

---

## 0. Executive TL;DR (English)

**One-liner:** a self-hosted, ~$0-cost AI stack for a content-creation ecosystem: a fork of Roo Code ("MiuraCode", VS Code extension) + a Python **Atomic Decomposition Proxy** (`services/atomic-ai`) that front-runs any OpenAI-compatible LLM upstream by decomposing every instruction into an atomic task tree (plan → execute leaves → synthesize), + a persistent chat TUI (`apps/miura`).

- **Live repo:** `D:\YT\Miura_Swarm_Ecosistema_de_Contenido\SSinsta\MiuraCode\miuracode` — branch `miuracode`, `origin = github.com/miura-wolf/MiuraCode` (synced), `upstream = RooCodeInc/Roo-Code`.
- **Latest milestone (pushed):** NVIDIA NIM free-tier upstream pivot + evidence doc (`1655ef125`), persistent TUI `apps/miura` — 21 files, 1519 insertions, SQLite+FTS5, zero native deps (`dfcebc6ce`), security chore for web-evals `.env` (`353241cb5`).
- **Runtime at snapshot:** proxy up on `127.0.0.1:8120` serving 3 lanes (`miura-fast`→`openai/gpt-oss-20b`, `miura-reasoner`→`moonshotai/kimi-k3`, orchestrated→`deepseek-v4-flash`); llama-server idle on `:8080` (generation lane discarded, kept for experiments); embeddings server on `:8081` **DOWN** (only affects hybrid semantic search, FTS5 still works).
- **Key technical finding:** local generation with the heretic Qwen merge (`Qwen3.5-4B-EmperoAI-Qwen3.8`) is **unusable** — it burns the entire token budget in `reasoning_content` and emits empty `content` (measured, 3/3 tests, 147–367 s). Full evidence in `services/atomic-ai/docs/LOCAL_LLAMACPP_FINDINGS.md` (§4.2 here).
- **Run in 60s:** double-click `miura.bat` at the repo root (starts the proxy in a second window if `:8120` is down, waits 8s, opens the TUI). Full runbook: §6.
- **Do NOT work in** `D:\YT\...\SSinsta\atomic_ai-main\atomic_ai-main` — that is the pre-fork ZIP copy (historical artifact, no git, missing F1/F6/F7/F8.1 modules). All live code is in the monorepo.

---

## 1. Contexto y visión — ¿qué se buscaba construir?

El proyecto vive dentro de la estructura de trabajo de un **ecosistema de creación de contenido** (`D:\YT\Miura_Swarm_Ecosistema_de_Contenido\...`). La necesidad de fondo: operar un asistente de desarrollo/contenido **gratuito, auto-hospedado y sin depender de suscripciones de IA de pago**, con persistencia propia y capacidades de investigación web.

La construcción se articuló en tres capas:

1. **MiuraCode (extensión VS Code)** — fork comunitario de Roo Code (`RooCodeInc/Roo-Code`) rebrandeado a `miura-wolf/MiuraCode` (_"Your AI-Powered Dev Team, Right in Your Editor"_). Es el producto final orientado al editor.
2. **atomic-ai (el "cerebro" backend)** — proxy HTTP OpenAI-compatible (`/v1/chat/completions`) que se interpone delante de cualquier LLM upstream y **descompone cada instrucción en un árbol de subtareas atómicas**, resuelve cada hoja por separado y sintetiza la respuesta final. Tesis de diseño: los modelos pequeños/baratos fallan en tareas compuestas porque intentan resolver todo de un tirón; forzar planificar→ejecutar→sintetizar hace cada paso lo bastante simple como para resolverse bien. Procede del proyecto open-source `Nichonauta/atomic_ai` (videos de teoría+demo en `services/atomic-ai/README.md`), fork-eado y potenciado (F1–F8, ver §4.1).
3. **`miura` (TUI de chat)** — interfaz de terminal persistente (sesiones SQLite + memoria entre sesiones + búsqueda FTS5) para usar el proxy sin abrir el editor. **Cero dependencias nativas** (`node:sqlite` + Ink + commander).

Servicio acompañante: **Gigaxity Deep Research** (`services/gigaxity`, :8090) — cuando el RAG local del proxy falla (miss), el proxy le pide investigar en la web (SearXNG/Tavily/LinkUp/ddgs) y sintetizar con citas usando NIM; el resultado se auto-aprende como entrada de la KB (`source=web_research`).

**Objetivo estratégico del hito cerrado (2026-10-09):** llevar el proxy a un upstream cloud gratuito usable en la práctica (pivot desde llama.cpp local, con evidencia numérica), construir el TUI persistente, documentar los hallazgos, dejarlo todo commiteado/pusheado y con un launcher de doble clic para uso diario por un usuario no-terminal.

## 2. Mapa del territorio — repos, directorios y rutas

### 2.1 Repositorio vivo (TODO el trabajo va aquí)

| Ruta                                                                    | Qué es                                                                                                                                                              |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `D:\YT\Miura_Swarm_Ecosistema_de_Contenido\SSinsta\MiuraCode\miuracode` | **Monorepo vivo.** Rama `miuracode`, remotes: `origin` = `https://github.com/miura-wolf/MiuraCode.git` · `upstream` = `https://github.com/RooCodeInc/Roo-Code.git`. |
| `services\atomic-ai\`                                                   | El proxy Python (FastAPI/uvicorn). App en `app\` (16 módulos + `app\prompts\`), tests en `tests\` (20 archivos). Ver §4.1.                                          |
| `services\gigaxity\`                                                    | Deep research companion (subtree, 919 tests). Puerto 8090.                                                                                                          |
| `apps\miura\`                                                           | El TUI (Node ≥23.4). 21 archivos, 3 suites de test (15 tests). Ver §4.3.                                                                                            |
| `apps\cli\`, `src\`, `webview-ui\`, `packages\`                         | La extensión MiuraCode (fork Roo Code) + sus packages.                                                                                                              |
| `scripts\stack.ps1`                                                     | Levanta/tumba el stack de servicios (gigaxity :8090 + atomic-ai :8120).                                                                                             |
| `miura.bat`                                                             | Launcher de doble clic del TUI (proxy-check + arranque). Ver §4.4.                                                                                                  |
| `ROADMAP.md` (raíz)                                                     | Lista única de pendientes del ecosistema.                                                                                                                           |
| `services\atomic-ai\ROADMAP.md`                                         | Historial técnico de features F1–F8 del proxy.                                                                                                                      |
| `services\atomic-ai\docs\LOCAL_LLAMACPP_FINDINGS.md`                    | Evidencia del pivot local→NIM (§4.2).                                                                                                                               |
| `HANDOFF.md` (este archivo)                                             | Fuente de verdad integral.                                                                                                                                          |

### 2.2 Copia standalone (NO trabajar aquí)

`D:\YT\Miura_Swarm_Ecosistema_de_Contenido\SSinsta\atomic_ai-main\atomic_ai-main` — el **ZIP original de `Nichonauta/atomic_ai`** donde se empezó a experimentar. Sin `.git`. Su `app\` **no contiene** `routing.py`, `metrics.py`, `web_research.py`, `rate_limit.py` (las F1/F6/F7/F8.1 viven solo en el monorepo). Su `.env` sigue apuntando al lane local pre-pivot (`http://127.0.0.1:8080`, `Qwen3.5-4B`). Conservar únicamente como artefacto histórico/forense.

### 2.3 Datos y runtime del usuario (Windows)

| Ruta                                                    | Contenido                                                                                                                                                                                                             |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `C:\Users\AnZa07\.miuracode\`                           | `miura.db` (sesiones/mensajes/memoria del TUI, SQLite WAL) + `settings.json` (`proxyUrl`, `model`, `systemPrompt`). Overrides por entorno: `MIURA_PROXY_URL`, `MIURA_MODEL`, `MIURA_CONFIG_DIR` (sandbox para tests). |
| `services\atomic-ai\.env`                               | Config real del proxy (**NO versionar, contiene API key de NIM**). Plantilla: `.env.example`.                                                                                                                         |
| `services\atomic-ai\atomic_ai.db`                       | KB del proxy (conocimiento + sesiones, migración automática de schema).                                                                                                                                               |
| `D:\IA\GGUF\gguf\llama_cpp.bat` · `llama_embedding.bat` | Scripts del usuario para levantar llama-server (router b10630) y el embedder bge-m3 (:8081).                                                                                                                          |
| `C:\Models_llama.cpp\beellama-vulkan\llama-server.exe`  | Binario llama.cpp (Vulkan, Intel Arc) corriendo hoy en :8080.                                                                                                                                                         |

## 3. Cronología verificada (git log de la rama `miuracode`)

Historial reciente (de nuevo a antiguo), con la lectura de cada commit:

| Commit                                                    | Qué hizo / por qué importa                                                                                                                                                                                                                                                 |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dfcebc6ce` feat(miura): TUI de chat persistente          | **Hito F4-TUI.** 21 archivos, +1519 líneas: `apps/miura` completo (index, client, config, store, memory, sessions, App/SessionView, commands, theme, tests, tsup/vitest/eslint configs, fix-sqlite.mjs) + pnpm-lock. Cero dependencias nativas.                            |
| `1655ef125` feat(atomic-ai): pivot upstream a NIM         | **Hito de infraestructura.** `.env.example` reescrito (NIM, `PASSTHROUGH_MODELS` con mapeo carril=modelo, `UPSTREAM_RPM=20`, timeout 180) + `docs/LOCAL_LLAMACPP_FINDINGS.md` (evidencia numérica T5/T6/T7 y NIM) + sección "Upstream en la practica" en README del proxy. |
| `353241cb5` chore(security): web-evals `.env`             | Sacó el `.env` real de `apps/web-evals` del versionado; renombrado a `.env.sample`. Higiene de secretos.                                                                                                                                                                   |
| `a9c4a13c0` chore: cierre de branding                     | Root `name` a `miuracode`, README vsix name, eliminó `progress.txt` obsoleto.                                                                                                                                                                                              |
| `d27ff1c4f` Rebrand final sweep                           | vscode-lm permission justification, bedrock userAgents, embedder HTTP-Referer a MiuraCode. **152/152 tests verdes.**                                                                                                                                                       |
| `0d90f7fd2` Rebrand F2                                    | Logo wolf (welcome/activitybar/marketplace), i18n+nls 18 locales, strings UI. Tests verdes.                                                                                                                                                                                |
| `ad20ecc24` Fix: omitir Authorization cuando no hay key   | Necesario para llama-server local sin `--api-key`.                                                                                                                                                                                                                         |
| `cc2a156af` F8: mapeo carril=modelo en PASSTHROUGH_MODELS | Habilita alias tipo `miura-fast=openai/gpt-oss-20b` cuando el upstream no conoce el alias.                                                                                                                                                                                 |
| `c653c19e7`, `8e7eba638` F8: passthrough + rate limit     | Carril `miura-fast` + `UPSTREAM_RPM` en atomic-ai aplicado al chat.                                                                                                                                                                                                        |
| `916e55ad0`…`b0c5033ac` subtree pulls gigaxity            | Absorción de Gigaxity Deep Research como subtree (ddgs keyless, NIM RPM limiter, test isolation).                                                                                                                                                                          |
| `bedf81bb9` docs: ROADMAP monorepo                        | Lista única de pendientes del ecosistema.                                                                                                                                                                                                                                  |
| `51bdc21c6` feat: monorepo MiuraCode                      | **El gran paso de estructura:** servicios atomic-ai + gigaxity absorbidos bajo `services/` + `scripts/stack.ps1`.                                                                                                                                                          |
| `d05fb5129` feat: providers atomic-ai + poolside          | La extensión Roo/Miura aprende a hablar con el proxy local 8120 (provider atomic-ai).                                                                                                                                                                                      |
| `84e932ea2` feat: dieta lean round 1                      | 2 modos, tools sin codebase_search/generate_image, identidad MiuraCode en prompts.                                                                                                                                                                                         |
| `40b61525f` feat: rebrand Roo Code → MiuraCode            | Identidad, nls, i18n, refs de build. Punto de partida de la rama.                                                                                                                                                                                                          |

> **Cómo llegó el ZIP aquí:** `atomic_ai` (Nichonauta) se descargó como ZIP y se experimentó en la copia standalone; luego se hizo el plan de fork documentado en `services/atomic-ai/ROADMAP.md` (clonar repo oficial → rama de trabajo → copiar cambios → commits atómicos por feature), que derivó en la absorción como subtree en el monorepo (`0b1c23830 Add 'services/atomic-ai/'`). El monorepo unifica: extensión + proxy + deep research.

**Anécdota de proceso (lección para el que continúe):** durante el hito del TUI, un `git add apps/miura` ejecutado en paralelo a un commit absorbió 24 archivos en el commit equivocado. Se resolvió con `git reset --soft HEAD~1`, unstaging total y re-commit secuencial. Moraleja: **no paralelicizar `git add` + `git commit` en este repo**; los hooks husky (pre-push check-types) son estrictos (15/15 pasando).

## 3.1 Hitos con validación en vivo (fecha 2026-10-09)

- **Proxy contra NIM real:** `GET http://127.0.0.1:8120/v1/models` responde `deepseek-ai/deepseek-v4-flash-0731`, `miura-fast`, `miura-reasoner` (verificado al cierre; proceso `python.exe` PID 43604 en :8120).
- **TUI contra proxy real:** subcomandos no interactivos `config`, `models`, `sessions`, `search` ejecutan con exit 0.
- **Launcher `miura.bat`:** probado end-to-end (arranque con proxy caído → lo levanta en ventana secundaria → espera 8 s → abre TUI).
- **Passthrough streaming:** `miura-fast` vía proxy respondió contenido real (176 chars) en ~5 s streaming.
- **Números de latencia medidos** (detalle en §4.2): deepseek-v4-flash JSON ~4 s (carril orquestado); gpt-oss-20b 5–19 s pero errático (3/6 timeouts); kimi-k3 estable ~59 s; heretic local 147–367 s con contenido **vacío** (descartado).

## 4. Arquitectura de lo construido — qué es cada pieza y cómo funciona

### 4.1 `services/atomic-ai` — Atomic Decomposition Proxy (el corazón)

**Qué hace:** cada turno de usuario que llega a `POST /v1/chat/completions` pasa por tres fases orquestadas por `AtomicDecompositionEngine` (`app/engine.py`):

1. **Descomposición** — el modelo decide si la instrucción es atómica o conviene dividirla en subtareas ordenadas; se aplica recursivamente hasta `MAX_DECOMPOSITION_DEPTH`. Construye un árbol de tareas.
2. **Ejecución de hojas atómicas** — cada hoja se resuelve en su propia llamada al modelo con el resultado de las anteriores como contexto acumulado; hojas independientes van en paralelo (`asyncio.gather`, F3) salvo que haya tools. Si el modelo pide `tool_calls`, la ejecución se pausa y el `tool_calls` se devuelve al cliente (protocolo OpenAI); el estado se recuerda entre requests (F‑sesiones).
3. **Síntesis final** — con todos los resultados atómicos, se genera la respuesta visible; el resto del proceso se expone como `reasoning_content` (configurable `EXPOSE_REASONING_CONTENT`).

**Comportamiento del motor durante el streaming:** cada evento relevante se emite como `progress` SSE opt-in (F4) para clientes agénticos.

**Módulos de `app/`** (16): `engine.py` (orquestación), `upstream.py` (cliente HTTP + resiliencia F2), `routing.py` (F1, modelo por especialidad), `session.py` (pausa/reanudación por hash encadenado, TTL), `knowledge.py`+`db.py`+`embeddings.py` (RAG híbrido FTS5 ∪ coseno), `web_research.py` (F7, fallback web vía Gigaxity), `metrics.py` (F6, `GET /v1/stats`), `rate_limit.py` (F8.1, ventana deslizante RPM), `content.py` (multimodal), `schemas.py`, `sse.py`, `main.py` (FastAPI), `config.py`, `prompts/` (criterios de atomicidad, tool-existence sin ejecución, anti prompt-injection).

**Tabla de features F1–F8** (estado: todas ✅ implementadas y testeadas; 152/152):

| Feature                      | Qué aporta                                                                                                       | Módulo                   | Tests                        |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------ | ---------------------------- |
| F1 routing                   | Cada hoja atómica va al modelo visión/código/rápido adecuado                                                     | `routing.py`             | `test_routing.py`            |
| F2 resiliencia               | Retries transitorios, `FALLBACK_MODEL`, reparación de JSON de descomposición                                     | `upstream.py`            | `test_resilience.py`         |
| F3 paralelo                  | Hojas independientes en `asyncio.gather`, fallback secuencial con tools                                          | `engine.py`              | `test_parallel.py`           |
| F4 streaming progreso        | Eventos `progress` SSE opt-in                                                                                    | `sse.py`                 | `test_progress.py`           |
| F5 KB metadata/grafo         | `source`, `updated_at`, `parent_id`, `version` + migración automática                                            | `db.py`                  | `test_knowledge_metadata.py` |
| F6 observabilidad            | Contadores/latencias por fase en `GET /v1/stats`                                                                 | `metrics.py`             | `test_metrics.py`            |
| F7 web research              | Miss del RAG → Gigaxity Deep Research → síntesis con citas → auto-aprendizaje (`source=web_research`)            | `web_research.py`        | `test_web_research.py`       |
| F7.1 carriles búsqueda       | Tavily/LinkUp (keyed), Exa/SerpAPI (keyed, pendientes de keys), ddgs keyless                                     | gigaxity                 | —                            |
| F7.2 rate limit NIM research | `RESEARCH_LLM_RPM` ventana deslizante                                                                            | gigaxity `llm_client.py` | 15 tests                     |
| F8.1 rate limit upstream     | `UPSTREAM_RPM` compartido por todos los carriles (chat incluido), cada intento HTTP gasta                        | `rate_limit.py`          | `test_rate_limit.py`         |
| F8 passthrough               | `PASSTHROUGH_MODELS` (alias `carril=modelo`): reenvío TAL CUAL, 1 llamada, sin decomp/RAG/sesiones, SSE verbatim | `main.py`                | `test_passthrough.py`        |

**Configuración en producción local** (`services/atomic-ai/.env`, valores reales sin el secreto):

```
UPSTREAM_BASE_URL=https://integrate.api.nvidia.com     # SIN sufijo /v1 (el proxy añade /v1/chat/completions)
UPSTREAM_MODEL=deepseek-ai/deepseek-v4-flash-0731      # carril orquestado (JSON ~4s)
FALLBACK_MODEL=moonshotai/kimi-k3                      # cubre timeouts erráticos de gpt-oss
PASSTHROUGH_MODELS=miura-fast=openai/gpt-oss-20b,miura-reasoner=moonshotai/kimi-k3
PROXY_PORT=8120 · UPSTREAM_RPM=20 · REQUEST_TIMEOUT_SECONDS=180
EMBEDDINGS_BASE_URL=http://127.0.0.1:8081 · WEB_RESEARCH_BASE_URL=http://127.0.0.1:8090 · WEB_RESEARCH_ENABLED=true
```

### 4.2 El hallazgo crítico — por qué el lane local quedó descartado (y el pivot a NIM)

Doc fuente: `services/atomic-ai/docs/LOCAL_LLAMACPP_FINDINGS.md` (mediciones directas 2026-10-09). Resumen ejecutivo:

- **Heretic local `Qwen3.5-4B-EmperoAI-Qwen3.8`** (llama-server :8080): en T5/T6/T7 (prompt código, "Hola", streaming y no, `max_tokens` 2048 y 8192) **siempre** los mismos 833 tokens de razonamiento, `finish_reason=length` y `content` **vacío** en 147–367 s. Subir max_tokens no ayuda (solo alarga el bucle). No es bug de llama.cpp ni del proxy: es el patrón del merge herético. **Descartado como generador.**
- **`deepseek-v4-flash`** (NIM free): **razonador puro** — excelente para el carril orquestado (JSON `response_format` en ~4 s) pero inútil en chat directo (consume el presupuesto en razonamiento, content vacío). Por eso `miura-fast` remapea a `gpt-oss-20b`.
- **`gpt-oss-20b`** (NIM free): contenido real en 5–19 s pero **errático** (3/6 llamadas en timeout en free tier) → necesita fallback.
- **`kimi-k3`** (NIM free): el más consistente del tier gratis (~59 s, siempre contenido) → `FALLBACK_MODEL` + carril `miura-reasoner`.
- **Regla de oro descubierta:** `UPSTREAM_BASE_URL` **sin** sufijo `/v1` — el proxy ya añade `/v1/chat/completions`; un `/v1` duplicado producía 404 en streaming.
- **Rate limit de cuenta:** NIM free-tier rechaza ráfagas ~45 RPM con `503 ResourceExhausted`; como proxy y Gigaxity comparten cuenta NIM, se reparte `UPSTREAM_RPM=20` + `RESEARCH_LLM_RPM=20`.
- **Qué queda del stack local:** llama-server sigue vigente como servidor de **embeddings** (`bge-m3` :8081, `EMBEDDINGS_BASE_URL`) — el defecto es del generador, no del servidor. Para reactivar generación local algún día: cargar un modelo sin bucle de razonamiento, pasar la batería T5/T6/T7 (exigiendo `content_len > 0`) y devolver `UPSTREAM_BASE_URL` a `http://127.0.0.1:8080`.

### 4.3 `apps/miura` — el TUI de chat persistente (`@miuracode/cli` v0.1.0)

**Qué es:** terminal-UI (Ink + React 19) sobre el proxy 8120. Requisito: **Node ≥ 23.4** (`node:sqlite` estable sin flag; verificado en 24.19.0). Bin: `miura` (`bin: { "miura": "dist/index.js" }`). Deps runtime: solo `commander`, `ink`, `react` — cero nativas.

**Estructura** (21 archivos, commit `dfcebc6ce`):

- `src/index.ts` — CLI commander: opciones `-c/--continue-chat`, `-r/--resume <uuid|prefijo>`, `-m/--model <carril>`; subcomandos no interactivos `sessions`, `search <texto>`, `models`, `config`.
- `src/lib/client.ts` — cliente HTTP del proxy: chat (streaming SSE + no-stream), `listModels`.
- `src/lib/config.ts` — settings `~/.miuracode/settings.json` (`proxyUrl`, `model`, `systemPrompt`); overrides de entorno `MIURA_PROXY_URL` / `MIURA_MODEL` / `MIURA_CONFIG_DIR`.
- `src/lib/store.ts` — `Store` sobre `node:sqlite`: tablas `sessions`, `messages` (con `reasoning`), `memory`; índices **FTS5 external-content** con triggers de sincronización; frase FTS segura (`ftsPhrase` quotea la query).
- `src/lib/memory.ts` — `MemoryStore`: hechos `clave=valor` (upsert por key, FTS5 search con snippet). Se inyecta como bloque `system` en cada turno, encima de la historia (últimos 40 mensajes) — patrón "Engram-lite" propio, cero embeddings.
- `src/lib/sessions.ts` — helpers de sesión (resolve prefijo UUID, latest).
- `src/ui/App.tsx` + `SessionView.tsx` — la TUI: flechas ↑/↓ recorren el historial de input; Ctrl+C con texto pendiente limpia la línea; selector (picker) de sesiones/búsqueda/memoria; aviso en pantalla si un modelo "responde" razonamiento sin contenido.
- `src/ui/commands.ts` — comandos slash: `/help /exit /new /model <nombre> /title <texto> /search <texto> /memory /remember clave=valor /forget clave /sessions`.
- `scripts/fix-sqlite.mjs` — parche del workspace para `node:sqlite`.
- Tests (vitest, 15): `store.test.ts`, `commands.test.ts`, `sessions.test.ts`. Comandos: `pnpm --filter @miuracode/cli dev|build|test|check-types`.

**Flujo de datos de un turno:** input → `SessionView` → `client.chat()` (POST `:8120/v1/chat/completions`, `stream:true`) → SSE chunks (`content` a pantalla, `reasoning_content` colapsable) → persist en `messages` (+`reasoning`) → FTS index vía trigger. Memoria: bloque `system` con hechos + `settings.systemPrompt` + últimos 40 mensajes.

### 4.4 `miura.bat` — launcher de doble clic (raíz del monorepo)

```bat
curl -s -o nul -m 3 http://127.0.0.1:8120/v1/models    REM probe del proxy
if errorlevel 1 ( start "atomic-ai proxy" cmd /k "services\atomic-ai\run.bat" & timeout 8 )
node "apps\miura\dist\index.js" %*                     REM TUI o subcomandos
if errorlevel 1 pause
```

Doble clic → TUI; si el proxy está caído lo levanta en segunda ventana (espera 8 s) y pasa argumentos (`miura.bat models`). **Estado git: untracked** — pendiente de commit (§7, chore).

### 4.5 `services/gigaxity` — Deep Research companion (:8090)

`POST /api/v1/research` → busca en la web (carriles Tavily/LinkUp activos con keys; Exa/SerpAPI cableados pendientes de keys; **ddgs keyless** funciona hoy; SearXNG reserva `search.noemaai.com`) → sintetiza con NIM (quality-gate sobre ~10 fuentes) → devuelve síntesis + fuentes. Consumido por `atomic-ai` como F7. Detalle y despliegue: `services/gigaxity/README.md` y `docs/` propios.

## 5. Estado del sistema al cierre del hito (2026-10-09, verificado en vivo)

| Pieza                  | Estado                                                                                                           | Evidencia                           |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| Git                    | `miuracode` synced con origin; árbol limpio salvo `miura.bat` (untracked) y este HANDOFF                         | `git status -sb`                    |
| Proxy atomic-ai        | **ARRIBA** :8120 (python.exe PID 43604)                                                                          | `GET /v1/models` → 3 carriles       |
| llama-server (heretic) | ARRIBA :8080 (llama-server.exe PID 38772, Vulkan/Intel Arc) — **generación descartada**; queda para experimentos | `Get-NetTCPConnection`              |
| Embedder bge-m3        | **CAÍDO** :8081 — solo afecta búsqueda semántica híbrida (`/v1/embeddings`); FTS5 sigue                          | nada escuchando en 8081             |
| Gigaxity :8090         | No levantado en la sesión de cierre (deploy vía `scripts/stack.ps1` o su propio run)                             | —                                   |
| TUI `miura`            | Built (`dist/` OK); subcomandos exit-0 contra proxy real                                                         | `miura.bat models`                  |
| Tests proxy            | 152/152 pytest                                                                                                   | commit `d27ff1c4f`                  |
| Tests TUI              | 15 vitest (3 suites)                                                                                             | `pnpm --filter @miuracode/cli test` |
| API key NIM            | Válida en `services/atomic-ai/.env` (secreto, no versionado)                                                     | proxy responde                      |

**Topología runtime** (todo localhost): `TUI miura :? → proxy atomic-ai :8120 → [NIM cloud | gigaxity :8090 → buscadores + NIM]`; embedder `:8081` (opcional) y llama-server `:8080` (reserva).

## 6. Runbook — cómo ejecutar, probar y verificar todo (desde cero)

### 6.1 Prerrequisitos

- **Windows** (scripts `.bat`/`.ps1` actuales; todo lo demás es portable). Usuario: `AnZa07`.
- **Node ≥ 23.4** (por `node:sqlite`; verificado en 24.19.0) + **pnpm** (workspace).
- **Python 3.12** (proxy en `C:\Users\AnZa07\AppData\Local\Programs\Python\Python312\python.exe`), venv propio en `services\atomic-ai\.venv`.
- **API key de NVIDIA NIM** (gratuita en `build.nvidia.com`) en `services\atomic-ai\.env` como `UPSTREAM_API_KEY`. **Regla de seguridad inquebrantable:** el usuario pega la key él mismo en el archivo; ningún agente debe escribirla.
- llama.cpp (opcional hoy): `D:\IA\GGUF\gguf\llama_cpp.bat` (router b10630, :8080) y `llama_embedding.bat` (bge-m3, :8081).

### 6.2 Arranque completo (del más simple al más granular)

**A. Vía launcher (usuario final):** doble clic en `miura.bat` (raíz del repo) → si :8120 no responde, abre segunda ventana con el proxy (espera 8 s) → TUI. Subcomandos: `miura.bat models|sessions|config|search <texto>`.

**B. Vía manual:**

```powershell
cd D:\YT\Miura_Swarm_Ecosistema_de_Contenido\SSinsta\MiuraCode\miuracode

# 1) Proxy (ventana 1) — usa el .env del directorio
services\atomic-ai\run.bat          # o: .venv\Scripts\activate; uvicorn app.main:app --port 8120

# 2) (Opcional) Embedder semántico (ventana 2) — solo si se quiere RAG híbrido
D:\IA\GGUF\gguf\llama_embedding.bat  # bge-m3 en :8081

# 3) (Opcional) Gigaxity (ventana 3) — solo si se quiere F7 web-research
scripts\stack.ps1                    # levanta gigaxity :8090 + atomic-ai :8120

# 4) TUI (ventana 4)
pnpm --filter @miuracode/cli dev     # directo con tsx (o: node apps\miura\dist\index.js tras build)
```

### 6.3 Verificación (smoke tests de 60 segundos)

```powershell
# Proxy vivo y carriles
curl http://127.0.0.1:8120/v1/models          # → deepseek-v4-flash, miura-fast, miura-reasoner

# Chat passthrough de humo (streaming)
curl -N http://127.0.0.1:8120/v1/chat/completions -H "Content-Type: application/json" `
  -d '{\"model\":\"miura-fast\",\"messages\":[{\"role\":\"user\",\"content\":\"hola\"}]}'

# Carril orquestado (pasa por descomposición→hojas→síntesis)
curl http://127.0.0.1:8120/v1/chat/completions -H "Content-Type: application/json" `
  -d '{\"model\":\"deepseek-ai/deepseek-v4-flash-0731\",\"messages\":[{\"role\":\"user\",\"content\":\"explica en 2 frases qué es FTS5\"}]}'

# TUI: subcomandos no interactivos
miura.bat models ; miura.bat sessions ; miura.bat config
```

> Nota Windows/curl: en PowerShell conviene `curl.exe` o Invoke-WebRequest; el alias `curl` de PS puede reescribir los flags. Los `-d` JSON van escapados como arriba.

### 6.4 Tests y calidad

```powershell
# Proxy (152 tests)
cd services\atomic-ai ; .venv\Scripts\python -m pytest
# TUI (15 tests) + tipos
pnpm --filter @miuracode/cli test ; pnpm --filter @miuracode/cli check-types
# Extensión completa (husky pre-push corre check-types en todo el workspace)
pnpm build    # build completo del monorepo (turbo)
```

### 6.5 Solución de problemas conocida

| Síntoma                                             | Causa                                              | Fix                                                                                                    |
| --------------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| 404 en streaming tras cambiar upstream              | `UPSTREAM_BASE_URL` con `/v1` duplicado            | quitar el sufijo `/v1` (el proxy ya lo añade)                                                          |
| 503 `ResourceExhausted` en ráfagas                  | free-tier NIM ~45 RPM compartido con Gigaxity      | mantener `UPSTREAM_RPM=20` + `RESEARCH_LLM_RPM=20`                                                     |
| Chat directo "responde" vacío pero con razonamiento | modelo razonador puro (deepseek-v4-flash, heretic) | usar carril `miura-fast`/`miura-reasoner` (remapeados a gpt-oss/kimi); TUI ya avisa                    |
| `miura` no arranca por `node:sqlite`                | Node < 23.4                                        | actualizar Node (o usar `scripts/fix-sqlite.mjs` del paquete si el workspace lo pide)                  |
| Timeout del chat passthrough                        | gpt-oss-20b errático en free tier                  | F2 reintentará y caerá a `FALLBACK_MODEL=kimi-k3`; en última instancia subir `REQUEST_TIMEOUT_SECONDS` |
| Búsqueda semántica falla / embeddings timeout       | embedder :8081 caído                               | levantar `llama_embedding.bat`; mientras tanto FTS5 keywords funciona igual (degradación diseñada)     |
| `miura.db` corrupta/locked (WAL)                    | cierre abrupto                                     | cerrar procesos node; SQLite WAL se auto-recupera; backup copiando el archivo                          |

### 6.6 Sandbox / entornos aislados

- TUI: `MIURA_CONFIG_DIR` (dir de `miura.db`+`settings.json`), `MIURA_PROXY_URL`, `MIURA_MODEL`.
- Proxy: todo por `services\atomic-ai\.env` (copiar de `.env.example`). Un `MIURA_CONFIG_DIR` residual de un smoke test anterior **ya fue limpiado** — no debería existir como variable de usuario persistente.

## 7. Roadmap — qué se puede hacer para mejorarlo (priorizado, con recetas)

### P0 — Mantenimiento inmediato (minutos)

1. **Commit + push de `miura.bat` y `HANDOFF.md`** (chore): ambos pendientes de versionar al cierre de este documento. También actualizar ROADMAP raíz con el hito TUI.
2. **Levantar embedder :8081** (`D:\IA\GGUF\gguf\llama_embedding.bat`) si se quiere búsqueda semántica en el RAG del proxy (hoy FTS5-only).
3. **Estandarizar el arranque de gigaxity** (hoy vía `scripts/stack.ps1`; no estaba corriendo al cierre): opcional integrarlo en `miura.bat` como tercera ventana condicional (:8090 down → subir).

### P1 — Corto plazo (días): robustez y UX

4. **Redundancia de upstream (triangulación de gratis):** añadir un segundo upstream libre como respaldo del free-tier de NIM. Cualquier proveedor OpenAI-compatible se integra con **cambio solo en `.env`** (`UPSTREAM_BASE_URL` sin `/v1` + `UPSTREAM_API_KEY` + `PASSTHROUGH_MODELS` con mapeo `carril=modelo`); el carril passthrough requiere cero código. Candidatos a evaluar por relación generosidad/latencia: OpenRouter (free ≈50 req/día), Groq, Google AI Studio (Gemini free), Cerebras.
5. **Carriles en `packages/types` de la extensión:** ya existe `miura-fast`; añadir `miura-reasoner` y `deepseek-v4-flash` a los modelos expuestos por el provider atomic-ai de la extensión para paridad TUI/extensión.
   5b. **TUI: `/export <ruta>`** — dump markdown de una sesión (trivial con el Store actual) y **`/stats`** proxy (`GET /v1/stats`) para observabilidad desde la TUI.
6. **Proxy: multi-upstream real (F9 candidato).** `upstream.py` soporta hoy UN upstream + `FALLBACK_MODEL`. Evolución natural: lista priorizada de upstreams (NIM → OpenRouter → local) con failover por carril; `PASSTHROUGH_MODELS` por upstream. Es el cambio de arquitectura con mayor ROI para blindarse del free-tier errático (gpt-oss-20b 3/6 timeouts).
7. **Windows service / tray para el proxy** (o `nssm`): hoy depende de ventanas abiertas y PIDs manuales; un servicio auto-start eliminaría la fricción del launcher.
8. **Backfill de embeddings**: correr `python backfill_embeddings.py` tras levantar :8081 para dar a la KB existente la capa semántica.

### P2 — Medio plazo (semanas): producto

9. **MCP server sobre la KB del proxy** (`/v1/knowledge*` ya existe): exponer el RAG como herramienta MCP para que la extensión MiuraCode y otros agentes consulten la base de conocimiento. Complementa: **AGENTS.md/CLAUDE.md en `services/`** con las convenciones de cada subproyecto.
10. **Gigaxity keys Exa + SerpAPI** (placeholders ya en `services/gigaxity/.env`): activar los dos carriles de búsqueda faltantes.
11. **TUI: multi-ventana/pane** (split sesiones), **`/remember` con extracción automática** al final de cada sesión (hoy es manual).
12. **Evaluación comparativa orquestado vs passthrough:** medir con `GET /v1/stats` si la descomposición atómica mejora calidad en prompts compuestos de contenido (la tesis del proyecto) — generaría el caso de uso "modo deep" del ecosistema de contenido. Dataset sugerido: prompts reales del workflow de YouTube/SSinsta.
13. **CI:** GitHub Actions corriendo pytest (atomic-ai) + vitest (miura) + check-types en PRs a `miuracode`. El repo ya tiene `.github/` del fork; faltan los workflows de servicios.

### P3 — Largo plazo: la visión completa

14. **Generación local reactivada:** cuando exista un GGUF sin bucle de razonamiento (base/quant oficial), pasar la batería T5/T6/T7 (exigir `content_len > 0`), devolver `UPSTREAM_BASE_URL` a `http://127.0.0.1:8080` y usar NIM solo como fallback cloud — soberanía total de $0.
15. **Vision lane (LFM2.5-VL-3B)**: el routing F1 ya soporta especialidad visión; falta el modelo multimodal en el stack local y cablearlo en `routing.py` (presets ya en `D:\IA\GGUF\gguf\presets.ini`).
16. **Lago de contenido:** la KB del proxy (`atomic_ai.db`) + auto-aprendizaje F7 como base de un "second brain" del ecosistema Miura (los videos del canal, scripts, hooks, investigación) consultable desde TUI, extensión y agentes vía MCP.

## 8. Para el agente que continúa (convenciones y reglas del repo)

- **Idioma:** documentación y commits del ecosistema en **español** (README/ROADMAP/HANDOFF en ES; el código/identificadores en inglés sigue la convención upstream Roo). El TL;DR §0 en EN es deliberado para handoff internacional.
- **Commits:** convención `type(scope): mensaje` (`feat(miura):`, `feat(atomic-ai):`, `chore:`, `docs:`). Atómicos por feature. **Nunca ejecutes `git add` en paralelo a un commit** (incidente documentado en §3). Hooks husky estrictos: pre-push corre check-types workspace-wide.
- **Secretos:** `.env` jamás se versiona; plantillas `.env.example`. **El usuario pega las API keys él mismo** — un agente no debe escribir secretos en archivos. Ya ocurrió una corrección de seguridad (`353241cb5`).
- **Tests como DoD:** una feature no está hecha hasta que pytest/vitest está verde + docs actualizadas (README del componente + ROADMAP si cambia el estado) + este HANDOFF si cierra un hito.
- **Trabaja siempre en `D:\...\miuracode`** (monorepo, rama `miuracode`). La copia standalone `atomic_ai-main` es solo forense. No confundas `apps/miura` (TUI) con `apps/cli` (CLI del fork Roo).
- **Regla `/v1`:** todo upstream nuevo se configura SIN sufijo `/v1` en `UPSTREAM_BASE_URL`.
- **Frontier de conocimiento:** el estado de la tésis "la descomposición atómica mejora a modelos pequeños" está medida solo anecdóticamente (demo del autor original + uso interno); falta la evaluación sistemática de P2-12.

## 9. Glosario y referencia rápida

| Término                | Significado en este ecosistema                                                                                                                                  |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **MiuraCode**          | El monorepo completo (extensión VS Code fork de Roo Code + servicios).                                                                                          |
| **atomic-ai**          | Proxy de descomposición atómica (`services/atomic-ai`, :8120).                                                                                                  |
| **Gigaxity**           | Servicio de deep research web (`services/gigaxity`, :8090).                                                                                                     |
| **miura (TUI)**        | App de chat terminal persistente (`apps/miura`, bin `miura`).                                                                                                   |
| **Carril (lane)**      | Nombre de modelo expuesto por el proxy: orquestado (`deepseek-v4-flash`), `miura-fast` (= gpt-oss-20b, passthrough), `miura-reasoner` (= kimi-k3, passthrough). |
| **Heretic**            | Merge experimental local `Qwen3.5-4B-EmperoAI-Qwen3.8` (llama-server :8080) — descartado para generación por bucle de razonamiento.                             |
| **F1–F8**              | Features del fork del proxy: routing, resiliencia, paralelo, streaming progreso, KB metadatos, métricas, web research, passthrough+rate limit.                  |
| **PASSTHROUGH_MODELS** | Variable que define carriles de reenvío directo (`carril=modelo`).                                                                                              |
| **T5/T6/T7**           | Batería de tests de decisión de generación (ver §4.2 y `LOCAL_LLAMACPP_FINDINGS.md`).                                                                           |
| **Engram-lite**        | Patrón de memoria `clave=valor` FTS5 del TUI (sin embeddings).                                                                                                  |
| **Nichonauta**         | Autor original de atomic_ai (videos: teoría + demo en el README del servicio).                                                                                  |

**Endpoints del proxy (:8120):** `POST /v1/chat/completions` (chat; carriles arriba) · `GET /v1/models` · `GET /v1/stats` (métricas F6) · `GET/POST/DELETE /v1/knowledge*` (KB admin; protegible con `ADMIN_TOKEN`) · `POST /v1/knowledge/backfill` (backfill de embeddings). `GET /` responde estado (`passthrough_models`, etc.).

**Puntos de extension futuros (donde tocar qué):** nuevo upstream → `services/atomic-ai/.env` · nuevo carril → `PASSTHROUGH_MODELS` · routing por especialidad → `app/routing.py` · prompts del motor → `app/prompts/*.md` · UI del TUI → `apps/miura/src/ui/` · provider de la extensión → `src/` (fork Roo) + `packages/types` · deep research → `services/gigaxity/`.

---

_Cierre: documento escrito por Cline junto al propietario (AnZa07) al completar el hito F1–F4/TUI + pivot NIM, 2026-10-09. Veracidad garantizada: cada afirmación de estado fue medida contra el sistema vivo esa misma fecha; cada afirmación de historia proviene del log git del monorepo._
