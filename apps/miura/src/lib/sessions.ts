import type { ChatMessage } from "./client.js"
import type { Store } from "./store.js"
import { MemoryStore } from "./memory.js"

/** Máximo de mensajes de historia que se envían al modelo por turno. */
export const MAX_CONTEXT_MESSAGES = 40

/**
 * Construye el contexto del turno: [system prompt] + [memoria persistente] +
 * últimos mensajes de la sesión. El mensaje nuevo del usuario lo añade el
 * caller. La memoria viaja como bloque system para que el modelo la trate
 * como hecho, no como conversación.
 */
export function buildChatContext(
	store: Store,
	memory: MemoryStore,
	sessionId: string,
	systemPrompt: string,
	memoryLimit = 10,
): ChatMessage[] {
	const messages: ChatMessage[] = []

	const memories = memory.listMemory(memoryLimit)
	if (systemPrompt || memories.length > 0) {
		const blocks: string[] = []
		if (systemPrompt) {
			blocks.push(systemPrompt)
		}
		if (memories.length > 0) {
			const lines = memories
				.slice()
				.reverse()
				.map((m) => `- ${m.key}: ${m.value}`)
				.join("\n")
			blocks.push(`Memoria persistente del usuario (hechos confirmados):\n${lines}`)
		}
		messages.push({ role: "system", content: blocks.join("\n\n") })
	}

	const history = store.getMessages(sessionId).slice(-MAX_CONTEXT_MESSAGES)
	for (const m of history) {
		if (m.role !== "system" && m.content) {
			messages.push({ role: m.role, content: m.content })
		}
	}
	return messages
}
