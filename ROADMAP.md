# 🚀 ROADMAP — MiuraCode (monorepo)

> Plan de trabajo del ecosistema Miura: fork de Roo-Code (`miura-wolf/MiuraCode`,
> rama `miuracode`) con los servicios backend absorbidos como subtrees bajo
> `services/`. Este archivo es la lista única de tareas pendientes del
> ecosistema; el detalle técnico de atomic-ai vive en
> `services/atomic-ai/ROADMAP.md`.

---

## ✅ Estado actual

| Capa                                                                                     | Estado                                                                                                                                    |
| ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Monorepo (subtrees `services/atomic-ai` + `services/gigaxity`)                           | ✅ absorbidos, tests verdes (130 + 919), backup en GitHub                                                                                 |
| atomic-ai (F1–F7: routing, resiliencia, paralelo, streaming, KB, métricas, web research) | ✅ 130/130 tests                                                                                                                          |
| gigaxity: carriles Tavily/LinkUp                                                         | ✅ activos con keys reales, RRF fusion funcionando                                                                                        |
| gigaxity: carriles Exa + SerpAPI (free-tier keyed)                                       | ✅ cableados, 23 tests, **pendientes de keys** (exa.ai / serpapi.com)                                                                     |
| gigaxity: carril **ddgs keyless** (deedy5/ddgs)                                          | ✅ implementado y testeado (opt-in `RESEARCH_DDGS_ENABLED`, 20 tests) — funciona HOY sin key mientras llegan las de Exa/SerpAPI           |
| gigaxity: **rate limiter NIM**                                                           | ✅ ventana deslizante RPM en `llm_client.py` (`RESEARCH_LLM_RPM`, default 0=off; 40 recomendado bajo los ~45 RPM del free-tier), 15 tests |
| Stack `scripts/stack.ps1`                                                                | ✅ up/down funcionando (gigaxity :8090, atomic-ai :8120)                                                                                  |

---

## 📌 Pendiente / Siguiente

1. **Keys Exa + SerpAPI**: crear cuentas en exa.ai y serpapi.com →
   `RESEARCH_EXA_API_KEY` / `RESEARCH_SERPAPI_API_KEY` en
   `services/gigaxity/.env`. Ambos conectores ya están cableados y testeados;
   con las keys simplemente se activan (los carriles existentes
   Tavily/LinkUp/ddgs siguen fusionando mientras tanto).
2. **Re-test NIM al reset de cuota** (diario): `POST /api/v1/research` con
   síntesis completa. Con `RESEARCH_LLM_RPM=40` el limiter evita reventar los
   ~45 RPM del free-tier (y el bucle de retries del SDK encima).
3. **llama-server (`D:\IA\GGUF\gguf\llama_cpp.bat`)**: levantar en :8080 →
   probar `POST /v1/chat/completions` end-to-end (miss RAG → F7 → gigaxity →
   ddgs/Tavily/LinkUp).
4. **Passthrough `miura-fast`**: sigue inexistente en atomic-ai (modelos
   ruteados por especialidad, pero todo el turno usa el upstream real; no hay
   modo "passthrough" puro). Pendiente de diseño.
5. **i18n F7**: revisar el wording de 18 locales para el claim de
   "web research" (paquete `i18n` de la extensión).
6. **Roadmap local → remoto**: este ROADMAP.md raíz se versiona en git;
   actualizarlo aquí al completar tareas.
