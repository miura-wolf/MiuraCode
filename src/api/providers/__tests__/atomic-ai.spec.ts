// npx vitest run src/api/providers/__tests__/atomic-ai.spec.ts

import OpenAI from "openai"
import { Anthropic } from "@anthropic-ai/sdk"

import { atomicAiDefaultModelId, atomicAiModels } from "@roo-code/types"

import { AtomicAIHandler } from "../atomic-ai"

vitest.mock("openai", () => {
	const createMock = vitest.fn()
	return {
		default: vitest.fn(() => ({ chat: { completions: { create: createMock } } })),
	}
})

describe("AtomicAIHandler", () => {
	let handler: AtomicAIHandler
	let mockCreate: any

	beforeEach(() => {
		vitest.clearAllMocks()
		mockCreate = (OpenAI as unknown as any)().chat.completions.create
		handler = new AtomicAIHandler({})
	})

	it("should use the default local proxy base URL", () => {
		new AtomicAIHandler({})
		expect(OpenAI).toHaveBeenCalledWith(expect.objectContaining({ baseURL: "http://127.0.0.1:8120/v1" }))
	})

	it("should use a custom base URL when provided", () => {
		new AtomicAIHandler({ atomicAiBaseUrl: "http://192.168.1.10:8120/v1" })
		expect(OpenAI).toHaveBeenCalledWith(expect.objectContaining({ baseURL: "http://192.168.1.10:8120/v1" }))
	})

	it("should not require an API key (local proxy placeholder)", () => {
		new AtomicAIHandler({})
		expect(OpenAI).toHaveBeenCalledWith(expect.objectContaining({ apiKey: "atomic-ai-local" }))
	})

	it("should use the provided API key when set", () => {
		new AtomicAIHandler({ atomicAiApiKey: "test-atomic-key" })
		expect(OpenAI).toHaveBeenCalledWith(expect.objectContaining({ apiKey: "test-atomic-key" }))
	})

	it("should return default model when no model is specified", () => {
		const model = handler.getModel()
		expect(model.id).toBe(atomicAiDefaultModelId)
		expect(model.info).toEqual(atomicAiModels[atomicAiDefaultModelId])
	})

	it("completePrompt method should return text from Atomic AI proxy", async () => {
		const expectedResponse = "This is a test response from Atomic AI"
		mockCreate.mockResolvedValueOnce({ choices: [{ message: { content: expectedResponse } }] })
		const result = await handler.completePrompt("test prompt")
		expect(result).toBe(expectedResponse)
	})

	it("should handle errors in completePrompt", async () => {
		const errorMessage = "AtomicAI API error"
		mockCreate.mockRejectedValueOnce(new Error(errorMessage))
		await expect(handler.completePrompt("test prompt")).rejects.toThrow(
			`AtomicAI completion error: ${errorMessage}`,
		)
	})

	it("createMessage should yield text content from stream", async () => {
		const testContent = "This is test content from Atomic AI stream"

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

	it("createMessage should pass correct parameters to Atomic AI client", async () => {
		mockCreate.mockImplementationOnce(() => {
			return {
				[Symbol.asyncIterator]: () => ({
					async next() {
						return { done: true }
					},
				}),
			}
		})

		const systemPrompt = "Test system prompt for Atomic AI"
		const messages: Anthropic.Messages.MessageParam[] = [{ role: "user", content: "Test message for Atomic AI" }]

		const messageGenerator = handler.createMessage(systemPrompt, messages)
		await messageGenerator.next()

		expect(mockCreate).toHaveBeenCalledWith(
			expect.objectContaining({
				model: atomicAiDefaultModelId,
				temperature: 0,
				messages: expect.arrayContaining([{ role: "system", content: systemPrompt }]),
				stream: true,
				stream_options: { include_usage: true },
			}),
			undefined,
		)
	})
})
