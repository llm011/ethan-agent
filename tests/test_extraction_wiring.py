# -*- coding: utf-8 -*-
"""tasks.py 提取链路接线集成测试(fake provider,0 LLM)。

覆盖手工实测发现过的回归点(见 df313ec 前的 live 实测):
1. 5 轮会话触发 _run_structured_extraction → 候选入库 + job completed
2. 增量去重: 二次运行不再提取(boundary 短路,0 次 LLM 调用)
3. 提取抛异常: job 标记 failed 并记录错误(不再静默吞掉)
4. _maybe_generate_skill 传 session.messages(Session 不可迭代的回归)
5. 非流式 /api/chat 也会触发 _maybe_consolidate(chat.py 非流式分支补齐的回归)
"""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import AsyncMock

import pytest

from ethan.core.context import ETHAN_USER_ID
from ethan.memory.session import SessionStore
from ethan.providers.base import Message


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    """CONFIG_DIR 隔离到 tmp_path + user_id 空,所有 user_*_path() 落到临时目录。"""
    import ethan.core.paths as paths
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path)
    token = ETHAN_USER_ID.set("")
    yield tmp_path
    ETHAN_USER_ID.reset(token)


async def _seed_session(db_path, session_id: str, pairs: int = 5) -> None:
    """造一个 sessions 行 + pairs 对 user/assistant 消息。"""
    store = SessionStore(db_path=db_path)
    await store.init()
    await store.create_with_id(session_id, "fake-model")
    for i in range(pairs):
        await store.save_message(session_id, Message(role="user", content=f"用户消息 {i}:你就叫我小渔吧。"))
        await store.save_message(session_id, Message(role="assistant", content=f"好的 {i}"))
    await store.close()


def _fake_payload(message_id: int) -> str:
    return json.dumps({"candidates": [{
        "memory_type": "personal_information",
        "dimension": "identity.preferred_name",
        "memory_key": "identity.preferred_name",
        "content": "用户希望被叫小渔",
        "evidence_level": "explicit",
        "scope_type": "user", "scope_id": "self",
        "message_id": message_id,
        "quote": "你就叫我小渔吧",
        "confidence": 0.95, "importance": 0.8,
        "valid_until": None, "structured": {},
    }]}, ensure_ascii=False)


class _FakeResp:
    def __init__(self, content):
        self.content = content


class FakeProvider:
    """返回固定 payload 的 provider;calls 记录调用次数。"""

    def __init__(self, payload: str):
        self.payload = payload
        self.calls = 0

    async def chat(self, messages, tools=None, system="", max_tokens=None):
        self.calls += 1
        return _FakeResp(self.payload)


class BoomProvider:
    async def chat(self, messages, tools=None, system="", max_tokens=None):
        raise RuntimeError("provider boom")


def _patch_provider(monkeypatch, provider):
    """把 extractor 的 _get_provider(async)替换为返回 fake provider。"""
    from ethan.memory.extractors import StructuredMemoryExtractor

    async def _get(self):
        return provider

    monkeypatch.setattr(StructuredMemoryExtractor, "_get_provider", _get)


@pytest.mark.anyio
async def test_extraction_wires_end_to_end_and_dedups(isolated_env, monkeypatch):
    from ethan.core.paths import user_sessions_db_path, user_vectors_db_path
    from ethan.interface.routers.tasks import _run_structured_extraction

    await _seed_session(user_sessions_db_path(), "sess-e2e")

    # fake provider:返回围栏包裹的 JSON,顺带验证宽松解析
    provider = FakeProvider("```json\n" + _fake_payload(1) + "\n```")
    _patch_provider(monkeypatch, provider)

    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()
    session = await store.load("sess-e2e")
    await store.close()
    turns = sum(1 for m in session.messages if m.role == "user")
    assert turns == 5

    # 真实 quote 校验:message_id 必须是真实消息 id,quote 是其子串。
    # fake payload 里 message_id=1 可能不对,先拿真实 user 消息 id 替换。
    uid = next(m.id for m in session.messages if m.role == "user")
    provider.payload = "```json\n" + _fake_payload(uid) + "\n```"

    await _run_structured_extraction(session, "fake-model", "", turns)
    assert provider.calls == 1

    db = sqlite3.connect(str(user_vectors_db_path()))
    try:
        cands = db.execute("select dimension, processing_status from memory_candidates").fetchall()
        assert cands == [("identity.preferred_name", "admitted")]
        job = db.execute(
            "select status, result_json from consolidation_jobs where job_type='incremental_extraction'"
        ).fetchone()
        assert job[0] == "completed"
        assert json.loads(job[1])["admitted"] == 1
    finally:
        db.close()

    # 二次运行:boundary 短路,不再调 LLM
    await _run_structured_extraction(session, "fake-model", "", turns)
    assert provider.calls == 1


