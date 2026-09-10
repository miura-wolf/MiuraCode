# MiuraCode — Servicios locales

MiuraCode no es solo la extensión de VS Code: es un **monorepo** que integra los
dos servicios Python que le dan superpoderes, viviendo junto al código de la
extensión (`.ts`) bajo `services/`:

```
┌────────────┐     /v1/chat/completions      ┌──────────────────┐
│  MiuraCode │ ─────────────────────────────► │   Atomic AI      │ :8120
│ (VS Code)  │                               │  (orquestador)   │
└────────────┘                               └────────┬─────────┘
                                                      │ miss del RAG local (F7)
                                                      ▼
                                             ┌──────────────────┐
                                             │  Gigaxity        │ :8090
                                             │ Deep Research    │
                                             └────────┬─────────┘
                                    búsqueda web (Exa/SerpApi/Tavily/LinkUp)
                                                      ▼
                                             NIM (síntesis con citas)
```

| Servicio | Puerto | Rol |
|---|---|---|
| `atomic-ai` | **8120** | Orquestador: descomposición atómica, RAG híbrido, routing F1–F7 |
| `gigaxity` | **8090** | Deep research web: multi-búsqueda + síntesis con citas |

## Puesta en marcha

```powershell
# 1. Venvs (solo la primera vez)
python -m venv services\atomic-ai\.venv
services\atomic-ai\.venv\Scripts\pip install -r services\atomic-ai\requirements.txt
python -m venv services\gigaxity\.venv
services\gigaxity\.venv\Scripts\pip install -e services\gigaxity

# 2. Configura los .env (NO se versionan)
copy services\atomic-ai\.env.example services\atomic-ai\.env
copy services\gigaxity\.env.example  services\gigaxity\.env
#    edita services\gigaxity\.env: RESEARCH_LLM_API_KEY (NIM), TAVILY_API_KEY, ...

# 3. Arranca el stack (gigaxity :8090 → atomic-ai :8120, con healthchecks)
.\scripts\stack.ps1 up

# Estado / parada
.\scripts\stack.ps1 status
.\scripts\stack.ps1 down
```

> **Nota sobre SearXNG**: la instancia pública usada antes (`search.noemaai.com`)
> dejó de servir la API JSON (401). Mientras no haya un self-host, gigaxity
> funciona con los carriles de API: **Exa** (neural, $10/mes gratis) y
> **SerpApi** (~100/mes gratis) más **Tavily** y **LinkUp** si tienes keys.
> Añade `RESEARCH_EXA_API_KEY` / `RESEARCH_SERPAPI_API_KEY` al `.env` de gigaxity.

## Mapa de puertos del ecosistema completo

| Puerto | Servicio | Estado |
|---|---|---|
| 8080 | llama-server (Qwen3.5-4B, upstream de atomic-ai) | externo (llama_cpp.bat) |
| 8081 | llama-server embeddings (bge-m3, RAG de atomic-ai) | externo (llama_embedding.bat) |
| 8090 | **gigaxity** (este monorepo) | `scripts\stack.ps1` |
| 8120 | **atomic-ai** (este monorepo) | `scripts\stack.ps1` |

## Tests

```powershell
# atomic-ai (130 tests)
Set-Location services\atomic-ai; .\.venv\Scripts\python.exe -m pytest -q

# gigaxity (915+ tests, 4 fallos pre-existentes por .env local NIM)
Set-Location services\gigaxity; .\.venv\Scripts\python.exe -m pytest -q -m "not integration"
```

## Notas de integración

- **Origen de los servicios**: absorbidos con `git subtree` desde sus repos
  (`atomic-ai` de `miura-wolf/atomic_ai` rama `v2-orchestrator`, con historial
  completo F1–F7; `gigaxity` de `miura-wolf/gigaxity-deep-research`, squashed).
  Para sincronizar cambios: `git subtree pull` (ver `git subtree --help`).
- **El VSIX no incluye nada de esto**: `src/.vscodeignore` empaqueta en modo
  whitelist desde `src/`; `services/` nunca entra al paquete de la extensión.
- **MiuraCode no necesita cambios**: la extensión ya apunta a
  `http://127.0.0.1:8120/v1` (provider "Atomic AI"); el proxy sigue en el
  mismo puerto dentro del monorepo.
- **Sincronización con GitHub**: este repo debe vivir en tu fork
  (`miura-wolf/MiuraCode`); los servicios mantienen su upstream propio para
  `subtree pull`.