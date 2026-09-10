import type { ModelInfo } from "../model.js"

// https://inference.poolside.ai/v1 — free tier con tool calling nativo
// confirmado en la práctica (/v1/models + tool call get_weather verificados).
// Contexto 256K reportado por el endpoint /v1/models.
export type PoolsideModelId = "poolside/laguna-xs-2.1" | "poolside/laguna-s-2.1"

export const poolsideDefaultModelId: PoolsideModelId = "poolside/laguna-xs-2.1"

export const poolsideModels = {
	"poolside/laguna-xs-2.1": {
		maxTokens: 8192,
		contextWindow: 262144,
		supportsImages: false,
		supportsPromptCache: false,
		isFree: true,
		description:
			"poolside Laguna XS 2.1 — modelo de código rápido (free tier), contexto 256K, tool calling nativo.",
	},
	"poolside/laguna-s-2.1": {
		maxTokens: 8192,
		contextWindow: 262144,
		supportsImages: false,
		supportsPromptCache: false,
		isFree: true,
		description: "poolside Laguna S 2.1 — modelo de código grande (free tier), contexto 256K, tool calling nativo.",
	},
} as const satisfies Record<string, ModelInfo>
