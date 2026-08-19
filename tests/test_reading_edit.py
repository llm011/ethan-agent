# -*- coding: utf-8 -*-
"""阅读模式编辑：消息正文更新 + 标注 offset 重定位（store 层）。"""
from __future__ import annotations

import asyncio


def test_update_message_content(tmp_path):
    """update_message_content 回写正文；消息不存在返回 False。"""
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message

    async def _run():
        store = SessionStore(db_path=tmp_path / "sessions.db")
        await store.init()
        await store.create_with_id("s1", "fake-model")
        await store.save_message("s1", Message(role="assistant", content="旧内容"))
        session = await store.load("s1")
        msg = next(m for m in session.messages if m.role == "assistant")
        assert msg.content == "旧内容"

        assert await store.update_message_content(msg.id, "新内容") is True
        session2 = await store.load("s1")
        msg2 = next(m for m in session2.messages if m.role == "assistant")
        assert msg2.content == "新内容"

        assert await store.update_message_content(99999, "x") is False
        await store.close()

    asyncio.run(_run())


def test_annotation_update_offset(tmp_path, monkeypatch):
    """update_offset 重定位标注；标注不存在返回 False。"""
    import ethan.interface.routers.annotations as anno_mod

    monkeypatch.setattr(anno_mod, "_DB_PATH", tmp_path / "annotations.db")

    async def _run():
        store = anno_mod.AnnotationStore()
        aid = await store.create(1, "u1", "highlight", "yellow", 0, 5, "hello", None)

        assert await store.update_offset(aid, "u1", 10, 15) is True
        items = await store.list_for_message(1, "u1")
        assert items[0]["start"] == 10 and items[0]["end"] == 15

        # 他人/不存在的标注不可更新
        assert await store.update_offset(aid, "u2", 1, 2) is False
        assert await store.update_offset(999, "u1", 1, 2) is False
        await store.close()

    asyncio.run(_run())