@pytest.mark.anyio
async def test_extraction_failure_marks_job_failed(isolated_env, monkeypatch):
    from ethan.core.paths import user_sessions_db_path, user_vectors_db_path
    from ethan.interface.routers.tasks import _run_structured_extraction

    await _seed_session(user_sessions_db_path(), "sess-fail")
    _patch_provider(monkeypatch, BoomProvider())

    store = SessionStore(db_path=user_sessions_db_path())
    await store.init()
    session = await store.load("sess-fail")
    await store.close()
    turns = sum(1 for m in session.messages if m.role == "user")

    await _run_structured_extraction(session, "fake-model", "", turns)  # 不抛

    db = sqlite3.connect(str(user_vectors_db_path()))
    try:
        job = db.execute(
            "select status, error_message from consolidation_jobs where job_type='incremental_extraction'"
        ).fetchone()
        assert job[0] == "failed"
        assert "LLM call failed" in job[1]  # 底层原因(boom)由 extractor logger.exception 记录
    finally:
        db.close()


@pytest.mark.anyio
async def test_generate_skill_passes_messages_not_session(isolated_env, monkeypatch):
    """回归: 曾把 Session 对象当 list 传给 maybe_generate(TypeError 被静默)。"""
    from ethan.interface.routers import tasks

    await _seed_session(isolated_env / "sessions.db", "sess-skill", pairs=5)
    captured = {}

    class FakeGen:
        def __init__(self, **kwargs):
            pass

        async def maybe_generate(self, messages):
            captured["messages"] = messages
            return None

    monkeypatch.setattr(tasks, "SkillGenerator", FakeGen) if hasattr(tasks, "SkillGenerator") else None
    # tasks.py 在函数内 import SkillGenerator,patch 目标模块
    monkeypatch.setattr("ethan.skills.generator.SkillGenerator", FakeGen)

    await tasks._maybe_generate_skill("sess-skill", "fake-model", "")
    assert isinstance(captured.get("messages"), list), f"应传 list[Message],实际 {type(captured.get('messages'))}"


def test_nonstream_chat_triggers_consolidation(isolated_env, monkeypatch):
    """回归: 非流式 /api/chat 曾完全不触发 _maybe_consolidate。"""
    from fastapi.testclient import TestClient

    from ethan.interface.api import app
    from ethan.interface.routers import chat as chat_mod
    from ethan.interface.routers import deps

    app.dependency_overrides[deps.verify_token] = lambda: ""

    class FakeAgent:
        class _P:
            model = "fake-model"
        _provider = _P()
        usage = type("U", (), {"input_tokens": 1, "output_tokens": 1, "cache_tokens": 0})()

        async def chat(self, messages):
            return Message(role="assistant", content="好的")

    consolidate = AsyncMock(return_value=None)
    gen_skill = AsyncMock(return_value=None)
    monkeypatch.setattr(chat_mod, "create_agent", lambda *a, **k: FakeAgent())
    monkeypatch.setattr("ethan.interface.routers.tasks._maybe_consolidate", consolidate)
    monkeypatch.setattr("ethan.interface.routers.tasks._maybe_generate_skill", gen_skill)

    client = TestClient(app)
    resp = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "你好"}],
        "session_id": "sess-nonstream", "stream": False,
    })
    assert resp.status_code == 200, resp.text
    import time
    time.sleep(0.2)  # 让 portal 循环跑一下后台 task
    assert consolidate.await_count >= 1, "非流式 chat 未触发 _maybe_consolidate"
    assert gen_skill.await_count >= 1, "非流式 chat 未触发 _maybe_generate_skill"
    app.dependency_overrides.clear()
