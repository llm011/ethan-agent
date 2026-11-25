"""session metadata responsibilities; public facade: memory.session."""
from __future__ import annotations

import logging
import shutil
import time

from .session_models import Session
from .session_titles import _generate_id

logger = logging.getLogger(__name__)


class SessionMetadataMixin:
    async def create(self, model: str, source: str = "web", mode: str = "", title: str | None = None) -> Session:
        """新建会话。

        `title` 让调用方把标题**随创建一起**落库（单次事务）。系统会话必须用它——
        `[心跳]`/`[定时]`/`[后台]` 这些前缀是分组识别的唯一依据，先 create 再
        update_title 的两次写之间若进程被打断（如 watchdog 重启风暴），就会留下
        一条有 source 却没有前缀的孤儿会话，永远落不进对应分组、只能掉进「最新对话」。
        """
        now = time.time()
        session = Session(
            id=_generate_id(),
            title=title or "新对话",
            model=model,
            created_at=now,
            updated_at=now,
            source=source,
            mode=mode,
            last_read_at=now,
        )
        await self._db.execute(
            "INSERT INTO sessions (id, title, model, created_at, updated_at, source, mode, last_read_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session.id, session.title, session.model, session.created_at, session.updated_at, source, mode, now),
        )
        await self._db.commit()
        return session


    async def create_with_id(self, session_id: str, model: str, source: str = "web", mode: str = "") -> Session:
        """使用指定的 session_id 创建 session（用于 CLI/API 预生成 id 的场景）。"""
        now = time.time()
        session = Session(
            id=session_id,
            title="新对话",
            model=model,
            created_at=now,
            updated_at=now,
            source=source,
            mode=mode,
            last_read_at=now,
        )
        await self._db.execute(
            "INSERT INTO sessions (id, title, model, created_at, updated_at, source, mode, last_read_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session.id, session.title, session.model, session.created_at, session.updated_at, source, mode, now),
        )
        await self._db.commit()
        return session


    async def update_title(self, session_id: str, title: str) -> None:
        now = time.time()
        await self._db.execute(
            # 标题是元数据，不应制造未读：已读会话水位跟随 updated_at 保持已读，
            # 未读会话水位不动保持未读（SET 表达式取旧行值）。
            "UPDATE sessions SET title = ?, updated_at = ?, "
            "last_read_at = CASE WHEN last_read_at >= updated_at THEN ? ELSE last_read_at END "
            "WHERE id = ?",
            (title, now, now, session_id),
        )
        await self._db.commit()


    async def update_mode(self, session_id: str, mode: str) -> None:
        now = time.time()
        await self._db.execute(
            # 同 update_title：模式切换是元数据变更，不制造未读。
            "UPDATE sessions SET mode = ?, updated_at = ?, "
            "last_read_at = CASE WHEN last_read_at >= updated_at THEN ? ELSE last_read_at END "
            "WHERE id = ?",
            (mode, now, now, session_id),
        )
        await self._db.commit()


    async def update_model(self, session_id: str, model: str) -> None:
        """更新会话绑定的模型。用于「点击重名模型候选后把选择持久化到当前会话」场景。

        与 update_mode 同款语义：模型选择是元数据变更，不制造未读。
        注：写入的可能是复合格式 ``provider/id``（与前端 selectedModel 的存储一致）。
        """
        now = time.time()
        await self._db.execute(
            "UPDATE sessions SET model = ?, updated_at = ?, "
            "last_read_at = CASE WHEN last_read_at >= updated_at THEN ? ELSE last_read_at END "
            "WHERE id = ?",
            (model, now, now, session_id),
        )
        await self._db.commit()


    async def pin_session(self, session_id: str) -> None:
        await self._db.execute(
            "UPDATE sessions SET pinned_at = ? WHERE id = ?",
            (time.time(), session_id),
        )
        await self._db.commit()


    async def unpin_session(self, session_id: str) -> None:
        await self._db.execute(
            "UPDATE sessions SET pinned_at = 0 WHERE id = ?",
            (session_id,),
        )
        await self._db.commit()


    async def save_kernel_session(
        self, session_id: str, kernel_session_id: str, kernel_kind: str = ""
    ) -> None:
        """记录外部内核自己的 session id。

        用户需要它去命令行定位这条对话（如 `dsh --session-id <id>`），
        所以要落库——否则刷新页面就丢了，只剩一次性的展示。
        """
        if not session_id:
            return
        try:
            await self._db.execute(
                "UPDATE sessions SET kernel_session_id = ?, kernel_kind = ? WHERE id = ?",
                (kernel_session_id or "", kernel_kind or "", session_id),
            )
            await self._db.commit()
        except Exception:
            logger.debug("保存 kernel_session_id 失败 session=%s", session_id, exc_info=True)


    async def load_pending_injected(self, session_id: str) -> list:
        """轻量读取会话的「补充信息」待消费队列（不加载消息）。

        供 producer 启动时恢复崩溃残留、inject 端点同步镜像用。
        """
        import json

        async with self._db.execute(
            "SELECT COALESCE(pending_injected, '[]') FROM sessions WHERE id = ?", (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return []
        try:
            items = json.loads(row[0] or "[]")
        except Exception:
            return []
        return [i for i in items if isinstance(i, dict) and i.get("id") and i.get("content")]


    async def save_pending_injected(self, session_id: str, items: list) -> None:
        """整体覆写「补充信息」待消费队列（DB 恒为活跃 run inbox 的镜像）。

        不 touch updated_at：补充信息不应把会话顶到最近列表顶部。
        """
        import json

        await self._db.execute(
            "UPDATE sessions SET pending_injected = ? WHERE id = ?",
            (json.dumps(items or [], ensure_ascii=False), session_id),
        )
        await self._db.commit()


    async def upsert_background_task(
        self,
        session_id: str,
        *,
        title: str,
        status: str,
        channel: str,
        channel_context: str = "{}",
        user_id: str = "",
        prompt: str = "",
        result: str = "",
        started_at: float | None = None,
        ended_at: float | None = None,
    ) -> None:
        """插入或更新后台任务记录（按 session_id 唯一）。"""
        await self._db.execute(
            "INSERT INTO background_tasks "
            "(session_id, title, status, channel, channel_context, user_id, prompt, result, started_at, ended_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "title=excluded.title, status=excluded.status, channel=excluded.channel, "
            "channel_context=excluded.channel_context, user_id=excluded.user_id, "
            "prompt=excluded.prompt, result=excluded.result, ended_at=excluded.ended_at",
            (
                session_id,
                title,
                status,
                channel,
                channel_context,
                user_id,
                prompt,
                result,
                started_at if started_at is not None else time.time(),
                ended_at,
            ),
        )
        await self._db.commit()


    async def list_background_tasks(self) -> list[dict]:
        """列出全部后台任务（按发起时间倒序），供 API / 启动恢复。"""
        async with self._db.execute(
            "SELECT session_id, title, status, channel, channel_context, user_id, "
            "prompt, result, started_at, ended_at FROM background_tasks "
            "ORDER BY started_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
        keys = (
            "session_id", "title", "status", "channel", "channel_context", "user_id",
            "prompt", "result", "started_at", "ended_at",
        )
        return [dict(zip(keys, row, strict=False)) for row in rows]


    async def get_background_task(self, session_id: str) -> dict | None:
        """按 session_id 读单条后台任务。"""
        async with self._db.execute(
            "SELECT session_id, title, status, channel, channel_context, user_id, "
            "prompt, result, started_at, ended_at FROM background_tasks WHERE session_id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        keys = (
            "session_id", "title", "status", "channel", "channel_context", "user_id",
            "prompt", "result", "started_at", "ended_at",
        )
        return dict(zip(keys, row, strict=False))


    async def list_pinned(self) -> list[Session]:
        sessions: list[Session] = []
        async with self._db.execute(
            "SELECT id, title, model, created_at, updated_at, COALESCE(source, 'web') as source, COALESCE(mode, '') as mode, pinned_at, "
            "COALESCE(last_read_at, 0) as last_read_at "
            "FROM sessions WHERE pinned_at > 0 ORDER BY pinned_at DESC"
        ) as cursor:
            async for row in cursor:
                sessions.append(
                    Session(
                        id=row[0],
                        title=row[1],
                        model=row[2],
                        created_at=row[3],
                        updated_at=row[4],
                        source=row[5],
                        mode=row[6],
                        pinned_at=row[7],
                        last_read_at=row[8],
                    )
                )
        return sessions


    async def touch(self, session_id: str, mark_read: bool = False) -> None:
        """推进会话 updated_at（列表排序时间戳）。

        mark_read=True 时同步把未读水位 last_read_at 一起推进，表示「落消息的同时
        用户正在查看该会话」，不应制造未读红点。用于 producer 流式落库：只要还有
        活跃 SSE 订阅者（用户窗口正开着、正接收实时流），就同步推进水位，避免
        「正在看的对话因为后台 touch 而闪烁红点」。
        """
        now = time.time()
        if mark_read:
            await self._db.execute(
                "UPDATE sessions SET updated_at = ?, last_read_at = ? WHERE id = ?",
                (now, now, session_id),
            )
        else:
            await self._db.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        await self._db.commit()


    async def mark_read(self, session_id: str) -> bool:
        """未读水位推进到当前 updated_at（前端打开会话时调用，消除红点）。

        单条 UPDATE 原子取 updated_at，避免与并发到达的消息竞态；
        last_read_at < updated_at 才写，已读时是 no-op。返回是否有实际推进。
        """
        cursor = await self._db.execute(
            "UPDATE sessions SET last_read_at = updated_at WHERE id = ? AND last_read_at < updated_at",
            (session_id,),
        )
        await self._db.commit()
        return bool(cursor.rowcount)


    async def delete(self, session_id: str) -> bool:
        async with self._db.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)) as cursor:
            if not await cursor.fetchone():
                return False
        from ethan.core.paths import user_intermediate_dir, user_uploads_dir

        shutil.rmtree(user_intermediate_dir() / session_id, ignore_errors=True)
        # 聊天附件随会话一起清（图片资产 assets/images/ 仍保留，属于既有行为）
        shutil.rmtree(user_uploads_dir() / session_id, ignore_errors=True)
        # 同 id 会话被删后重新创建时，曾归属它的附件可能还留在 _pending/（搬迁失败 / 跨端排队），
        # 不清掉会被 adopt_uploads 重新认领到新会话上。
        from ethan.core.uploads import discard_pending_for

        discard_pending_for(session_id)
        await self._db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await self._db.commit()
        return True


    async def delete_many(self, session_ids: list[str]) -> list[str]:
        """批量删除会话，返回**实际删掉**的 id 列表（不存在的会被跳过）。

        与 delete() 语义一致：清 intermediate 目录 + 删 messages + 删 sessions。
        分两趟查删的原因是「实际删了哪些」要如实回报——前端才能把「列表过期、
        有 N 个已不存在」和「真出错」区分开（同 /models/delete-batch 的做法）。
        """
        if not session_ids:
            return []
        from ethan.core.paths import user_intermediate_dir

        # 去重但保留顺序，避免重复 id 造成 rowcount 虚高
        uniq = list(dict.fromkeys(session_ids))

        existing: list[str] = []
        placeholders = ",".join("?" * len(uniq))
        async with self._db.execute(
            f"SELECT id FROM sessions WHERE id IN ({placeholders})", uniq
        ) as cursor:
            existing = [row[0] for row in await cursor.fetchall()]
        if not existing:
            return []

        inter_dir = user_intermediate_dir()
        for sid in existing:
            shutil.rmtree(inter_dir / sid, ignore_errors=True)

        ph = ",".join("?" * len(existing))
        await self._db.execute(f"DELETE FROM messages WHERE session_id IN ({ph})", existing)
        await self._db.execute(f"DELETE FROM sessions WHERE id IN ({ph})", existing)
        await self._db.commit()
        return existing
