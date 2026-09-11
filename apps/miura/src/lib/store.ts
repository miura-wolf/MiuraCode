import fs from "fs"
import path from "path"
import { randomUUID } from "node:crypto"
import { DatabaseSync } from "node:sqlite"

import { ensureConfigDir, getConfigDir } from "./config.js"

export type MessageRole = "user" | "assistant" | "system"

export interface SessionRow {
	id: string
	title: string
	model: string
	created_at: string
	updated_at: string
	message_count: number
}

export interface MessageRow {
	id: number
	session_id: string
	role: MessageRole
	content: string
	reasoning: string
	created_at: string
}

export interface MessageSearchHit {
	session_id: string
	title: string
	updated_at: string
	snippet: string
}

/** Ruta por defecto de la BD: ~/.miuracode/miura.db */
export function defaultDbPath(): string {
	return path.join(getConfigDir(), "miura.db")
}

/** Frase FTS5 segura: la query se entrecomilla para que guiones/paréntesis
 * del texto no se interpreten como sintaxis FTS. */
export function ftsPhrase(query: string): string {
	return `"${query.replace(/"/g, '""')}"`
}

const SCHEMA = `
CREATE TABLE IF NOT EXISTS sessions (
	id TEXT PRIMARY KEY,
	title TEXT NOT NULL DEFAULT '',
	model TEXT NOT NULL DEFAULT '',
	created_at TEXT NOT NULL,
	updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
	role TEXT NOT NULL,
	content TEXT NOT NULL DEFAULT '',
	reasoning TEXT NOT NULL DEFAULT '',
	created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5 (
	content, session_id UNINDEXED, content='messages', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
	INSERT INTO messages_fts (rowid, content, session_id)
	VALUES (new.id, new.content, new.session_id);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
	INSERT INTO messages_fts (messages_fts, rowid, content, session_id)
	VALUES ('delete', old.id, old.content, old.session_id);
END;
CREATE TABLE IF NOT EXISTS memory (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	key TEXT NOT NULL UNIQUE,
	value TEXT NOT NULL,
	source TEXT NOT NULL DEFAULT 'manual',
	created_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5 (
	key, value, content='memory', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory BEGIN
	INSERT INTO memory_fts (rowid, key, value) VALUES (new.id, new.key, new.value);
END;
CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory BEGIN
	INSERT INTO memory_fts (memory_fts, rowid, key, value) VALUES ('delete', old.id, old.key, old.value);
	INSERT INTO memory_fts (rowid, key, value) VALUES (new.id, new.key, new.value);
END;
CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory BEGIN
	INSERT INTO memory_fts (memory_fts, rowid, key, value) VALUES ('delete', old.id, old.key, old.value);
END;
`

/**
 * Store persistente de sesiones y mensajes sobre SQLite (node:sqlite) con
 * índice FTS5 — persistencia propia ligera, sin dependencias nativas ni
 * servicios externos. Todo síncrono: SQLite local es instantáneo.
 */
export class Store {
	private db: DatabaseSync

	constructor(dbPath: string = defaultDbPath()) {
		fs.mkdirSync(path.dirname(dbPath), { recursive: true })
		ensureConfigDir()
		this.db = new DatabaseSync(dbPath)
		this.db.exec("PRAGMA journal_mode = WAL;")
		this.db.exec("PRAGMA foreign_keys = ON;")
		this.db.exec(SCHEMA)
	}

	get database(): DatabaseSync {
		return this.db
	}

	close(): void {
		this.db.close()
	}

	// -------------------------------------------------------------
	// Sesiones
	// -------------------------------------------------------------

	private toSessionRow(row: Record<string, unknown>): SessionRow {
		return {
			id: String(row.id ?? ""),
			title: String(row.title ?? ""),
			model: String(row.model ?? ""),
			created_at: String(row.created_at ?? ""),
			updated_at: String(row.updated_at ?? ""),
			message_count: Number(row.message_count ?? 0),
		}
	}

	createSession(model = "", title = ""): SessionRow {
		const id = randomUUID()
		const now = new Date().toISOString()
		this.db
			.prepare("INSERT INTO sessions (id, title, model, created_at, updated_at) VALUES (?, ?, ?, ?, ?)")
			.run(id, title, model, now, now)
		return { id, title, model, created_at: now, updated_at: now, message_count: 0 }
	}

