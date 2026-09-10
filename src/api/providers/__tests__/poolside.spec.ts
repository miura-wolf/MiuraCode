// npx vitest run src/api/providers/__tests__/poolside.spec.ts

import OpenAI from "openai"
import { Anthropic } from "@anthropic-ai/sdk"

import { poolsideDefaultModelId, poolsideModels } from "@roo-code/types"

import { PoolsideHandler } from "../poolside"

vitest.mock("openai", () => {
	const createMock = vitest.fn()
	return {
		default: vitest.fn(() => ({ chat: { completions: { create: createMock } } })),
	}
})

describe("PoolsideHandler", () => {
	let handler: PoolsideHandler
	let mockCreate: any

	beforeEach(() => {
		vitest.clearAllMocks()
		mockCreate = (OpenAI as unknown as any)().chat.completions.create
		handler = new PoolsideHandler({ poolsideApiKey: "test-poolside-api-key" })
	})

	it("should use the correct Poolside base URL", () => {
		new PoolsideHandler({ poolsideApiKey: "test-poolside-api-key" })
		expect(OpenAI).toHaveBeenCalledWith(expect.objectContaining({ baseURL: "https://inference.poolside.ai/v1" }))
	})

	it("should use the provided API key", () => {
		const poolsideApiKey = "test-poolside-api-key"
		new PoolsideHandler({ poolsideApiKey })
		expect(OpenAI).toHaveBeenCalledWith(expect.objectContaining({ apiKey: poolsideApiKey }))
	})

	it("should return default model when no model is specified", () => {
		const model = handler.getModel()
		expect(model.id).toBe(poolsideDefaultModelId)
		expect(model.info).toEqual(poolsideModels[poolsideDefaultModelId])
	})

	it("should return specified model when valid model is provided", () => {
		const testModelId = "poolside/laguna-s-2.1"
		const handlerWithModel = new PoolsideHandler({
			apiModelId: testModelId,
			poolsideApiKey: "test-poolside-api-key",
		})
		const model = handlerWithModel.getModel()
		expect(model.id).toBe(testModelId)
		expect(model.info).toEqual(poolsideModels[testModelId])
	})

	it("completePrompt method should return text from Poolside API", async () => {
		const expectedResponse = "This is a test response from Poolside"
		mockCreate.mockResolvedValueOnce({ choices: [{ message: { content: expectedResponse } }] })
		const result = await handler.completePrompt("test prompt")
		expect(result).toBe(expectedResponse)
	})

	it("should handle errors in completePrompt", async () => {
		const errorMessage = "Poolside API error"
		mockCreate.mockRejectedValueOnce(new Error(errorMessage))
		await expect(handler.completePrompt("test prompt")).rejects.toThrow(
			`Poolside completion error: ${errorMessage}`,
		)
	})

	it("createMessage should yield text content from stream", async () => {
		const testContent = "This is test content from Poolside stream"

		mockCreate.mockImplementationOnce(() => {
			return {
				[Symbol.asyncIterator]: () => ({
					next: vitest
						.fn()
						.mockResolvedValueOnce({
							done: false,
							value: { choices: [{ delta: { content: testContent } }] },
						})
						.mockResolvedValueOnce({ done: true }),
				}),
			}
		})

		const stream = handler.createMessage("system prompt", [])
		const firstChunk = await stream.next()

		expect(firstChunk.done).toBe(false)
		expect(firstChunk.value).toEqual({ type: "text", text: testContent })
	})

	it("createMessage should yield usage data from stream", async () => {
		mockCreate.mockImplementationOnce(() => {
			return {
				[Symbol.asyncIterator]: () => ({
					next: vitest
						.fn()
						.mockResolvedValueOnce({
							done: false,
							value: { choices: [{ delta: {} }], usage: { prompt_tokens: 10, completion_tokens: 20 } },
						})
						.mockResolvedValueOnce({ done: true }),
				}),
			}
		})

		const stream = handler.createMessage("system prompt", [])
		const firstChunk = await stream.next()

		expect(firstChunk.done).toBe(false)
		expect(firstChunk.value).toMatchObject({ type: "usage", inputTokens: 10, outputTokens: 20 })
	})

	it("createMessage should pass correct parameters to Poolside client", async () => {
		mockCreate.mockImplementationOnce(() => {
			return {
				[Symbol.asyncIterator]: () => ({
					async next() {
						return { done: true }
					},
				}),
			}
		})

		const systemPrompt = "Test system prompt for Poolside"
		const messages: Anthropic.Messages.MessageParam[] = [{ role: "user", content: "Test message for Poolside" }]

		const messageGenerator = handler.createMessage(systemPrompt, messages)
		await messageGenerator.next()

		expect(mockCreate).toHaveBeenCalledWith(
			expect.objectContaining({
				model: poolsideDefaultModelId,
				temperature: 0.7,
				messages: expect.arrayContaining([{ role: "system", content: systemPrompt }]),
				stream: true,
				stream_options: { include_usage: true },
			}),
			undefined,
		)
	})
})
