import { DatabaseSync } from "node:sqlite"

import { ftsPhrase } from "./store.js"

export interface MemoryRow {
	id: number
	key: string
	value: string
	source: string
	created_at: string
}

export interface MemorySearchHit extends MemoryRow {
	snippet: string
}

/**
 * Memoria persistente entre sesiones (patrón "Engram-lite" propio, sobre la
 * misma SQLite del store): hechos clave=valor que el TUI inyecta como system
 * context en cada turno. Cero servicios externos, cero embeddings — FTS5.
 */
export class MemoryStore {
	constructor(private readonly db: DatabaseSync) {}

	private mapRow(row: Record<string, unknown>): MemoryRow {
		return {
			id: Number(row.id ?? 0),
			key: String(row.key ?? ""),
			value: String(row.value ?? ""),
			source: String(row.source ?? "manual"),
			created_at: String(row.created_at ?? ""),
		}
	}

	/** Inserta o actualiza (upsert por key): la memoria es clave=valor única. */
	addMemory(key: string, value: string, source = "manual"): MemoryRow {
		const now = new Date().toISOString()
		const info = this.db
			.prepare(
				`INSERT INTO memory (key, value, source, created_at) VALUES (?, ?, ?, ?)
				 ON CONFLICT(key) DO UPDATE SET value = excluded.value, created_at = excluded.created_at`,
			)
			.run(key, value, source, now)
		const id = Number(info.lastInsertRowid)
		const row = this.db.prepare("SELECT * FROM memory WHERE id = ?").get(id) as Record<string, unknown>
		return this.mapRow(row)
	}

	listMemory(limit = 20): MemoryRow[] {
		const rows = this.db.prepare("SELECT * FROM memory ORDER BY id DESC LIMIT ?").all(limit) as Record<
			string,
			unknown
		>[]
		return rows.map((row) => this.mapRow(row))
	}

	searchMemory(query: string, limit = 10): MemorySearchHit[] {
		if (!query.trim()) {
			return []
		}
		const rows = this.db
			.prepare(
				`SELECT m.*, snippet(memory_fts, 1, '[', ']', '…', 14) AS value_snippet
				 FROM memory_fts f JOIN memory m ON m.id = f.rowid
				 WHERE memory_fts MATCH ? ORDER BY rank LIMIT ?`,
			)
			.all(ftsPhrase(query), limit) as Record<string, unknown>[]
		return rows.map((row) => ({
			...this.mapRow(row),
			snippet: String(row.value_snippet ?? ""),
		}))
	}

	deleteMemory(key: string): boolean {
		const info = this.db.prepare("DELETE FROM memory WHERE key = ?").run(key)
		return Number(info.changes) > 0
	}
}
