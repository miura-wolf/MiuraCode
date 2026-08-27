from __future__ import annotations

import pytest

from app.db import (
    clear_knowledge,
    delete_session,
    init_db,
    list_sessions,
    load_session,
    save_knowledge,
    save_session,
    search_knowledge,
)
from app.engine import GoalContext, TaskNode
from app.session import SessionState, _serialize_state


def _make_session(session_id: str = "s1") -> dict:
    state = SessionState(
        session_id=session_id,
        checkpoint_hash="h1",
        checkpoint_len=2,
        goal_ctx=GoalContext(
            caller_system="sys",
            turn_instruction="haz algo",
            prior_context="ctx",
        ),
        model="test-model",
        tools=None,
        tool_choice=None,
        root=TaskNode(description="haz algo", depth=0, is_atomic=True),
        leaves=[],
        results=[],
    )
    return _serialize_state(state)


@pytest.mark.asyncio
async def test_save_and_load_session():
    await save_session("s_db_1", _make_session("s_db_1"))
    loaded = await load_session("s_db_1")
    assert loaded is not None
    assert loaded["session_id"] == "s_db_1"
    assert loaded["model"] == "test-model"
    assert loaded["checkpoint_len"] == 2


@pytest.mark.asyncio
async def test_list_sessions():
    await save_session("s_db_2", _make_session("s_db_2"))
    await save_session("s_db_3", _make_session("s_db_3"))
    sessions = await list_sessions()
    ids = {s["session_id"] for s in sessions}
    assert "s_db_2" in ids
    assert "s_db_3" in ids


@pytest.mark.asyncio
async def test_delete_session():
    await save_session("s_db_4", _make_session("s_db_4"))
    await delete_session("s_db_4")
    loaded = await load_session("s_db_4")
    assert loaded is None


@pytest.mark.asyncio
async def test_save_and_search_knowledge():
    await save_knowledge(
        "Sumar dos numeros en Python",
        "def sumar(a, b):\n    return a + b",
        "python",
    )
    await save_knowledge(
        "Leer archivo en Python",
        "with open('x') as f:\n    ...",
        "python",
    )
    results = await search_knowledge("sumar numeros")
    assert len(results) >= 1
    descriptions = [r["description"].lower() for r in results]
    assert any("sumar" in d for d in descriptions)


@pytest.mark.asyncio
async def test_search_knowledge_limit():
    for i in range(10):
        await save_knowledge(f"Item numero {i}", f"contenido {i}", "general")
    results = await search_knowledge("Item", limit=3)
    assert len(results) <= 3


@pytest.mark.asyncio
async def test_search_knowledge_empty_query():
    results = await search_knowledge("")
    assert results == []
    results = await search_knowledge("   ")
    assert results == []


@pytest.mark.asyncio
async def test_clear_knowledge():
    await save_knowledge("temp", "contenido temporal", "general")
    await clear_knowledge()
    results = await search_knowledge("temp")
    assert results == []


@pytest.mark.asyncio
async def test_session_roundtrip_preserves_complex_fields():
    from app.session import _deserialize_state

    state = SessionState(
        session_id="s_rt",
        checkpoint_hash="h_rt",
        checkpoint_len=3,
        goal_ctx=GoalContext(
            caller_system="caller",
            turn_instruction="instruccion",
            prior_context="previo",
            image_parts=[{"type": "image_url", "image_url": {"url": "data:image/png;base64,aa"}}],
        ),
        model="m",
        tools=[{"type": "function", "function": {"name": "f", "description": "d"}}],
        tool_choice="auto",
        root=TaskNode(
            description="raiz",
            depth=0,
            children=[
                TaskNode(description="hijo", depth=1, is_atomic=True)
            ],
            is_atomic=False,
        ),
        leaves=[TaskNode(description="hoja", depth=2, is_atomic=True)],
        results=["r1"],
        pending_phase="leaf",
        pending_leaf_index=0,
        pending_tool_calls=[{"id": "c1", "function": {"name": "f", "arguments": "{}"}}],
        pending_conversation=[{"role": "tool", "tool_call_id": "c1", "content": "out"}],
        tool_round_count=1,
        turn_history=["turno 1"],
    )
    data = _serialize_state(state)
    await save_session("s_rt", data)
    loaded = await load_session("s_rt")
    assert loaded is not None
    restored = _deserialize_state(loaded)
    assert restored.session_id == "s_rt"
    assert restored.goal_ctx.caller_system == "caller"
    assert restored.goal_ctx.image_parts == [{"type": "image_url", "image_url": {"url": "data:image/png;base64,aa"}}]
    assert restored.root.children[0].description == "hijo"
    assert restored.leaves[0].description == "hoja"
    assert restored.pending_tool_calls[0]["id"] == "c1"
    assert restored.turn_history == ["turno 1"]
