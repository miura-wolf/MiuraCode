import fs from "fs"
import os from "os"
import path from "path"
import { afterEach, beforeEach, describe, expect, it } from "vitest"

import { MemoryStore } from "@/lib/memory.js"
import { Store } from "@/lib/store.js"

let tmpDir: string

beforeEach(() => {
	tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "miura-test-"))
	process.env.MIURA_CONFIG_DIR = tmpDir
})

afterEach(() => {
	delete process.env.MIURA_CONFIG_DIR
	fs.rmSync(tmpDir, { recursive: true, force: true })
})

describe("Store — sesiones y mensajes", () => {
	it("crea, lista, resuelve por prefijo y borra sesiones", () => {
		const store = new Store()
		const a = store.createSession("miura-fast", "Sesión A")
		store.createSession("miura-fast", "Sesión B")
		const rows = store.listSessions()
		expect(rows.length).toBe(2)
		expect(rows[0]?.title).toBe("Sesión B")

		const resolved = store.resolveSession(a.id.slice(0, 6))
		expect(resolved.id).toBe(a.id)
		expect(store.deleteSession(a.id)).toBe(true)
		expect(store.listSessions().length).toBe(1)
		store.close()
	})

	it("asigna título automático con el primer mensaje del usuario", () => {
		const store = new Store()
		const s = store.createSession()
		store.appendMessage(s.id, "user", "Explícame el patrón reactor en Node")
		const rows = store.listSessions()
		expect(rows[0]?.title).toBe("Explícame el patrón reactor en Node")
		store.close()
	})

	it("persiste y recupera mensajes con razonamiento", () => {
		const store = new Store()
		const s = store.createSession()
		store.appendMessage(s.id, "user", "hola")
		store.appendMessage(s.id, "assistant", "que tal", "porque el usuario saludó")
		const msgs = store.getMessages(s.id)
		expect(msgs).toHaveLength(2)
		expect(msgs[1]?.reasoning).toBe("porque el usuario saludó")
		store.close()
	})

	it("busca en el historial con FTS5 y snippet", () => {
		const store = new Store()
		const a = store.createSession()
		const b = store.createSession()
		store.appendMessage(a.id, "user", "El proxy Atomic AI descompone tareas atómicas")
		store.appendMessage(b.id, "user", "Otra conversación sobre recetas de pizza")
		const hits = store.searchMessages("tareas atómicas")
		expect(hits).toHaveLength(1)
		expect(hits[0]?.session_id).toBe(a.id)
		expect(hits[0]?.snippet).toContain("tareas")
		store.close()
	})

	it("el prefijo ambiguo lanza error claro", () => {
		const store = new Store()
		store.createSession()
		store.createSession()
		expect(() => store.resolveSession("x")).toThrow(/no encontrada|prefijo/)
		store.close()
	})
})

describe("MemoryStore — memoria persistente", () => {
	it("hace upsert por clave y la lista", () => {
		const store = new Store()
		const memory = new MemoryStore(store.database)
		memory.addMemory("lenguaje", "TypeScript")
		memory.addMemory("lenguaje", "TypeScript estricto")
		const rows = memory.listMemory()
		expect(rows).toHaveLength(1)
		expect(rows[0]?.value).toBe("TypeScript estricto")
		store.close()
	})

	it("busca memoria con FTS5", () => {
		const store = new Store()
		const memory = new MemoryStore(store.database)
		memory.addMemory("editor", "VS Code con extensión Roo")
		const hits = memory.searchMemory("VS Code")
		expect(hits).toHaveLength(1)
		expect(hits[0]?.key).toBe("editor")
		store.close()
	})

	it("borra memoria por clave", () => {
		const store = new Store()
		const memory = new MemoryStore(store.database)
		memory.addMemory("temporal", "dato")
		expect(memory.deleteMemory("temporal")).toBe(true)
		expect(memory.deleteMemory("temporal")).toBe(false)
		expect(memory.listMemory()).toHaveLength(0)
		store.close()
	})
})
