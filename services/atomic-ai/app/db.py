from __future__ import annotations

import time
from typing import Any, Optional

import aiosqlite

from .config import settings

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id           TEXT PRIMARY KEY,
    checkpoint_hash      TEXT,
    checkpoint_len       INTEGER,
    goal_ctx             TEXT,
    model                TEXT,
    tools                TEXT,
    tool_choice          TEXT,
    root                 TEXT,
    leaves               TEXT,
    results              TEXT,
    pending_phase        TEXT,
    pending_leaf_index   INTEGER,
    pending_tool_calls   TEXT,
    pending_conversation TEXT,
    turn_history         TEXT,
    tool_round_count     INTEGER DEFAULT 0,
    updated_at           REAL
);

CREATE TABLE IF NOT EXISTS knowledge_base (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'general',
    content     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    source      TEXT NOT NULL DEFAULT 'manual',
    updated_at  REAL,
    vector_updated_at REAL,
    parent_id   INTEGER,
    version     INTEGER NOT NULL DEFAULT 1
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_base_fts USING fts5(
    description,
    content
);

CREATE TABLE IF NOT EXISTS knowledge_vec (
    knowledge_id INTEGER PRIMARY KEY REFERENCES knowledge_base(id) ON DELETE CASCADE,
    dim          INTEGER NOT NULL,
    vec          BLOB NOT NULL,
    created_at   REAL NOT NULL
);
"""

# F5 — columnas de metadatos de knowledge_base. Se listan aquí para la
# migración idempotente de bases creadas antes de F5 (ALTER TABLE ADD COLUMN).
_KNOWLEDGE_METADATA_COLUMNS = [
    ("source", "TEXT NOT NULL DEFAULT 'manual'"),
    ("updated_at", "REAL"),
    ("vector_updated_at", "REAL"),
    ("parent_id", "INTEGER"),
    ("version", "INTEGER NOT NULL DEFAULT 1"),
]


async def _migrate_knowledge_metadata(conn: aiosqlite.Connection) -> None:
    """F5: añade las columnas de metadatos a knowledge_base si no existen.
    Idempotente y barata (un PRAGMA table_info + comprobaciones), segura para
    bases creadas antes de F5: las filas existentes reciben los defaults."""
    cursor = await conn.execute("PRAGMA table_info(knowledge_base)")
    rows = await cursor.fetchall()
    existing = {row[1] for row in rows}
    added = False
    for name, coltype in _KNOWLEDGE_METADATA_COLUMNS:
        if name not in existing:
            await conn.execute(f"ALTER TABLE knowledge_base ADD COLUMN {name} {coltype}")
            added = True
    if added:
        await conn.commit()


async def _connect() -> aiosqlite.Connection:
    """Abre una conexión a la base de datos SQLite configurada y asegura que
    el esquema exista. Cada llamada abre su propia conexión para evitar
    problemas de concurrencia en entornos multihilo/async."""
    conn = await aiosqlite.connect(settings.database_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA busy_timeout = 5000")
    await conn.executescript(_SCHEMA_SQL)
    await _migrate_knowledge_metadata(conn)
    return conn


async def init_db(db_path: Optional[str] = None) -> None:
    """Crea/actualiza el esquema de la base de datos."""
    path = db_path if db_path is not None else settings.database_path
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.executescript(_SCHEMA_SQL)
    await _migrate_knowledge_metadata(conn)
    await conn.commit()
    await conn.close()


# ------------------------------------------------------------------
# Sesiones
# ------------------------------------------------------------------

async def save_session(session_id: str, data: dict[str, Any]) -> None:
    """Persista o actualiza el estado de una sesión en la tabla ``sessions``."""
    conn = await _connect()
    try:
        await conn.execute(
            """
            INSERT INTO sessions (
                session_id, checkpoint_hash, checkpoint_len, goal_ctx,
                model, tools, tool_choice, root, leaves, results,
                pending_phase, pending_leaf_index, pending_tool_calls,
                pending_conversation, turn_history, tool_round_count,
                updated_at
            ) VALUES (
                :session_id, :checkpoint_hash, :checkpoint_len, :goal_ctx,
                :model, :tools, :tool_choice, :root, :leaves, :results,
                :pending_phase, :pending_leaf_index, :pending_tool_calls,
                :pending_conversation, :turn_history, :tool_round_count,
                :updated_at
            )
            ON CONFLICT(session_id) DO UPDATE SET
                checkpoint_hash      = excluded.checkpoint_hash,
                checkpoint_len       = excluded.checkpoint_len,
                goal_ctx             = excluded.goal_ctx,
                model                = excluded.model,
                tools                = excluded.tools,
                tool_choice          = excluded.tool_choice,
                root                 = excluded.root,
                leaves               = excluded.leaves,
                results              = excluded.results,
                pending_phase        = excluded.pending_phase,
                pending_leaf_index   = excluded.pending_leaf_index,
                pending_tool_calls   = excluded.pending_tool_calls,
                pending_conversation = excluded.pending_conversation,
                turn_history         = excluded.turn_history,
                tool_round_count     = excluded.tool_round_count,
                updated_at           = excluded.updated_at
            """,
            {
                **data,
                "updated_at": data.get("updated_at") or time.time(),
            },
        )
        await conn.commit()
    finally:
        await conn.close()


async def load_session(session_id: str) -> Optional[dict[str, Any]]:
    """Carga el estado de una sesión por su ``session_id``."""
    conn = await _connect()
    try:
        cursor = await conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        await conn.close()


async def list_sessions() -> list[dict[str, Any]]:
    """Devuelve todas las sesiones almacenadas."""
    conn = await _connect()
    try:
        cursor = await conn.execute("SELECT * FROM sessions")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def delete_session(session_id: str) -> None:
    """Elimina una sesión de la base de datos."""
    conn = await _connect()
    try:
        await conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        await conn.commit()
    finally:
        await conn.close()


async def clear_sessions() -> None:
    """Elimina todas las sesiones (usado principalmente en tests)."""
    conn = await _connect()
    try:
        await conn.execute("DELETE FROM sessions")
        await conn.commit()
    finally:
        await conn.close()


# ------------------------------------------------------------------
# Base de conocimiento (RAG)
# ------------------------------------------------------------------

async def save_knowledge(
    description: str,
    content: str,
    category: str = "general",
    source: str = "manual",
    parent_id: Optional[int] = None,
) -> int:
    """Guarda un snippet de código/solución reutilizable en la base de
    conocimiento. Devuelve el ``id`` asignado. ``source`` registra la
    procedencia (manual/auto_learn/admin) y ``parent_id`` permite relacionar
    entradas entre sí (grafo de conocimiento, F5)."""
    now = time.time()
    conn = await _connect()
    try:
        cursor = await conn.execute(
            "INSERT INTO knowledge_base "
            "(description, category, content, created_at, source, updated_at, parent_id, version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (description, category, content, now, source, now, parent_id),
        )
        row_id: int = cursor.lastrowid
        await conn.execute(
            "INSERT INTO knowledge_base_fts(rowid, description, content) VALUES (?, ?, ?)",
            (row_id, description, content),
        )
        await conn.commit()
        return row_id
    finally:
        await conn.close()


async def search_knowledge(query: str, limit: int = 3) -> list[dict[str, Any]]:
    """Busca coincidencias de texto completo en la base de conocimiento usando
    FTS5. Devuelve una lista de diccionarios con ``description``, ``category``,
    ``content`` y ``created_at``, ordenados por relevancia (rank)."""
    if not query or not query.strip():
        return []
    conn = await _connect()
    try:
        escaped = query.replace("'", "''")
        cursor = await conn.execute(
            """
            SELECT
                kb.id,
                kb.description,
                kb.category,
                kb.content,
                kb.created_at
            FROM knowledge_base_fts fts
            JOIN knowledge_base kb ON kb.id = fts.rowid
            WHERE knowledge_base_fts MATCH ?
            ORDER BY fts.rank
            LIMIT ?
            """,
            (escaped, limit),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def clear_knowledge() -> None:
    """Elimina todos los snippets de la base de conocimiento (usado en tests)."""
    conn = await _connect()
    try:
        await conn.execute("DELETE FROM knowledge_vec")
        await conn.execute("DELETE FROM knowledge_base_fts")
        await conn.execute("DELETE FROM knowledge_base")
        await conn.commit()
    finally:
        await conn.close()


async def init_knowledge(
    seed: list[dict[str, str]] | None = None
) -> None:
    """Utility para sembrar la base de conocimiento (útil en tests y demos)."""
    if not seed:
        return
    conn = await _connect()
    try:
        for item in seed:
            cursor = await conn.execute(
                "INSERT INTO knowledge_base (description, category, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    item["description"],
                    item.get("category", "general"),
                    item["content"],
                    time.time(),
                ),
            )
            row_id: int = cursor.lastrowid
            await conn.execute(
                "INSERT INTO knowledge_base_fts(rowid, description, content) VALUES (?, ?, ?)",
                (row_id, item["description"], item["content"]),
            )
        await conn.commit()
    finally:
        await conn.close()


# ------------------------------------------------------------------
# Conocimiento: CRUD admin y soporte de vectores para búsqueda híbrida
# ------------------------------------------------------------------

async def delete_knowledge(knowledge_id: int) -> bool:
    """Elimina una entrada (fila + índice FTS + vector). True si existía."""
    conn = await _connect()
    try:
        await conn.execute("DELETE FROM knowledge_vec WHERE knowledge_id = ?", (knowledge_id,))
        await conn.execute("DELETE FROM knowledge_base_fts WHERE rowid = ?", (knowledge_id,))
        cursor = await conn.execute("DELETE FROM knowledge_base WHERE id = ?", (knowledge_id,))
        deleted = bool(cursor.rowcount)
        await conn.commit()
        return deleted
    finally:
        await conn.close()


async def knowledge_description_count(description_normalized: str) -> int:
    """Cuenta entradas cuya descripción coincide exactamente (anti-duplicado)."""
    conn = await _connect()
    try:
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE description = ?",
            (description_normalized,),
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0
    finally:
        await conn.close()


async def list_knowledge(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Lista entradas recientes sin criterio de búsqueda (para curar la KB)."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    conn = await _connect()
    try:
        cursor = await conn.execute(
            """
            SELECT kb.id, kb.description, kb.category, kb.content, kb.created_at,
                   kb.source, kb.updated_at, kb.vector_updated_at, kb.parent_id, kb.version,
                   (kv.knowledge_id IS NOT NULL) AS has_vector
            FROM knowledge_base kb
            LEFT JOIN knowledge_vec kv ON kv.knowledge_id = kb.id
            ORDER BY kb.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def knowledge_stats() -> dict[str, Any]:
    """Conteo total, desglose por categoría y cuántas entradas tienen vector."""
    conn = await _connect()
    try:
        total_row = await (await conn.execute("SELECT COUNT(*) FROM knowledge_base")).fetchone()
        vec_row = await (await conn.execute("SELECT COUNT(*) FROM knowledge_vec")).fetchone()
        cat_cursor = await conn.execute(
            "SELECT category, COUNT(*) AS n FROM knowledge_base GROUP BY category ORDER BY n DESC"
        )
        by_category = {r["category"]: r["n"] for r in await cat_cursor.fetchall()}
        src_cursor = await conn.execute(
            "SELECT source, COUNT(*) AS n FROM knowledge_base GROUP BY source ORDER BY n DESC"
        )
        by_source = {r["source"]: r["n"] for r in await src_cursor.fetchall()}
        return {
            "total": int(total_row[0]) if total_row else 0,
            "with_vector": int(vec_row[0]) if vec_row else 0,
            "by_category": by_category,
            "by_source": by_source,
        }
    finally:
        await conn.close()


async def upsert_knowledge_vec(knowledge_id: int, dim: int, blob: bytes) -> None:
    """Guarda o actualiza el vector de una entrada y marca en knowledge_base
    cuándo se vectorizó (``vector_updated_at``, F5)."""
    now = time.time()
    conn = await _connect()
    try:
        await conn.execute(
            """
            INSERT INTO knowledge_vec (knowledge_id, dim, vec, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(knowledge_id) DO UPDATE SET
                dim = excluded.dim,
                vec = excluded.vec,
                created_at = excluded.created_at
            """,
            (knowledge_id, dim, blob, now),
        )
        await conn.execute(
            "UPDATE knowledge_base SET vector_updated_at = ? WHERE id = ?",
            (now, knowledge_id),
        )
        await conn.commit()
    finally:
        await conn.close()


async def fetch_all_vectors() -> list[dict[str, Any]]:
    """Todos los vectores persistidos [{knowledge_id, dim, vec}]. Pensado para
    KB locales (miles, no millones): escaneo completo con similitud coseno es
    más que suficiente y no añade dependencias externas."""
    conn = await _connect()
    try:
        cursor = await conn.execute("SELECT knowledge_id, dim, vec FROM knowledge_vec")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def get_entries_by_ids(ids: list[int]) -> dict[int, dict[str, Any]]:
    """Mapa id -> entrada, para ensamblar resultados fusionados sin reconsultar."""
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    conn = await _connect()
    try:
        cursor = await conn.execute(
            f"""
            SELECT kb.id, kb.description, kb.category, kb.content, kb.created_at,
                   kb.source, kb.updated_at, kb.vector_updated_at, kb.parent_id, kb.version
            FROM knowledge_base kb WHERE kb.id IN ({placeholders})
            """,
            tuple(int(i) for i in ids),
        )
        rows = await cursor.fetchall()
        return {int(r["id"]): dict(r) for r in rows}
    finally:
        await conn.close()


async def list_entries_without_vec(limit: int = 10000) -> list[dict[str, Any]]:
    """Entradas aún sin vector (para el backfill)."""
    conn = await _connect()
    try:
        cursor = await conn.execute(
            """
            SELECT kb.id, kb.description, kb.content
            FROM knowledge_base kb
            LEFT JOIN knowledge_vec kv ON kv.knowledge_id = kb.id
            WHERE kv.knowledge_id IS NULL
            ORDER BY kb.id
            LIMIT ?
            """,
            (max(1, limit),),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()
