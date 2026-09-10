import { type AtomicAIModelId, atomicAiDefaultModelId, atomicAiModels } from "@roo-code/types"

import type { ApiHandlerOptions } from "../../shared/api"

import { BaseOpenAiCompatibleProvider } from "./base-openai-compatible-provider"

const DEFAULT_BASE_URL = "http://127.0.0.1:8120/v1"

export class AtomicAIHandler extends BaseOpenAiCompatibleProvider<AtomicAIModelId> {
	constructor(options: ApiHandlerOptions) {
		super({
			...options,
			providerName: "AtomicAI",
			// El proxy local no exige autenticación; la clave placeholder satisface
			// el check obligatorio del cliente OpenAI (Authorization: Bearer atomic-ai-local).
			baseURL: options.atomicAiBaseUrl?.trim() || DEFAULT_BASE_URL,
			apiKey: options.atomicAiApiKey?.trim() || "atomic-ai-local",
			defaultProviderModelId: atomicAiDefaultModelId,
			providerModels: atomicAiModels,
			defaultTemperature: 0,
		})
	}
}
