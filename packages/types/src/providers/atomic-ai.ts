import type { ModelInfo } from "../model.js"

// Atomic AI — proxy orquestador local (atomic_ai-fork, app/main.py) con
// descomposición atómica (F1-F4), RAG híbrido FTS5+vectores (bge-m3) e
// investigación web (F7). El proxy acepta cualquier `model` en la request:
// F1 resuelve la especialidad por hoja y el modelo base del turno se envía
// tal cual al upstream (llama.cpp local). Estos perfiles definen el
// presupuesto de contexto/salida que MiuraCode usa del lado cliente.
//
// F8 — carril passthrough: los modelos listados en PASSTHROUGH_MODELS del
// proxy (p. ej. "miura-fast") se reenvían al upstream TAL CUAL — una sola
// llamada, sin descomposición/RAG/sesiones — para chat directo de latencia
// mínima. "miura-fast" es el carril directo por defecto del stack local.
export type AtomicAIModelId = "atomic-orchestrator" | "miura-fast"

export const atomicAiDefaultModelId: AtomicAIModelId = "atomic-orchestrator"

export const atomicAiModels = {
	"atomic-orchestrator": {
		maxTokens: 8192,
		contextWindow: 32768,
		supportsImages: false,
		supportsPromptCache: false,
		isFree: true,
		description:
			"Orquestación atómica completa vía el proxy atomic_ai local: descompone el turno en hojas atómicas, RAG híbrido (FTS5 + bge-m3) e investigación web (F7) como respaldo. El modelo base (Qwen3.5-4B en llama.cpp) ejecuta cada fase y F1 puede routear hojas a especialistas.",
	},
	"miura-fast": {
		maxTokens: 8192,
		contextWindow: 32768,
		supportsImages: false,
		supportsPromptCache: false,
		isFree: true,
		description:
			"Carril passthrough (F8): reenvía el turno al upstream tal cual — una sola llamada, sin descomposición atómica, sin RAG y sin sesiones. Latencia mínima para chat directo; requiere PASSTHROUGH_MODELS=miura-fast en el proxy atomic_ai.",
	},
} as const satisfies Record<string, ModelInfo>
