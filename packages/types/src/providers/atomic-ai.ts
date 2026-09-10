import type { ModelInfo } from "../model.js"

// Atomic AI — proxy orquestador local (atomic_ai-fork, app/main.py) con
// descomposición atómica (F1-F4), RAG híbrido FTS5+vectores (bge-m3) e
// investigación web (F7). El proxy acepta cualquier `model` en la request:
// F1 resuelve la especialidad por hoja y el modelo base del turno se envía
// tal cual al upstream (llama.cpp local). Estos perfiles definen el
// presupuesto de contexto/salida que MiuraCode usa del lado cliente.
export type AtomicAIModelId = "atomic-orchestrator"

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
} as const satisfies Record<string, ModelInfo>
