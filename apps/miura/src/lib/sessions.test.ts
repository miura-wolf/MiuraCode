import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it } from "vitest"

import { MemoryStore } from "@/lib/memory.js"
import { buildChatContext } from "@/lib/sessions.js"
import { Store } from "@/lib/store.js"

let tmpDir: string

beforeEach(() => {
	tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "miura-ctx-"))
	process.env.MIURA_CONFIG_DIR = tmpDir
})

afterEach(() => {
	delete process.env.MIURA_CONFIG_DIR
	fs.rmSync(tmpDir, { recursive: true, force: true })
})

describe("buildChatContext — contexto del turno", () => {
	it("inyecta system prompt + memoria como system y mantiene la historia", () => {
		const store = new Store()
		const memory = new MemoryStore(store.database)
		const s = store.createSession()
		memory.addMemory("nombre", "AnZa")
		store.appendMessage(s.id, "user", "hola")
		store.appendMessage(s.id, "assistant", "¿qué tal?")

		const messages = buildChatContext(store, memory, s.id, "Eres miura, directo y técnico.")
		expect(messages[0]?.role).toBe("system")
		expect(messages[0]?.content).toContain("Eres miura")
		expect(messages[0]?.content).toContain("nombre: AnZa")
		expect(messages[1]).toEqual({ role: "user", content: "hola" })
		expect(messages[2]).toEqual({ role: "assistant", content: "¿qué tal?" })
		store.close()
	})

	it("sin system prompt ni memoria no añade mensaje system", () => {
		const store = new Store()
		const s = store.createSession()
		store.appendMessage(s.id, "user", "hola")
		const messages = buildChatContext(store, memoryEmpty(store), s.id, "")
		expect(messages).toHaveLength(1)
		expect(messages[0]?.role).toBe("user")
		store.close()
	})

	it("limita la historia a los últimos MAX_CONTEXT_MESSAGES", () => {
		const store = new Store()
		const s = store.createSession()
		for (let i = 0; i < 60; i++) {
			store.appendMessage(s.id, "user", `mensaje número ${i}`)
		}
		const messages = buildChatContext(store, memoryEmpty(store), s.id, "")
		expect(messages).toHaveLength(40)
		expect(messages.at(-1)?.content).toBe("mensaje número 59")
		store.close()
	})
})

function memoryEmpty(store: Store): MemoryStore {
	return new MemoryStore(store.database)
}
