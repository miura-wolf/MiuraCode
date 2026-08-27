from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

from . import db
from .engine import GoalContext, TaskNode


def _message_digest(prev: str, message: dict[str, Any]) -> str:
    serialized = json.dumps(message, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{prev}\x1e{serialized}".encode("utf-8")).hexdigest()


def hash_chain(messages: list[dict[str, Any]]) -> list[str]:
    """Hash acumulado por prefijo: chain[i] identifica de forma estable el
    historial messages[:i+1], para poder detectar cuándo una request nueva es
    continuación exacta (mismo prefijo) de una conversación ya vista."""
    chain: list[str] = []
    prev = ""
    for message in messages:
        prev = _message_digest(prev, message)
        chain.append(prev)
    return chain


def new_session_id() -> str:
    return uuid.uuid4().hex


@dataclass
class SessionState:
    session_id: str
    checkpoint_hash: str
    checkpoint_len: int
    goal_ctx: GoalContext
    model: str
    tools: Optional[list[dict[str, Any]]]
    tool_choice: Any
    root: TaskNode
    leaves: list[TaskNode]
    results: list[str]
    pending_phase: Optional[Literal["leaf", "synthesis"]] = None
    pending_leaf_index: Optional[int] = None
    pending_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    pending_conversation: list[dict[str, Any]] = field(default_factory=list)
    tool_round_count: int = 0
    # Solo el contenido final de cada síntesis ya entregada en turnos previos
    # de esta misma conversación — nunca el reasoning_content interno, para
    # no filtrar la narración del proxy como si fuera diálogo real.
    turn_history: list[str] = field(default_factory=list)
    last_used_at: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def pending_tool_call_ids(self) -> set[str]:
        return {tc["id"] for tc in self.pending_tool_calls if tc.get("id")}


def is_valid_resume(session: SessionState, messages: list[dict[str, Any]]) -> bool:
    """True si `messages` extiende exactamente el checkpoint de `session` con
    los resultados de tool que esa sesión estaba esperando (en una hoja
    atómica o en la síntesis final — ambas quedan marcadas con pending_phase)."""
    if session.pending_phase is None or not session.pending_tool_calls:
        return False
    if len(messages) <= session.checkpoint_len:
        return False
    suffix = messages[session.checkpoint_len :]
    tool_ids = {m.get("tool_call_id") for m in suffix if m.get("role") == "tool" and m.get("tool_call_id")}
    return session.pending_tool_call_ids.issubset(tool_ids)


def is_new_turn(session: SessionState, messages: list[dict[str, Any]]) -> bool:
    """True si la sesión ya terminó su run (sin fase pendiente) pero la
    request trae mensajes nuevos más allá del checkpoint: un turno externo
    nuevo del caller sobre una conversación ya resuelta, no una reanudación
    de tool call. Permite sembrar el turno nuevo con turn_history en vez de
    reaplanar/redecomponer el historial crudo desde cero."""
    return session.pending_phase is None and len(messages) > session.checkpoint_len


def extract_tool_outputs(session: SessionState, messages: list[dict[str, Any]]) -> dict[str, str]:
    suffix = messages[session.checkpoint_len :]
    outputs: dict[str, str] = {}
    for m in suffix:
        if m.get("role") == "tool" and m.get("tool_call_id") in session.pending_tool_call_ids:
            outputs[m["tool_call_id"]] = m.get("content") or ""
    return outputs


# ------------------------------------------------------------------
# Serialización SessionState <-> dict (para persistencia en SQLite)
# ------------------------------------------------------------------

def _tasknode_to_dict(node: TaskNode) -> dict[str, Any]:
    return asdict(node)


def _dict_to_tasknode(d: dict[str, Any]) -> TaskNode:
    children_data = d.pop("children", [])
    children = [_dict_to_tasknode(c) for c in children_data]
    return TaskNode(children=children, **d)


def _serialize_state(state: SessionState) -> dict[str, Any]:
    """Convierte SessionState a un dict plano de valores JSON-serializables,
    listo para almacenarse en la tabla ``sessions`` de SQLite."""
    return {
        "session_id": state.session_id,
        "checkpoint_hash": state.checkpoint_hash,
        "checkpoint_len": state.checkpoint_len,
        "goal_ctx": json.dumps(asdict(state.goal_ctx), default=str),
        "model": state.model,
        "tools": json.dumps(state.tools, default=str),
        "tool_choice": json.dumps(state.tool_choice, default=str),
        "root": json.dumps(_tasknode_to_dict(state.root), default=str),
        "leaves": json.dumps([_tasknode_to_dict(l) for l in state.leaves], default=str),
        "results": json.dumps(state.results, default=str),
        "pending_phase": state.pending_phase,
        "pending_leaf_index": state.pending_leaf_index,
        "pending_tool_calls": json.dumps(state.pending_tool_calls, default=str),
        "pending_conversation": json.dumps(state.pending_conversation, default=str),
        "turn_history": json.dumps(state.turn_history, default=str),
        "tool_round_count": state.tool_round_count,
        "updated_at": state.last_used_at,
    }


def _deserialize_state(row: dict[str, Any]) -> SessionState:
    """Reconstruye SessionState a partir de una fila de la tabla ``sessions``."""

    def _load_json(key: str, default: Any) -> Any:
        val = row.get(key)
        if val is None:
            return default
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return default

    goal_ctx = GoalContext(**_load_json("goal_ctx", {}))
    root = _dict_to_tasknode(_load_json("root", {"description": "", "depth": 0}))
    leaves = [_dict_to_tasknode(l) for l in _load_json("leaves", [])]

    return SessionState(
        session_id=row["session_id"],
        checkpoint_hash=row.get("checkpoint_hash") or "",
        checkpoint_len=row.get("checkpoint_len") or 0,
        goal_ctx=goal_ctx,
        model=row.get("model") or "",
        tools=_load_json("tools", None),
        tool_choice=_load_json("tool_choice", None),
        root=root,
        leaves=leaves,
        results=_load_json("results", []),
        pending_phase=row.get("pending_phase"),
        pending_leaf_index=row.get("pending_leaf_index"),
        pending_tool_calls=_load_json("pending_tool_calls", []),
        pending_conversation=_load_json("pending_conversation", []),
        turn_history=_load_json("turn_history", []),
        tool_round_count=row.get("tool_round_count") or 0,
        last_used_at=row.get("updated_at") or 0.0,
    )


class SessionStore:
    """Guarda el árbol de tareas y los resultados ya calculados entre
    peticiones HTTP, para poder reanudar un turno externo pausado por una
    tool call sin repetir la descomposición ni las tareas atómicas ya
    resueltas.

    La fuente de verdad es la base de datos SQLite (``app/db.py``): las
    sesiones se persisten allí al guardarlas y se cargan de vuelta en la
    caché en memoria cuando esta está vacía (p. ej. tras un reinicio del
    proceso). La caché ``_sessions`` sigue sirviendo como acceso rápido y
    para la política de TTL/evicción dentro de una vida del proceso."""

    def __init__(self, ttl_seconds: float, max_sessions: int) -> None:
        self._ttl = ttl_seconds
        self._max_sessions = max_sessions
        self._sessions: dict[str, SessionState] = {}
        self._lock = asyncio.Lock()

    async def _load_from_db(self) -> None:
        """Carga todas las sesiones persistidas en la BD a la caché en memoria.
        Se llama de forma lazy cuando la caché está vacía."""
        async with self._lock:
            try:
                rows = await db.list_sessions()
            except Exception:
                return
            now = time.time()
            for row in rows:
                try:
                    state = _deserialize_state(row)
                except Exception:
                    continue
                if state.last_used_at >= now - self._ttl or self._ttl <= 0:
                    self._sessions[state.session_id] = state

    async def find_matching(self, messages: list[dict[str, Any]]) -> Optional[SessionState]:
        async with self._lock:
            self._evict_expired_locked()
            candidates = list(self._sessions.values())

        # Si la caché está vacía, intentar cargar desde la BD (p. ej. tras
        # un reinicio del proceso).
        if not candidates:
            await self._load_from_db()
            async with self._lock:
                self._evict_expired_locked()
                candidates = list(self._sessions.values())

        if not candidates or not messages:
            return None

        chain = hash_chain(messages)
        best: Optional[SessionState] = None
        for session in candidates:
            if session.checkpoint_len <= 0 or session.checkpoint_len > len(chain):
                continue
            if chain[session.checkpoint_len - 1] != session.checkpoint_hash:
                continue
            if best is None or session.checkpoint_len > best.checkpoint_len:
                best = session
        return best

    async def save(self, session: SessionState) -> None:
        session.last_used_at = time.time()
        evicted: list[str] = []
        async with self._lock:
            self._sessions[session.session_id] = session
            self._evict_expired_locked()
            overflow = len(self._sessions) - self._max_sessions
            if overflow > 0:
                oldest = sorted(self._sessions.values(), key=lambda s: s.last_used_at)
                for stale in oldest[:overflow]:
                    self._sessions.pop(stale.session_id, None)
                    evicted.append(stale.session_id)

        # Persistir a la BD (fuera del lock para no bloquear el event loop).
        data = _serialize_state(session)
        try:
            await db.save_session(session.session_id, data)
        except Exception:
            pass

        # Limpiar la BD de las sesiones evictadas de la caché.
        for sid in evicted:
            try:
                await db.delete_session(sid)
            except Exception:
                pass

    def _evict_expired_locked(self) -> None:
        if self._ttl <= 0:
            return
        cutoff = time.time() - self._ttl
        expired = [sid for sid, s in self._sessions.items() if s.last_used_at < cutoff]
        for sid in expired:
            self._sessions.pop(sid, None)

    # ------------------------------------------------------------------
    # Memoria de conocimiento reutilizable (RAG)
    # ------------------------------------------------------------------

    async def save_knowledge(
        self, description: str, content: str, category: str = "general"
    ) -> None:
        """Guarda un snippet de código o solución reutilizable en la base de
        conocimiento SQLite."""
        await db.save_knowledge(description, content, category)

    async def search_knowledge(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """Busca coincidencias de texto completo en la base de conocimiento
        usando FTS5."""
        return await db.search_knowledge(query, limit)
