import { describe, expect, it } from "vitest"

import { parseRemember, renderPickerRow, SLASH_COMMANDS } from "@/ui/commands.js"

describe("commands — slash commands y helpers de render", () => {
	it("registra los comandos esperados", () => {
		const names = SLASH_COMMANDS.map((c) => c.name)
		expect(names).toContain("/help")
		expect(names).toContain("/model")
		expect(names).toContain("/remember")
		expect(names).toContain("/search")
	})

	it("parsea /remember clave=valor", () => {
		expect(parseRemember("idioma=español")).toEqual({ key: "idioma", value: "español" })
		expect(parseRemember("clave con espacios = valor largo")).toEqual({
			key: "clave con espacios",
			value: "valor largo",
		})
	})

	it("rechaza /remember mal formado", () => {
		expect(parseRemember("")).toBeNull()
		expect(parseRemember("sin-igual")).toBeNull()
		expect(parseRemember("=novalue")).toBeNull()
	})

	it("renderiza filas del selector", () => {
		const session = renderPickerRow({
			kind: "session",
			row: {
				id: "abcdefgh-1234",
				title: "mi sesión",
				model: "miura-fast",
				created_at: "2026-10-09T12:00:00.000Z",
				updated_at: "2026-10-09T12:00:00.000Z",
				message_count: 5,
			},
		})
		expect(session).toContain("abcdefgh")
		expect(session).toContain("mi sesión")
		expect(session).toContain("[5 msg]")

		const search = renderPickerRow({
			kind: "search",
			hit: { session_id: "abcdefgh-1234", title: "", updated_at: "", snippet: "…proxy [atómico]…" },
		})
		expect(search).toContain("abcdefgh")
		expect(search).toContain("[atómico]")

		const memory = renderPickerRow({
			kind: "memory",
			hit: { id: 3, key: "editor", value: "VS Code", source: "manual", created_at: "", snippet: "VS [Code]" },
		})
		expect(memory).toContain("editor")
		expect(memory).toContain("VS [Code]")
	})
})
