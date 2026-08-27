# 🚀 ROADMAP — Atomic AI v2 (Fork potenciado)

> Este documento es el plan de trabajo para potenciar el *Atomic Decomposition Proxy*
> original de [Nichonauta](https://github.com/Nichonauta/atomic_ai) hacia un
> **orquestador multi-modelo local** aprovechando un arsenal de GGUF corriendo en
> llama.cpp (Vulkan, tarjeta Intel Arc).

---

## 🎯 Objetivo

Convertir Atomic AI de *"proxy de un solo upstream barato"* en un
**orquestador heterogéneo** que:

- Reparte cada tarea al **modelo más adecuado** (visión, código, resumen, velocidad).
- Es **resiliente** ante fallos (retries, fallback a modelo de respaldo, rollback).
- **Ejecuta en paralelo** subtareas independientes.
- Aprende y recuerda (RAG híbrido + auto-aprendizaje — ya implementado).
- Muestra **progreso observable** a los clientes agénticos.

---

## ✅ Estado actual (ya logrado en esta rama de trabajo)

| Capa | Estado |
|---|---|
| Descomposición atómica (plan→ejecutar→sintetizar) | ✅ núcleo sólido |
| Tool-calling con pausa/reanudación (hasta 25 rondas) | ✅ robusto |
| RAG híbrido (FTS5 keywords ∪ similitud coseno) | ✅ implementado (`app/knowledge.py`, `app/embeddings.py`) |
| Auto-aprendizaje self-loop con dedupe | ✅ implementado (`engine._save_knowledge_safe`) |
| Endpoints admin de conocimiento (`/v1/knowledge*`) | ✅ implementado (`main.py`) |
| Backfill de vectores para la KB existente | ✅ `backfill_embeddings.py` + endpoint |
| Multi-modelo **por turno** (cambiar `model` en cada request) | ✅ funciona vía `requested_model = request.model or settings.upstream_model` |
| **Routing multi-modelo por especialidad (F1)** | ✅ implementado (`app/routing.py`): cada hoja atómica va al modelo visión/código/rápido adecuado |
| **Resiliencia: retry + fallback (F2)** | ✅ implementado (`app/upstream.py`): reintentos transitorios, modelo de respaldo y reparación de JSON de descomposición |
| **Ejecución paralela de hojas (F3)** | ✅ implementado (`engine._execute_parallel`): hojas independientes con `asyncio.gather`, fallback a secuencial con tools |
| **Streaming con progreso del árbol (F4)** | ✅ implementado (`sse.progress_chunk`): eventos `progress` SSE opt-in para clientes agénticos |
| **Metadatos/grafo en la KB (F5)** | ✅ implementado (`db.py`): `source`, `updated_at`, `vector_updated_at`, `parent_id`, `version` + migración automática |
| **Observabilidad / métricas (F6)** | ✅ implementado (`app/metrics.py` + `GET /v1/stats`): contadores y latencias por fase en memoria, sin dependencias externas |
| Visión (mmproj) | ✅ pero global por turno (todo el turno usa un solo modelo) |
| Tests | ✅ **117/117** pasando |

---

## 🕳️ Backlog priorizado

### ✅ F1 — Routing MULTI-MODELO por especialidad *(IMPLEMENTADO en `app/routing.py`)*

Hoy el proxy usa **UN remero en TODAS las fases** del turno. Doblamos hacia
orquestador real asignando modelo por *hoja atómica* según especialidad:

```
hoja 1 = visión   → LFM2.5-VL-3B
hoja 2 = código   → Qwen3.5-4B
hoja 3 = resumen  → Ling-3-flash
síntesis final     → Qwen3.5-4B
```

**Diseño propuesto:**
- Nuevas variables en `.env`: `VISION_MODEL`, `CODE_MODEL`, `FAST_MODEL`, `DEFAULT_MODEL`.
- Cada `TaskNode` hereda una `specialty` (detectada por: ¿hay imagen? → visión;
  ¿genera código? → code; ¿breve/resumen? → fast; else default).
- El engine asigna `model` por hoja en lugar de por turno.
- La síntesis usa `DEFAULT_MODEL`.

### ✅ F2 — Fallback + retry resiliente *(IMPLEMENTADO en `app/upstream.py` + `app/engine.py`)*

- Retry de la descomposición si el JSON llega roto (reintento con prompt
  reforzado; si sigue fallando → bajar a tarea plana / modo sin descomponer).
- Timeout/NaN en ejecución → reintento con `FAST_MODEL` de respaldo.
- Rollback: si el plan falla del todo, responder con la mejor respuesta parcial.

### ✅ F3 — Ejecución PARALELA de hojas atómicas independientes *(IMPLEMENTADO en `engine._execute_parallel`)*

- Detectar hojas **sin dependencia** de resultado previo (gr.cpp del árbol).
- Ejecutarlas con `asyncio.gather` contra el upstream.
- Speedup esperado 2-3x en tareas con varias ramas sueltas.

### ✅ F4 — Streaming con progreso del árbol *(IMPLEMENTADO en `sse.progress_chunk` + `engine`)*

- Eventos SSE adicionales con campo `progress`: `phase_started`, `phase_done`,
  `leaf_started`, `leaf_done`, `done` para que clientes agénticos muestren
  progreso real. Opt-in vía `EMIT_PROGRESS_EVENTS`; los clientes OpenAI
  estándar ignoran el campo, así que es retrocompatible.

### ✅ F5 — Metadatos / grafo en la knowledge base *(IMPLEMENTADO en `db.py`)*

- `knowledge_base` ahora guarda: `source` (manual/auto_learn), `updated_at`,
  `vector_updated_at`, `parent_id` (grafo) y `version`.
- Migración automática idempotente para bases creadas antes de F5.
- `GET /v1/knowledge/stats` añade el desglose `by_source`.

### ✅ F6 — Observabilidad / métricas *(IMPLEMENTADO en `app/metrics.py` + `GET /v1/stats`)*

- Contadores: hojas descompuestas/ejecutadas, ejecuciones paralelas vs secuenciales,
  rondas y llamadas de tools, consultas/aciertos/fallos de RAG.
- Latencias por fase: descomposición, ejecución de hoja y síntesis.
- Registro en memoria, sin dependencias externas, expuesto vía `GET /v1/stats`
  (protegido por `X-Admin-Token` como el resto de endpoints admin).

---

## 📦 Stack local objetivo (ya definido)

| Rol | Modelo | Puerto |
|---|---|---|
| Cerebro principal (planner/síntesis) | Qwen3.5-4B (UD-Q4_K_XL, draft dflash n=4) | 8080 |
| Código / residual | Qwen3.5-4B (ídem) | 8080 |
| Velocidad / resúmenes | Ling-3-flash | 8080 |
| Visión | LFM2.5-VL-3B (mmproj BF16) | 8080 |
| Embeddings (RAG semántico) | **bge-m3 Q8_0** | 8081 |
| Proxy | Atomic AI v2 | 8120 |

> **Nota importante**: Qwen3-Embedding-0.6B se descartó por NaN con los builds
> actuales de llama.cpp (b10630/b10502); bge-m3 funciona perfecto en el mismo
> build/GPU/flags.

---

## 🛠️ Acciones técnicas ya realizadas (fuera del código del proxy)

- `D:\IA\GGUF\gguf\llama_cpp.bat` → router mode en b10630, pregunta interactiva para embeddings.
- `D:\IA\GGUF\gguf\llama_embedding.bat` → bge-m3 en :8081.
- `presets.ini` → sección `[Qwen3.5-4B]` optimizada (dflash n_max=4, KV q8_0, fa=on, ctx 65536, mmproj).

---

## 🔀 Plan de FORK (git)

Contexto: la carpeta actual es el **ZIP descargado** (sin `.git`). Pasos:

1. Clonar repo oficial: `git clone https://github.com/Nichonauta/atomic_ai.git`
2. Crear rama de trabajo `v2-orchestrator`.
3. Copiar encima nuestros cambios (código `app/`, `tests/`, `backfill_embeddings.py`,
   `ROADMAP.md`, `README.md` actualizado) — **excluyendo** `.env` real, `atomic_ai.db`,
   `.venv`, `.pytest_cache`.
4. Crear fork en GitHub y apuntarlo como `origin`.
5. Commit atómico por feature (F1..F6) para historial limpio.

---

## ✅ Definición de hecho (DoD) por feature

- Código implementado + tipado.
- Tests nuevos (pytest) cubriendo el feature.
- Suite completa verde (hoy 71 tests, crecerá).
- Documentación en `README.md` (variables y endpoints).
- Validación manual contra llama.cpp real cuando aplique.

---

*Última actualización: 2026-08-27 — F1 (routing), F2 (resiliencia), F3 (paralelo), F4 (streaming de progreso), F5 (metadatos KB) y F6 (observabilidad/métricas) implementados y testeados.*