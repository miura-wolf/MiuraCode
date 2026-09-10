# 🚀 ROADMAP — MiuraCode (monorepo)

> Plan de trabajo del ecosistema Miura: fork de Roo-Code (`miura-wolf/MiuraCode`,
> rama `miuracode`) con los servicios backend absorbidos como subtrees bajo
> `services/`. Este archivo es la lista única de tareas pendientes del
> ecosistema; el detalle técnico de atomic-ai vive en
> `services/atomic-ai/ROADMAP.md`.

---

## ✅ Estado actual

| Capa                                                                                     | Estado                                                                                                                                                    |
| ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Monorepo (subtrees `services/atomic-ai` + `services/gigaxity`)                           | ✅ absorbidos, tests verdes (152 + 919), backup en GitHub                                                                                                 |
| atomic-ai (F1–F7: routing, resiliencia, paralelo, streaming, KB, métricas, web research) | ✅ 152/152 tests                                                                                                                                          |
| atomic-ai: **rate limit del upstream (F8.1)** — aplica al CHAT, no solo a research       | ✅ ventana deslizante RPM en `app/rate_limit.py` (`UPSTREAM_RPM`, default 0=off); cada intento HTTP (reintentos F2 incluidos) gasta del mismo presupuesto |
| atomic-ai: **carril passthrough `miura-fast` (F8)**                                      | ✅ `PASSTHROUGH_MODELS`: reenvío TAL CUAL (1 llamada, sin decomp/RAG/sesiones; SSE verbatim) + modelo `miura-fast` en packages/types                      |
| extensión: i18n F7/F8                                                                    | ✅ wording `atomicAiBaseUrlDescription` actualizado en los 18 locales (citas + carril rápido)                                                             |
| gigaxity: carriles Tavily/LinkUp                                                         | ✅ activos con keys reales, RRF fusion funcionando                                                                                                        |
| gigaxity: carriles Exa + SerpAPI (free-tier keyed)                                       | ✅ cableados, 23 tests, **pendientes de keys** (placeholders ya en `services/gigaxity/.env`)                                                              |
| gigaxity: carril **ddgs keyless** (deedy5/ddgs)                                          | ✅ implementado y testeado (opt-in `RESEARCH_DDGS_ENABLED`, 20 tests) — funciona HOY sin key mientras llegan las de Exa/SerpAPI                           |
| gigaxity: **rate limiter NIM**                                                           | ✅ ventana deslizante RPM en `llm_client.py` (`RESEARCH_LLM_RPM`, default 0=off; 40 recomendado bajo los ~45 RPM del free-tier), 15 tests                 |
| Stack `scripts/stack.ps1`                                                                | ✅ up/down funcionando (gigaxity :8090, atomic-ai :8120)                                                                                                  |

---

## 📌 Pendiente / Siguiente

1. **Keys Exa + SerpAPI**: crear cuentas en exa.ai y serpapi.com → pegarlas
   en `RESEARCH_EXA_API_KEY` / `RESEARCH_SERPAPI_API_KEY` (placeholders ya
   presentes en `services/gigaxity/.env`). Ambos conectores ya están cableados
   y testeados; con las keys simplemente se activan (los carriles existentes
   Tavily/LinkUp/ddgs siguen fusionando mientras tanto).
2. **Re-test NIM al reset de cuota** (diario): `POST /api/v1/research` con
   síntesis completa. Con `RESEARCH_LLM_RPM=40` el limiter evita reventar los
   ~45 RPM del free-tier (y el bucle de retries del SDK encima). El mismo
   presupuesto de CUENTA aplica si se apunta el `UPSTREAM_BASE_URL` de
   atomic-ai a NIM: repartir (p. ej. `RESEARCH_LLM_RPM=20` + `UPSTREAM_RPM=20`).
3. **llama-server (`D:\IA\GGUF\gguf\llama_cpp.bat`)**: levantar en :8080 →
   probar `POST /v1/chat/completions` end-to-end (miss RAG → F7 → gigaxity →
   ddgs/Tavily/LinkUp), y el carril `miura-fast` (passthrough directo,
   ya activo con `PASSTHROUGH_MODELS=miura-fast` en el `.env`).
4. **Passthrough `miura-fast`** — ✅ HECHO (2026-09-09): `PASSTHROUGH_MODELS`
   en atomic-ai + modelo `miura-fast` en `packages/types` de la extensión.
5. **i18n F7** — ✅ HECHO (2026-09-09): wording del claim "web research"
   revisado en los 18 locales (`atomicAiBaseUrlDescription`: síntesis con
   citas + carril rápido miura-fast).
6. **Roadmap local → remoto**: este ROADMAP.md raíz se versiona en git;
   actualizarlo aquí al completar tareas.
