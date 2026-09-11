# Hallazgos en vivo: llama.cpp local (heretic) vs. NVIDIA NIM

> Pruebas ejecutadas el **2026-10-09** con llamadas reales contra el modelo
> local (llama-server en `127.0.0.1:8080`) y contra NVIDIA NIM free tier
> (`integrate.api.nvidia.com`), durante la construcción del TUI `miura`
> ([apps/miura](../../../apps/miura)) y el remapeo del carril passthrough (F8).
> Cifras = medición directa de cada respuesta; nada es estimación.

## TL;DR

1. **El lane local queda descartado para generación.** El modelo herético
   `Qwen3.5-4B-EmperoAI-Qwen3.8` consume el presupuesto **completo** de
   completion tokens en `reasoning_content` y emite **contenido vacío** —
   con `max_tokens` 2048 y 8192, en streaming y sin streaming, con prompt de
   código y casual. No es un bug de llama.cpp, del proxy ni del cliente: es
   el patrón de comportamiento del merge.
2. **El pivot de upstream es NVIDIA NIM free tier**: `deepseek-v4-flash` para
   el carril orquestado (JSON en ~4 s) y `gpt-oss-20b` + `kimi-k3` para chat
   directo (carriles `miura-fast` / `miura-reasoner`).
3. **`deepseek-v4-flash` es razonador puro en chat directo** (contesta con
   razonamiento y `content` vacío); por eso `miura-fast` remapea a
   `gpt-oss-20b` y no a deepseek.
4. **`gpt-oss-20b` en el free tier es errático** (timeouts intermitentes);
   `FALLBACK_MODEL=moonshotai/kimi-k3` lo cubre (estable, ~59 s).

## Evidencia — modelo local (heretic)

Servidor: llama-server, endpoint `POST /v1/chat/completions`.

| Test | Prompt | `max_tokens` | Stream | Tiempo | finish_reason | Tokens | Chunks reasoning | `content` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T5 | función JS sumar (+ system "piensa brevemente") | 2048 | no | **147 s** | `length` | 833 | — | **vacío** |
| T6 | función JS sumar | 8192 | sí | **367 s** | `length` | — | 833 | **vacío** |
| T7 | "Hola, ¿quién eres?" | 8192 | sí | **189 s** | `length` | — | 833 | **vacío** |

### Patrón definitivo

- **833 tokens de razonamiento en los tres tests**, idéntico, y `finish_reason
  = length`: el modelo entra en un bucle de razonamiento que agota el
  presupuesto de tokens **antes de emitir un solo carácter de contenido**.
- Subir `max_tokens` de 2048 → 8192 no ayuda (T5 vs T6/T7): solo alarga el
  bucle (147 s → 189-367 s en CPU) y consume el presupuesto igual.
- Quitar el system prompt no ayuda (T6/T7 no lo llevan).
- El streaming no ayuda: los chunks de `reasoning_content` fluyen, pero
  `delta.content` llega siempre vacío.
- Conclusión: descartado como generador. Un lane local solo vuelve a ser
  viable con un modelo sin ese defecto (p. ej. un base/quant oficial sin
  merge herético), y re-validando con esta misma batería.

## Evidencia — NVIDIA NIM free tier

Endpoint `POST https://integrate.api.nvidia.com/v1/chat/completions`.

| Modelo | `max_tokens` | Tiempo | finish | Tokens | Contenido |
| --- | --- | --- | --- | --- | --- |
| `deepseek-ai/deepseek-v4-flash-0731` | 350 | 4 s | `length` | 350 | **vacío** (razonador puro) |
| `deepseek-ai/deepseek-v4-flash-0731` | 350 | 60 s | — | — | timeout |
| `openai/gpt-oss-20b` | 350 | **19 s** | `stop` | 224 | ✅ real |
| `openai/gpt-oss-20b` | 350 | 60 s | — | — | timeout |
| `openai/gpt-oss-20b` | sin límite | 90 s | — | — | timeout |
| `moonshotai/kimi-k3` | sin límite | **59 s** | `stop` | 75 | ✅ real (estable) |
| `miura-fast` vía proxy (= gpt-oss-20b) | sin límite | **5 s** | `stop` | — | ✅ 176 chars, streaming |

### Lectura

- `deepseek-v4-flash` es **excelente para el carril orquestado** (F2:
  descomposición/hojas/síntesis con `response_format=json_object` responde
  en ~4 s) pero **inútil para chat directo**: consume el presupuesto en
  razonamiento igual que el heretic local, solo que más rápido.
- `gpt-oss-20b` entrega contenido real en chat directo (5-19 s) pero el free
  tier lo congela con frecuencia (3 de 6 llamadas acabaron en timeout) →
  necesita fallback.
- `kimi-k3` es el más consistente del tier gratis (~59 s, siempre con
  contenido) → `FALLBACK_MODEL` y carril `miura-reasoner`.

## Configuración resultante (`.env.example`)

| Variable | Valor | Por qué |
| --- | --- | --- |
| `UPSTREAM_BASE_URL` | `https://integrate.api.nvidia.com` | **sin** sufijo `/v1` (el proxy ya añade `/v1/chat/completions`; un `/v1` duplicado producía 404 en streaming) |
| `UPSTREAM_MODEL` | `deepseek-ai/deepseek-v4-flash-0731` | carril orquestado (JSON, ~4 s) |
| `FALLBACK_MODEL` | `moonshotai/kimi-k3` | cubre los timeouts erráticos de gpt-oss |
| `PASSTHROUGH_MODELS` | `miura-fast=openai/gpt-oss-20b,miura-reasoner=moonshotai/kimi-k3` | chat directo sin descomposición |
| `REQUEST_TIMEOUT_SECONDS` | `180` | NIM responde en 4-30 s; 900 (margen para CPU local) ya no aplica |
| `UPSTREAM_RPM` | `20` | el free tier rechaza ráfagas ~45 RPM con `503 ResourceExhausted`; presupuesto compartido con Gigaxity |

## Qué queda del stack local

- **Descartado**: generación con `Qwen3.5-4B-EmperoAI-Qwen3.8` (esta doc).
- **Vigente**: llama-server con **bge-m3** en `127.0.0.1:8081` como servidor
  de **embeddings** para la búsqueda híbrida F1-RAG (`EMBEDDINGS_BASE_URL`)
  — el defecto es del generador, no del servidor de inferencia.
- **Para reactivar generación local** algún día: cargar un modelo sin el
  bucle de razonamiento, pasar esta batería (T5/T6/T7 con `content_len > 0`)
  y devolver `UPSTREAM_BASE_URL` a `http://127.0.0.1:8080`.
