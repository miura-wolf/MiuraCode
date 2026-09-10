import { type PoolsideModelId, poolsideDefaultModelId, poolsideModels } from "@roo-code/types"

import type { ApiHandlerOptions } from "../../shared/api"

import { BaseOpenAiCompatibleProvider } from "./base-openai-compatible-provider"

export class PoolsideHandler extends BaseOpenAiCompatibleProvider<PoolsideModelId> {
	constructor(options: ApiHandlerOptions) {
		super({
			...options,
			providerName: "Poolside",
			baseURL: "https://inference.poolside.ai/v1",
			apiKey: options.poolsideApiKey,
			defaultProviderModelId: poolsideDefaultModelId,
			providerModels: poolsideModels,
			defaultTemperature: 0.7,
		})
	}
}
