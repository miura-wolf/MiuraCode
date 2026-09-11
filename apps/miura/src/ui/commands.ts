import type { SessionRow, MessageSearchHit } from "@/lib/store.js"
import type { MemorySearchHit } from "@/lib/memory.js"

export interface SlashCommand {
	name: string
	description: string
	/** Ejemplo de uso que se muestra en la ayuda. */
	usage: string
}

/** Comandos slash soportados por el TUI dentro de una sesión. */
export const SLASH_COMMANDS: SlashCommand[] = [
	{ name: "/help", description: "muestra esta ayuda", usage: "/help" },
	{ name: "/exit", description: "sale del TUI", usage: "/exit" },
	{ name: "/new", description: "abandona la sesión actual y crea otra", usage: "/new" },
	{ name: "/model", description: "cambia el modelo/carril del turno", usage: "/model <nombre>" },
	{ name: "/title", description: "renombra la sesión actual", usage: "/title <texto>" },
	{ name: "/search", description: "busca en el historial de todas las sesiones (FTS5)", usage: "/search <texto>" },
	{ name: "/memory", description: "lista la memoria persistente", usage: "/memory" },
	{ name: "/remember", description: "guarda un hecho clave=valor en la memoria", usage: "/remember clave=valor" },
	{ name: "/forget", description: "borra una clave de la memoria", usage: "/forget clave" },
	{ name: "/sessions", description: "lista sesiones recientes", usage: "/sessions" },
]

/** Una fila del selector: sesión, hit de búsqueda o hit de memoria. */
export type PickerRow =
	| { kind: "session"; row: SessionRow }
	| { kind: "search"; hit: MessageSearchHit }
	| { kind: "memory"; hit: MemorySearchHit }

/** Render de una fila del selector en texto plano (sin colores). */
export function renderPickerRow(row: PickerRow): string {
	if (row.kind === "session") {
		const s = row.row
		const date = s.updated_at.slice(0, 16).replace("T", " ")
		return `${s.id.slice(0, 8)}  ${date}  ${s.title || "(sin título)"}  [${s.message_count} msg]`
	}
	if (row.kind === "search") {
		return `${row.hit.session_id.slice(0, 8)}  ${row.hit.snippet}`
	}
	return `mem #${row.hit.id}  ${row.hit.key}: ${row.hit.snippet}`
}

/** Parsea "/remember clave=valor" → { key, value } o null si el formato no vale. */
export function parseRemember(input: string): { key: string; value: string } | null {
	const sep = input.indexOf("=")
	if (sep <= 0) {
		return null
	}
	return {
		key: input.slice(0, sep).trim(),
		value: input.slice(sep + 1).trim(),
	}
}
