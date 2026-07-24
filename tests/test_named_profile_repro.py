# -*- coding: utf-8 -*-
"""命名 profile 短会话记忆回归测试。

回归场景：changpeng 帐号在 1 轮短会话里说"我最近在研究机器人"没被记录。
根因是旧的实时抽取门槛 `user_turns % 3 != 0` 让 <3 轮短会话永不触发，
午夜 backfill 又被过高的字符门槛当闲聊丢弃。修复后短会话即时触发（token
门槛只挡纯寒暄），explicit 事实直接准入。admin/changpeng 对称断言，杜绝
per-profile 回归。
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from ethan.core.context import ETHAN_USER_ID
from ethan.memory.session import SessionStore
from ethan.providers.base import Message


def _setup_profile_env(tmp_path, monkeypatch, user_id: str):
    import ethan.core.config as config_mod
    import ethan.core.paths as paths
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    token = ETHAN_USER_ID.set(user_id)
    return token


async def _seed(user_id, tmp_path, monkeypatch, session_id,
                user_text="我最近在研究机器人", pairs: int = 3):
    """造一个 session，最后一条 user 消息恒为 user_text（便于 quote 校验通过）。

    pairs 控制对话轮数：1=只有事实那句，2=寒暄+事实，3=完整三段。
    这样短会话场景下 quote 仍能命中真实消息子串，区分"门槛没触发"与"quote 没命中"。
    """
    _setup_profile_env(tmp_path, monkeypatch, user_id)
    from ethan.core.paths import user_sessions_db_path
    db_path = user_sessions_db_path()
    store = SessionStore(db_path=db_path)
    await store.init()
    await store.create_with_id(session_id, "fake-model")
    prefix = [("你好", "你好！"), ("在忙点东西", "哦？")]
    convo = prefix[: pairs - 1] + [(user_text, "有意思！")]
    for u, a in convo:
        await store.save_message(session_id, Message(role="user", content=u))
        await store.save_message(session_id, Message(role="assistant", content=a))
    session = await store.load(session_id)
    await store.close()
    uid = next(m.id for m in reversed(session.messages) if m.role == "user")
    return db_path, session, uid


def _payload(message_id, evidence_level, quote="我最近在研究机器人"):
    return json.dumps({"candidates": [{
        "memory_type": "activity",
        "dimension": "activity.project",
        "memory_key": "activity.project",
        "content": "用户最近在研究机器人",
        "evidence_level": evidence_level,
        "scope_type": "user", "scope_id": "self",
        "message_id": message_id,
        "quote": quote,
        "confidence": 0.8, "importance": 0.7,
        "valid_until": None, "structured": {},
    }]}, ensure_ascii=False)


class _R:
    def __init__(self, c): self.content = c


class FakeProvider:
    def __init__(self, p):
        self.payload = p
        self.calls = 0

    async def chat(self, messages, tools=None, system="", max_tokens=None):
        self.calls += 1
        return _R(self.payload)


def _patch(monkeypatch, provider):
    from ethan.memory.extractors import StructuredMemoryExtractor
    async def _g(self): return provider
    monkeypatch.setattr(StructuredMemoryExtractor, "_get_provider", _g)


async def _run_case(user_id, evidence, tmp_path, monkeypatch, label, pairs: int = 3):
    from ethan.core.paths import user_vectors_db_path
    from ethan.interface.routers.tasks import _run_structured_extraction
    from ethan.memory.recall import build_structured_recall

    sid = f"sess-{label}"
    _, session, uid = await _seed(user_id, tmp_path, monkeypatch, sid, pairs=pairs)
    provider = FakeProvider(_payload(uid, evidence))
    _patch(monkeypatch, provider)
    turns = sum(1 for m in session.messages if m.role == "user")
    await _run_structured_extraction(session, "fake-model", user_id, turns)

    mem_db = user_vectors_db_path()
    db = sqlite3.connect(str(mem_db))
    try:
        st = db.execute(
            "select processing_status from memory_candidates where memory_key='activity.project'"
        ).fetchone()
        active = db.execute("select count(*) from memories where status='active'").fetchone()[0]
    finally:
        db.close()
    rr = build_structured_recall("机器人", mode="")
    return {
        "label": label, "user_id": repr(user_id), "evidence": evidence,
        "pairs": pairs, "turns": turns,
        "candidate_status": st[0] if st else None,
        "active_count": active,
        "recall_count": rr.count,
        "db_path": str(mem_db),
    }


@pytest.mark.anyio
async def test_short_session_records_explicit_for_named_profile(tmp_path, monkeypatch):
    """回归：changpeng 在 1 轮短会话里明确陈述"我最近在研究机器人"，必须被记录并召回。

    这是用户报告的症状根因：旧逻辑 user_turns % 3 != 0 门槛让 <3 轮短会话永不触发
    实时抽取；午夜 backfill 又被过高的字符门槛当闲聊丢弃。修复后短会话即时触发
    （token 门槛只挡纯寒暄），explicit 事实直接准入。admin/changpeng 对称断言，
    杜绝 per-profile 回归。
    """
    admin = await _run_case("", "explicit", tmp_path, monkeypatch, "admin-1turn", pairs=1)
    cp = await _run_case("changpeng", "explicit", tmp_path, monkeypatch, "cp-1turn", pairs=1)

    assert admin["active_count"] >= 1, "admin 1 轮短会话 explicit 事实未入库"
    assert cp["active_count"] >= 1, "changpeng 1 轮短会话 explicit 事实未入库 ← 用户报告的症状"
    assert admin["recall_count"] == cp["recall_count"], "短会话记忆在 profile 间不对称"