	listSessions(limit = 20): SessionRow[] {
		const rows = this.db
			.prepare(
				`SELECT s.id AS id, s.title AS title, s.model AS model, s.created_at AS created_at,
					s.updated_at AS updated_at, COUNT(m.id) AS message_count
				 FROM sessions s LEFT JOIN messages m ON m.session_id = s.id
				 GROUP BY s.id ORDER BY s.updated_at DESC LIMIT ?`,
			)
			.all(limit) as Record<string, unknown>[]
		return rows.map((row) => this.toSessionRow(row))
	}

	private sessionById(id: string): SessionRow {
		const row = this.db
			.prepare(
				`SELECT s.id AS id, s.title AS title, s.model AS model, s.created_at AS created_at,
					s.updated_at AS updated_at, COUNT(m.id) AS message_count
				 FROM sessions s LEFT JOIN messages m ON m.session_id = s.id
				 WHERE s.id = ? GROUP BY s.id`,
			)
			.get(id) as Record<string, unknown> | undefined
		if (!row) {
			throw new Error("sesión no encontrada")
		}
		return this.toSessionRow(row)
	}

	/** Resuelve por UUID completo o por prefijo único. */
	resolveSession(idOrPrefix: string): SessionRow {
		try {
			return this.sessionById(idOrPrefix)
		} catch {
			const matches = this.listSessions(1000).filter((s) => s.id.startsWith(idOrPrefix))
			const match = matches.length === 1 ? matches.at(0) : undefined
			if (match) {
				return this.sessionById(match.id)
			}
			if (matches.length === 0) {
				throw new Error(`sesión no encontrada: ${idOrPrefix}`)
			}
			throw new Error(`prefijo ambiguo (${matches.length} coinciden): ${idOrPrefix}`)
		}
	}

	/** La sesión más reciente (para --continue). */
	latestSession(): SessionRow | null {
		const all = this.listSessions(1)
		return all[0] ?? null
	}

	deleteSession(id: string): boolean {
		const info = this.db.prepare("DELETE FROM sessions WHERE id = ?").run(id)
		return Number(info.changes) > 0
	}

	/** Actualiza el título explícitamente (/title). */
	renameSession(id: string, title: string): void {
		this.db.prepare("UPDATE sessions SET title = ? WHERE id = ?").run(title, id)
	}

	/** Cambia el modelo activo de una sesión (/model). */
	setSessionModel(id: string, model: string): void {
		this.db.prepare("UPDATE sessions SET model = ? WHERE id = ?").run(model, id)
	}

	// -------------------------------------------------------------
	// Mensajes
	// -------------------------------------------------------------

	appendMessage(sessionId: string, role: MessageRole, content: string, reasoning = ""): MessageRow {
		const now = new Date().toISOString()
		const info = this.db
			.prepare("INSERT INTO messages (session_id, role, content, reasoning, created_at) VALUES (?, ?, ?, ?, ?)")
			.run(sessionId, role, content, reasoning, now)
		this.db.prepare("UPDATE sessions SET updated_at = ? WHERE id = ?").run(now, sessionId)
		if (role === "user") {
			this.db
				.prepare("UPDATE sessions SET title = ? WHERE id = ? AND title = ''")
				.run(content.slice(0, 60), sessionId)
		}
		return {
			id: Number(info.lastInsertRowid),
			session_id: sessionId,
			role,
			content,
			reasoning,
			created_at: now,
		}
	}

	getMessages(sessionId: string): MessageRow[] {
		const rows = this.db
			.prepare("SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC")
			.all(sessionId) as Record<string, unknown>[]
		return rows.map((row) => ({
			id: Number(row.id ?? 0),
			session_id: String(row.session_id ?? ""),
			role: String(row.role ?? "user") as MessageRole,
			content: String(row.content ?? ""),
			reasoning: String(row.reasoning ?? ""),
			created_at: String(row.created_at ?? ""),
		}))
	}

	/** Búsqueda FTS5 sobre todo el historial con snippet resaltado. */
	searchMessages(query: string, limit = 10): MessageSearchHit[] {
		if (!query.trim()) {
			return []
		}
		const rows = this.db
			.prepare(
				`SELECT f.session_id AS session_id, s.title AS title, s.updated_at AS updated_at,
					snippet(messages_fts, 0, '[', ']', '…', 18) AS snippet
				 FROM messages_fts f JOIN sessions s ON s.id = f.session_id
				 WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?`,
			)
			.all(ftsPhrase(query), limit) as Record<string, unknown>[]
		return rows.map((row) => ({
			session_id: String(row.session_id ?? ""),
			title: String(row.title ?? ""),
			updated_at: String(row.updated_at ?? ""),
			snippet: String(row.snippet ?? ""),
		}))
	}
}
