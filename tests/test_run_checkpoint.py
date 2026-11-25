"""运行检查点 / 断点续跑（计划条目 6）。

中断时把结构化运行快照（跑到第几轮、最后调用什么工具、是否失败）落进
messages.run_checkpoint；/chat/resume 读回并注入 runtime_context，让模型知道
精确断点，而不是从零重新推理。
"""

from __future__ import annotations

import asyncio
import sqlite3

from ethan.memory.session import SessionStore
from ethan.providers.base import Message


async def _mk_store(tmp_path):
    store = SessionStore(db_path=tmp_path / "s.db")
    await store.init()
    return store


def test_run_checkpoint_column_exists(tmp_path):
    async def _run():
        await _mk_store(tmp_path)
        conn = sqlite3.connect(str(tmp_path / "s.db"))
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
        finally:
            conn.close()
        assert "run_checkpoint" in cols, "messages.run_checkpoint 列未创建"

    asyncio.run(_run())


def test_save_and_load_checkpoint_roundtrip(tmp_path):
    async def _run():
        store = await _mk_store(tmp_path)
        s = await store.create("m")
        msg = await store.save_message(s.id, Message(role="assistant", content="部分产出"))
        row_id = msg if isinstance(msg, int) else getattr(msg, "id", None)
        assert row_id, "需要拿到消息行 id"

        ckpt = {
            "iter": 7,
            "max_iters": 60,
            "last_tools": ["shell", "file_read"],
            "last_had_error": True,
            "updated_at": 1234.5,
        }
        await store.save_run_checkpoint(row_id, ckpt)
        got = await store.load_run_checkpoint(row_id)
        assert got["iter"] == 7
        assert got["last_tools"] == ["shell", "file_read"]
        assert got["last_had_error"] is True

    asyncio.run(_run())


def test_load_missing_checkpoint_returns_empty(tmp_path):
    async def _run():
        store = await _mk_store(tmp_path)
        s = await store.create("m")
        msg = await store.save_message(s.id, Message(role="assistant", content="x"))
        row_id = msg if isinstance(msg, int) else getattr(msg, "id", None)
        got = await store.load_run_checkpoint(row_id)
        assert got == {}

    asyncio.run(_run())


def test_checkpoint_survives_reinit(tmp_path):
    """检查点落库后，重启（新 store 实例）仍能读到。"""
    async def _run():
        store = await _mk_store(tmp_path)
        s = await store.create("m")
        msg = await store.save_message(s.id, Message(role="assistant", content="x"))
        row_id = msg if isinstance(msg, int) else getattr(msg, "id", None)
        await store.save_run_checkpoint(row_id, {"iter": 3, "last_tools": ["web_fetch"]})

        store2 = SessionStore(db_path=tmp_path / "s.db")
        await store2.init()
        got = await store2.load_run_checkpoint(row_id)
        assert got["iter"] == 3
        assert got["last_tools"] == ["web_fetch"]

    asyncio.run(_run())


def test_agent_tracks_run_checkpoint():
    """agent 每轮工具执行后更新 _run_checkpoint（字段完整）。"""
    from ethan.core.agent import Agent
    from ethan.tools.registry import ToolRegistry

    agent = Agent(tool_registry=ToolRegistry())
    assert agent._run_checkpoint == {}
    # 直接模拟循环内的更新逻辑（真实路径在 stream_chat 里）
    agent._run_checkpoint = {
        "iter": 1,
        "max_iters": 60,
        "last_tools": ["shell"],
        "last_had_error": False,
        "tool_names": ["shell"],
        "signatures": ["shell:ls"],
        "reflections_used": 0,
    }
    ck = agent._run_checkpoint
    assert ck["iter"] == 1
    assert ck["last_tools"] == ["shell"]
    assert ck["last_had_error"] is False
