"""session maintenance responsibilities; public facade: memory.session."""
from __future__ import annotations


class SessionMaintenanceMixin:
    async def cleanup_empty(self) -> int:
        """删除没有任何消息的空 session，返回删除数量。"""
        cursor = await self._db.execute(
            "DELETE FROM sessions WHERE id NOT IN (SELECT DISTINCT session_id FROM messages)"
        )
        await self._db.commit()
        return cursor.rowcount


    async def cleanup_trivial(self) -> tuple[int, list[str]]:
        """删除无意义会话：空会话 + 只含试探性消息的会话 + 无回复的单条会话，返回 (deleted_count, deleted_ids)。"""
        import re

        trivial_patterns = re.compile(
            r"^(h[ei]|hi|hello|hey|yo|test|测试|你好|你是谁|谁|在吗|在不在|你是什么|什么|哈喽|嗨|ok|okay|嗯|哦|喂|1|11|111|aaa|啊|哈|嘿|\.+|。+|…+|\?+|？+|!+|！+)$",
            re.IGNORECASE,
        )
        max_msg_count = 4
        deleted_ids: list[str] = []

        # 1) 空会话（无任何消息）
        async with self._db.execute(
            "SELECT id FROM sessions WHERE id NOT IN (SELECT DISTINCT session_id FROM messages)"
        ) as cursor:
            deleted_ids.extend(row[0] for row in await cursor.fetchall())

        # 2) 只有 user 消息且 assistant 回复为空的会话（发了但没得到回复，abandoned）
        async with self._db.execute(
            """
            SELECT s.id
            FROM sessions s
            JOIN messages m ON m.session_id = s.id
            GROUP BY s.id
            HAVING COUNT(m.id) <= 2
               AND SUM(CASE WHEN m.role = 'assistant' AND length(trim(m.content)) > 0 THEN 1 ELSE 0 END) = 0
            """,
        ) as cursor:
            for row in await cursor.fetchall():
                if row[0] not in deleted_ids:
                    deleted_ids.append(row[0])

        # 3) 消息内容全为试探性的会话
        async with self._db.execute(
            """
            SELECT s.id, GROUP_CONCAT(m.content, '\x1f') as contents, COUNT(m.id) as cnt
            FROM sessions s
            JOIN messages m ON m.session_id = s.id
            WHERE m.role IN ('user', 'assistant')
            GROUP BY s.id
            HAVING cnt <= ?
            """,
            (max_msg_count,),
        ) as cursor:
            rows = await cursor.fetchall()

        for sid, contents_concat, _ in rows:
            if sid in deleted_ids:
                continue
            msgs = contents_concat.split("\x1f") if contents_concat else []
            if all(trivial_patterns.match(m.strip()) for m in msgs if m.strip()):
                deleted_ids.append(sid)

        if deleted_ids:
            placeholders = ",".join("?" * len(deleted_ids))
            await self._db.execute(f"DELETE FROM sessions WHERE id IN ({placeholders})", deleted_ids)
            await self._db.commit()

        return len(deleted_ids), deleted_ids


    SESSION_DB_SIZE_THRESHOLD = (
        500 * 1024 * 1024
    )  # 500 MB — SQLite 可轻松处理 GB 级数据，10MB 阈值过于激进导致频繁清空用户数据


    async def rotate_if_needed(self, threshold: int = SESSION_DB_SIZE_THRESHOLD) -> bool:
        """如果 sessions.db 超过 threshold，快照归档 + 清空 active db。

        归档文件名按日期跨度命名：sessions.2026-01-01~2026-02-10.db
        使用 VACUUM INTO 做原子快照（不受并发连接影响），然后 DELETE + VACUUM 回收空间。
        返回 True 表示执行了轮转。
        """
        if not self._db_path.exists():
            return False
        size = self._db_path.stat().st_size
        if size < threshold:
            return False

        # 查日期跨度
        async with self._db.execute("SELECT MIN(created_at), MAX(created_at) FROM sessions") as cursor:
            row = await cursor.fetchone()
        if not row or row[0] is None:
            return False  # 空库不轮转

        from datetime import datetime

        start_date = datetime.fromtimestamp(row[0]).strftime("%Y-%m-%d")
        end_date = datetime.fromtimestamp(row[1]).strftime("%Y-%m-%d")

        from ethan.core.paths import user_session_archive_dir

        archive_dir = user_session_archive_dir()
        archive_dir.mkdir(parents=True, exist_ok=True)

        # 文件名：sessions.{start}~{end}.db，重名加序号
        base_name = f"sessions.{start_date}~{end_date}.db"
        archive_path = archive_dir / base_name
        counter = 1
        while archive_path.exists():
            archive_path = archive_dir / f"sessions.{start_date}~{end_date}.{counter}.db"
            counter += 1

        # VACUUM INTO：原子快照，不受并发连接影响（SQLite ≥ 3.27）
        try:
            await self._db.execute(f"VACUUM INTO '{archive_path}'")
        except Exception:
            # VACUUM INTO 不可用时 fallback：文件级复制
            import shutil

            shutil.copy2(str(self._db_path), str(archive_path))

        # 清空 active db
        await self._db.execute("DELETE FROM messages")
        await self._db.execute("DELETE FROM sessions")
        await self._db.commit()

        # 回收空间（VACUUM 需要无事务，可能因并发连接失败 — 失败也无妨，空页会被复用）
        try:
            await self._db.execute("VACUUM")
        except Exception:
            pass

        import logging

        logging.getLogger(__name__).info(
            "[SessionStore] Rotated sessions.db (%.1f MB → %s), archive: %s",
            size / 1024 / 1024,
            archive_path.name,
            archive_path,
        )
        return True
