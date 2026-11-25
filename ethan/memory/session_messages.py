"""session messages responsibilities; public facade: memory.session."""
from __future__ import annotations

import logging
import shutil
import time

from ethan.providers.base import Message

from .session_models import Session

logger = logging.getLogger(__name__)


class SessionMessagesMixin:
    async def save_message(self, session_id: str, msg: Message) -> int:
        if not getattr(self, "_transaction_owned", False):
            return await self._message_transaction("save_message", session_id, msg)
        import json

        tool_calls_json = (
            json.dumps([{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls])
            if msg.tool_calls
            else None
        )

        msg_created_at = msg.created_at if msg.created_at else time.time()
        usage_json = json.dumps(msg.usage) if msg.usage else None
        tool_steps_json = json.dumps(msg.tool_steps) if msg.tool_steps else None
        quote_json = json.dumps(msg.quote, ensure_ascii=False) if msg.quote else None
        a2ui_json = json.dumps(msg.a2ui, ensure_ascii=False) if msg.a2ui else None
        mcp_apps_json = json.dumps(msg.mcp_apps, ensure_ascii=False) if msg.mcp_apps else None
        images_json = json.dumps(msg.images, ensure_ascii=False) if msg.images else None
        matched_skills_json = json.dumps(msg.matched_skills, ensure_ascii=False) if msg.matched_skills else None
        cards_json = json.dumps(msg.cards, ensure_ascii=False) if msg.cards else None
        files_json = json.dumps(msg.files, ensure_ascii=False) if msg.files else None

        cursor = await self._db.execute(
            "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, created_at, usage, tool_steps, thought, quote, a2ui, images, matched_skills, ttfb_ms, total_ms, mcp_apps, cards, intermediate_blob_id, status, reasoning, model, error, files) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                msg.role,
                msg.content,
                tool_calls_json,
                msg.tool_call_id,
                msg_created_at,
                usage_json,
                tool_steps_json,
                msg.thought,
                quote_json,
                a2ui_json,
                images_json,
                matched_skills_json,
                msg.ttfb_ms,
                msg.total_ms,
                mcp_apps_json,
                cards_json,
                0,
                msg.status,
                msg.reasoning or "",
                msg.model or None,
                msg.error or "",
                files_json,
            ),
        )
        row_id = cursor.lastrowid
        await self._persist_message_wire(session_id, row_id, msg)
        await self._db.commit()
        blob_id = await self._ensure_intermediate_blob(session_id, row_id, msg)
        msg.intermediate_blob_id = blob_id
        return row_id  # 返回行 id，供「进度消息」复用同一条行做覆盖式 UPDATE


    async def update_message(self, row_id: int, session_id: str, msg: Message) -> None:
        """按主键 id 更新一条消息。

        用于「工具进度实时落库」：流式过程中先 INSERT 一条占位 assistant 消息（content 空、
        tool_steps 为当前步骤），每完成一个工具就 UPDATE 同一行覆盖 tool_steps；流结束后
        再 UPDATE 写入最终正文/usage/a2ui。这样工具过程实时留存，且整轮只占一行。
        """
        if not getattr(self, "_transaction_owned", False):
            return await self._message_transaction("update_message", row_id, session_id, msg)
        import json

        tool_calls_json = (
            json.dumps([{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls])
            if msg.tool_calls
            else None
        )
        usage_json = json.dumps(msg.usage) if msg.usage else None
        tool_steps_json = json.dumps(msg.tool_steps) if msg.tool_steps else None
        a2ui_json = json.dumps(msg.a2ui, ensure_ascii=False) if msg.a2ui else None
        mcp_apps_json = json.dumps(msg.mcp_apps, ensure_ascii=False) if msg.mcp_apps else None
        matched_skills_json = json.dumps(msg.matched_skills, ensure_ascii=False) if msg.matched_skills else None
        cards_json = json.dumps(msg.cards, ensure_ascii=False) if msg.cards else None

        await self._db.execute(
            "UPDATE messages SET content=?, tool_calls=?, usage=?, tool_steps=?, thought=?, a2ui=?, mcp_apps=?, matched_skills=?, ttfb_ms=?, total_ms=?, cards=?, created_at=?, status=?, reasoning=?, model=COALESCE(?, model), error=? "
            "WHERE id=? AND session_id=?",
            (
                msg.content,
                tool_calls_json,
                usage_json,
                tool_steps_json,
                msg.thought,
                a2ui_json,
                mcp_apps_json,
                matched_skills_json,
                msg.ttfb_ms,
                msg.total_ms,
                cards_json,
                msg.created_at or time.time(),
                msg.status,
                msg.reasoning or "",
                msg.model or None,
                msg.error or "",
                row_id,
                session_id,
            ),
        )
        await self._persist_message_wire(session_id, row_id, msg)
        await self._db.commit()
        msg.intermediate_blob_id = await self._ensure_intermediate_blob(session_id, row_id, msg)


    async def update_message_status(self, row_id: int, status: str, expected: str | None = None) -> bool:
        """原子更新消息状态。传入 expected 时仅当前状态匹配才更新（CAS），返回是否生效。"""
        if expected:
            cursor = await self._db.execute(
                "UPDATE messages SET status=? WHERE id=? AND status=?",
                (status, row_id, expected),
            )
        else:
            cursor = await self._db.execute(
                "UPDATE messages SET status=? WHERE id=?",
                (status, row_id),
            )
        await self._db.commit()
        return cursor.rowcount > 0


    async def save_run_checkpoint(self, row_id: int, checkpoint: dict) -> None:
        """保存运行检查点（条目 6）：中断/超时时记录当前轮次与步骤进度。

        存 messages.run_checkpoint（JSON 字符串）。续跑时由 /chat/resume 读回，
        让模型知道「跑到哪一步、哪些已完成」，而不是从零重新推理。
        不 touch updated_at，避免续跑检查点把会话顶到列表顶部。
        """
        import json

        try:
            await self._db.execute(
                "UPDATE messages SET run_checkpoint=? WHERE id=?",
                (json.dumps(checkpoint or {}, ensure_ascii=False), row_id),
            )
            await self._db.commit()
        except Exception:
            logger.debug("保存运行检查点失败 row=%s", row_id, exc_info=True)


    async def load_run_checkpoint(self, row_id: int) -> dict:
        """读取运行检查点；无则返回空 dict。"""
        import json

        try:
            async with self._db.execute(
                "SELECT COALESCE(run_checkpoint, '') FROM messages WHERE id=?", (row_id,)
            ) as cursor:
                row = await cursor.fetchone()
        except Exception:
            return {}
        if not row or not row[0]:
            return {}
        try:
            data = json.loads(row[0])
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


    async def interrupt_running_messages(self, session_id: str, reason: str = "") -> int:
        """把会话内所有 running 态的 assistant 消息标记为 interrupted。

        producer 崩溃/异常退出时的兜底：实时进度占位行（content 空、status=running）
        若无人定稿，刷新后 UI 会无限转圈。watchdog 补丁与落库失败路径调用；
        已正常定稿的行是 completed，不会被误伤。返回更新行数。

        传入 reason（如“任务意外终止…/友好错误文案”）时，会把该说明写入独立 error
        字段（而非 content），让中断原因持久化且不与回复正文语义混淆——否则前端
        会把错误文案当正常正文渲染、提示条措辞与实际内容错位。
        """
        if reason:
            cursor = await self._db.execute(
                "UPDATE messages SET status='interrupted', error=? "
                "WHERE session_id=? AND role='assistant' AND status='running'",
                (reason, session_id),
            )
        else:
            cursor = await self._db.execute(
                "UPDATE messages SET status='interrupted' WHERE session_id=? AND role='assistant' AND status='running'",
                (session_id,),
            )
        await self._db.commit()
        return cursor.rowcount


    async def delete_message_by_id(self, row_id: int) -> None:
        """按主键 id 删除单条消息（新 run 替换旧 run 时丢弃残留的进度占位行用）。"""
        await self._delete_intermediate_blob_for_message(row_id)
        await self._db.execute("DELETE FROM messages WHERE id=?", (row_id,))
        await self._db.commit()


    async def update_message_content(self, row_id: int, content: str) -> bool:
        """按主键更新消息正文（阅读模式编辑用）。返回消息是否存在。"""
        cursor = await self._db.execute(
            "UPDATE messages SET content=? WHERE id=?",
            (content, row_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0


    async def replace_messages(self, session_id: str, messages: list[Message]) -> None:
        """用新消息集替换该 session 的全部消息（/compact 压缩历史用）。

        保留 session 记录本身，只清空 messages 再重写，并 touch 更新时间。
        """
        from ethan.core.paths import user_intermediate_dir

        shutil.rmtree(user_intermediate_dir() / session_id, ignore_errors=True)
        await self._db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await self._db.commit()
        for msg in messages:
            await self.save_message(session_id, msg)
        await self.touch(session_id)


    async def load(
        self,
        session_id: str,
        limit: int | None = None,
        before: int | None = None,
    ) -> Session | None:
        """加载会话及其消息。

        limit / before 用于分页：只取「最近 limit 条」或「id 小于 before 的最近 limit 条」。
        两者都为 None 时行为与分页前完全一致（全量加载），保证既有调用方不受影响。

        分页时按 id 倒序取 limit 条再翻回正序返回，因此 session.messages 始终是
        时间正序（与全量加载一致），调用方无需关心取的是哪一段。判断还有没有更早的
        消息用 has_more_messages()。
        """
        import json

        from ethan.providers.base import ToolCall

        async with self._db.execute(
            "SELECT id, title, model, created_at, updated_at, COALESCE(source, 'web'), COALESCE(mode, ''), "
            "COALESCE(pending_injected, '[]'), COALESCE(kernel_session_id, ''), COALESCE(kernel_kind, '') "
            "FROM sessions WHERE id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

        session = Session(
            id=row[0],
            title=row[1],
            model=row[2],
            created_at=row[3],
            updated_at=row[4],
            source=row[5],
            mode=row[6],
            # 外部内核会话 id（DSH/Claude），刷新后仍要展示
            kernel_session_id=row[8] if len(row) > 8 else "",
            kernel_kind=row[9] if len(row) > 9 else "",
        )
        # 「补充信息」待消费队列（跨刷新/重启持久化）；坏数据直接丢弃
        try:
            _pending = json.loads(row[7]) if len(row) > 7 and row[7] else []
        except Exception:
            _pending = []
        session.pending_injected = [
            i for i in _pending if isinstance(i, dict) and i.get("id") and i.get("content")
        ]

        # 新列一律**追加到末尾**：下面的行解析按位置下标取值（r[11]…r[21]），
        # 插在中间会把所有既有字段错位。
        _MSG_COLS = (
            "id, role, content, tool_calls, tool_call_id, created_at, usage, tool_steps, thought, "
            "quote, a2ui, images, matched_skills, ttfb_ms, total_ms, mcp_apps, cards, "
            "intermediate_blob_id, status, reasoning, model, error, files"
        )
        if limit is None and before is None:
            _sql = f"SELECT {_MSG_COLS} FROM messages WHERE session_id = ? ORDER BY id"
            _params: tuple = (session_id,)
        else:
            # 取「比 before 更早的最近 limit 条」：先按 id 倒序 + LIMIT 命中目标窗口，
            # 再在 Python 里翻回正序（SQL 末尾的 ORDER BY 是外层，用来恢复正序）。
            _where = "session_id = ?"
            _params = [session_id]
            if before is not None:
                _where += " AND id < ?"
                _params.append(before)
            _sql = (
                f"SELECT * FROM (SELECT {_MSG_COLS} FROM messages WHERE {_where} "
                "ORDER BY id DESC LIMIT ?) ORDER BY id"
            )
            # limit 缺省（只传了 before）时取「比 before 更早的全部」：SQLite 的
            # LIMIT -1 就是不限量。不能对 None 直接 int()，那会 TypeError → 500。
            _params.append(max(1, int(limit)) if limit is not None else -1)
            _params = tuple(_params)

        async with self._db.execute(_sql, _params) as cursor:
            async for r in cursor:
                tool_calls = []
                if r[3]:
                    for tc in json.loads(r[3]):
                        tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"]))
                usage = json.loads(r[6]) if r[6] else None
                tool_steps = json.loads(r[7]) if r[7] else []
                quote = json.loads(r[9]) if len(r) > 9 and r[9] else None
                a2ui = json.loads(r[10]) if len(r) > 10 and r[10] else None
                images = json.loads(r[11]) if len(r) > 11 and r[11] else []
                matched_skills = json.loads(r[12]) if len(r) > 12 and r[12] else None
                ttfb_ms = r[13] if len(r) > 13 and r[13] is not None else None
                total_ms = r[14] if len(r) > 14 and r[14] is not None else None
                mcp_apps = json.loads(r[15]) if len(r) > 15 and r[15] else None
                cards = json.loads(r[16]) if len(r) > 16 and r[16] else None
                intermediate_blob_id = int(r[17] or 0) if len(r) > 17 and r[17] is not None else 0
                _status = r[18] if len(r) > 18 and r[18] else "completed"
                _reasoning = r[19] if len(r) > 19 and r[19] else ""
                _model = r[20] if len(r) > 20 and r[20] else None
                _error = r[21] if len(r) > 21 and r[21] else ""
                files = json.loads(r[22]) if len(r) > 22 and r[22] else None
                session.messages.append(
                    Message(
                        role=r[1],
                        content=r[2],
                        id=r[0],
                        tool_calls=tool_calls,
                        tool_call_id=r[4],
                        created_at=r[5],
                        usage=usage,
                        tool_steps=tool_steps,
                        thought=r[8],
                        reasoning=_reasoning,
                        quote=quote,
                        a2ui=a2ui,
                        images=images,
                        matched_skills=matched_skills,
                        ttfb_ms=ttfb_ms,
                        total_ms=total_ms,
                        mcp_apps=mcp_apps,
                        cards=cards,
                        files=files,
                        intermediate_blob_id=intermediate_blob_id,
                        status=_status,
                        model=_model,
                        error=_error,
                    )
                )

        transcripts = await self.load_wire_transcripts(session_id)
        for message in session.messages:
            if message.id in transcripts:
                message._wire_transcript = transcripts[message.id]
        return session


    async def has_more_messages(self, session_id: str, before: int) -> bool:
        """session 里是否还有 id 小于 before 的消息（分页时判断能否继续上滚加载）。"""
        async with self._db.execute(
            "SELECT 1 FROM messages WHERE session_id = ? AND id < ? LIMIT 1",
            (session_id, before),
        ) as cursor:
            return await cursor.fetchone() is not None


    async def count_messages(self, session_id: str) -> int:
        """会话的消息总数（前端展示「还有 N 条更早」之类的提示时用）。"""
        async with self._db.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0
