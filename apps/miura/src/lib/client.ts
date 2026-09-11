export interface ChatMessage {
	role: "system" | "user" | "assistant"
	content: string
}

export interface StreamResult {
	content: string
	reasoning: string
	finishReason: string | null
}

export interface StreamOptions {
	proxyUrl: string
	model: string
	messages: ChatMessage[]
	temperature?: number
	signal?: AbortSignal
	onContent?: (chunk: string) => void
	onReasoning?: (chunk: string) => void
}

export class MiuraApiError extends Error {
	constructor(
		message: string,
		readonly status?: number,
	) {
		super(message)
		this.name = "MiuraApiError"
	}
}

function apiUrl(proxyUrl: string, pathname: string): string {
	return `${proxyUrl.replace(/\/+$/, "")}${pathname}`
}

/**
 * Streaming de chat contra un endpoint OpenAI-compatible (el proxy Atomic AI
 * o cualquier /v1/chat/completions). Acumula `delta.content` y
 * `delta.reasoning_content` (el proxy los expone con EXPOSE_REASONING_CONTENT).
 */
export async function streamChat(options: StreamOptions): Promise<StreamResult> {
	const body: Record<string, unknown> = {
		model: options.model,
		messages: options.messages,
		stream: true,
	}
	if (typeof options.temperature === "number") {
		body.temperature = options.temperature
	}

	const res = await fetch(apiUrl(options.proxyUrl, "/v1/chat/completions"), {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(body),
		signal: options.signal,
	})

	if (!res.ok) {
		const text = await res.text().catch(() => "")
		throw new MiuraApiError(`HTTP ${res.status}: ${text.slice(0, 300)}`, res.status)
	}
	if (!res.body) {
		throw new MiuraApiError("la respuesta no trae cuerpo de stream")
	}

	let content = ""
	let reasoning = ""
	let finishReason: string | null = null
	const reader = res.body.getReader()
	const decoder = new TextDecoder()
	let buffer = ""

	const handleLine = (line: string) => {
		if (!line.startsWith("data:")) {
			return
		}
		const payload = line.slice(5).trim()
		if (payload === "[DONE]") {
			return
		}
		try {
			const json = JSON.parse(payload) as {
				choices?: Array<{
					delta?: { content?: unknown; reasoning_content?: unknown }
					finish_reason?: string | null
				}>
				error?: { message?: string }
			}
			if (json.error) {
				throw new MiuraApiError(json.error.message ?? "error del upstream")
			}
			const choice = json.choices?.[0]
			const delta = choice?.delta ?? {}
			if (typeof delta.content === "string" && delta.content) {
				content += delta.content
				options.onContent?.(delta.content)
			}
			if (typeof delta.reasoning_content === "string" && delta.reasoning_content) {
				reasoning += delta.reasoning_content
				options.onReasoning?.(delta.reasoning_content)
			}
			if (choice?.finish_reason) {
				finishReason = choice.finish_reason
			}
		} catch (error) {
			if (error instanceof MiuraApiError) {
				throw error
			}
			// Chunks no-JSON (comentarios keep-alive, ruido): se ignoran.
		}
	}

	while (true) {
		const { done, value } = await reader.read()
		if (done) {
			break
		}
		buffer += decoder.decode(value, { stream: true })
		let newlineIndex: number
		while ((newlineIndex = buffer.indexOf("\n")) >= 0) {
			const line = buffer.slice(0, newlineIndex).trim()
			buffer = buffer.slice(newlineIndex + 1)
			handleLine(line)
		}
	}
	if (buffer.trim()) {
		handleLine(buffer.trim())
	}

	return { content, reasoning, finishReason }
}

/** GET /v1/models del proxy (incluye los carriles passthrough, p. ej. miura-fast). */
export async function listModels(proxyUrl: string): Promise<string[]> {
	const res = await fetch(apiUrl(proxyUrl, "/v1/models"))
	if (!res.ok) {
		const text = await res.text().catch(() => "")
		throw new MiuraApiError(`HTTP ${res.status}: ${text.slice(0, 300)}`, res.status)
	}
	const json = (await res.json()) as { data?: Array<{ id?: string }> }
	return (json.data ?? []).map((m) => m.id ?? "").filter((id): id is string => Boolean(id))
}
