"""session schema responsibilities; public facade: memory.session."""
from __future__ import annotations

import logging
import time
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)


class SessionSchemaMixin:
    def __init__(self, db_path: Path | None = None, *, _singleton: bool = False):
        # 不传时按当前 user context 求值，避免模块级缓存击穿 per-user 隔离
        if db_path is None:
            from ethan.core.paths import user_sessions_db_path

            db_path = user_sessions_db_path()
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._singleton = _singleton


    async def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # 清理历史 WAL 残留（已切换到 DELETE 模式，-wal/-shm 不再产生）
        for suffix in ("-wal", "-shm"):
            self._db_path.with_name(self._db_path.name + suffix).unlink(missing_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        # DELETE 模式：journal_mode 是 DB 级持久化属性，曾经设过 WAL 就会默认恢复 WAL。
        # 必须每次连接后显式 PRAGMA journal_mode=DELETE，否则会重新生成 -wal/-shm 文件。
        # DELETE 模式下写时用 rollback journal，commit 后立即删除，无 -wal/-shm 残留。
        await self._db.execute("PRAGMA journal_mode=DELETE")
        await self._db.execute("PRAGMA busy_timeout=30000")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                source TEXT NOT NULL DEFAULT 'web',
                mode TEXT NOT NULL DEFAULT ''
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_calls TEXT,
                tool_call_id TEXT,
                created_at REAL,
                usage TEXT,
                intermediate_blob_id INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'completed',
                reasoning TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS message_wire_transcripts (
                message_id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                state TEXT NOT NULL,
                FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS run_checkpoints (
                message_id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                state TEXT NOT NULL,
                FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS background_tasks (
                session_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                channel TEXT NOT NULL DEFAULT 'web',
                channel_context TEXT NOT NULL DEFAULT '{}',
                user_id TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '',
                started_at REAL NOT NULL,
                ended_at REAL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS message_intermediate_blobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'process',
                file_path TEXT NOT NULL,
                format TEXT NOT NULL DEFAULT 'markdown',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                preview_text TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        await self._db.commit()
        # Migration: add columns if they don't exist (for existing databases)
        for col, definition in [
            ("created_at", "REAL"),
            ("usage", "TEXT"),
            ("tool_steps", "TEXT"),
            ("thought", "TEXT"),
            ("quote", "TEXT"),
            ("a2ui", "TEXT"),
            ("mcp_apps", "TEXT"),
            ("images", "TEXT"),
            ("matched_skills", "TEXT"),
            ("ttfb_ms", "INTEGER"),
            ("total_ms", "INTEGER"),
            ("cards", "TEXT"),
            ("intermediate_blob_id", "INTEGER NOT NULL DEFAULT 0"),
            ("status", "TEXT NOT NULL DEFAULT 'completed'"),
            ("reasoning", "TEXT NOT NULL DEFAULT ''"),
            ("model", "TEXT"),
            ("error", "TEXT NOT NULL DEFAULT ''"),
            ("files", "TEXT"),  # 非图片附件元数据，见 ethan/core/uploads.py
            # 运行检查点（条目 6）：中断/超时时保存的结构化运行快照（当前轮次、
            # 已完成/待办步骤、最后一次工具调用等），供「继续」精确接续而非重头再来。
            ("run_checkpoint", "TEXT NOT NULL DEFAULT ''"),
        ]:
            try:
                await self._db.execute(f"ALTER TABLE messages ADD COLUMN {col} {definition}")
                await self._db.commit()
            except Exception:
                pass  # Column already exists
        # messages.session_id 索引：files 路由的 _session_grants（下载/预览鉴权）每次都
        # SELECT cards FROM messages WHERE session_id=?，无索引会全表扫；长会话 + 一页多图
        # 的 N+1 直链请求下会卡事件循环。IF NOT EXISTS 幂等。
        try:
            await self._db.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)")
            await self._db.commit()
        except Exception:
            pass
        # sessions.updated_at 索引：会话列表/轮询按 updated_at DESC 取前 N 条。
        # 无索引时 SQLite 要把 777 行全读出来再建临时 B-TREE 排序（EXPLAIN 实测
        # "SCAN sessions + USE TEMP B-TREE FOR ORDER BY"）；有索引后直接倒序扫描
        # 取前 N 行即可，数据量涨到几万会话时差距会非常明显。
        # 同理建 created_at 索引，日记忆整理/归档按创建时间范围查。
        try:
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC)"
            )
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at)"
            )
            await self._db.commit()
        except Exception:
            pass
        # Migration: sessions.mode（对话模式持久化）
        try:
            await self._db.execute("ALTER TABLE sessions ADD COLUMN mode TEXT NOT NULL DEFAULT ''")
            await self._db.commit()
        except Exception:
            pass  # Column already exists
        # Migration: 历史 mode 值从中文 key 迁移到英文 slug（key 规范化，见 core/modes.py）。
        # 幂等：已是新值或无此类行时 UPDATE 影响 0 行。
        try:
            for old, new in (("法律", "legal"), ("陪伴", "companion")):
                await self._db.execute("UPDATE sessions SET mode = ? WHERE mode = ?", (new, old))
            await self._db.commit()
        except Exception:
            pass
        # Migration: sessions.pinned_at（置顶时间戳）
        try:
            await self._db.execute("ALTER TABLE sessions ADD COLUMN pinned_at REAL NOT NULL DEFAULT 0")
            await self._db.commit()
        except Exception:
            pass
        # Migration: sessions.last_read_at（未读红点水位）。存量会话回填为已读
        # （水位=updated_at），避免升级后满屏红点；新会话由 create 显式写水位，
        # mark_read 端点写入的值恒 > 0，回填只命中历史行，幂等。
        try:
            await self._db.execute("ALTER TABLE sessions ADD COLUMN last_read_at REAL NOT NULL DEFAULT 0")
            await self._db.commit()
        except Exception:
            pass  # Column already exists
        try:
            await self._db.execute("UPDATE sessions SET last_read_at = updated_at WHERE last_read_at = 0")
            await self._db.commit()
        except Exception:
            pass
        # Migration: sessions.pending_injected（运行中补充信息待消费队列，JSON 数组）
        try:
            await self._db.execute("ALTER TABLE sessions ADD COLUMN pending_injected TEXT NOT NULL DEFAULT '[]'")
            await self._db.commit()
        except Exception:
            pass
        # Migration: sessions.kernel_session_id / kernel_kind
        # 外部内核（DSH/Claude）自己的会话 id，用户拿它去命令行定位这条对话。
        for _col, _ddl in (
            ("kernel_session_id", "ALTER TABLE sessions ADD COLUMN kernel_session_id TEXT NOT NULL DEFAULT ''"),
            ("kernel_kind", "ALTER TABLE sessions ADD COLUMN kernel_kind TEXT NOT NULL DEFAULT ''"),
        ):
            try:
                await self._db.execute(_ddl)
                await self._db.commit()
            except Exception:
                pass  # 已存在
        # 启动扫描：把上次进程崩溃/重启时仍处于 running 的消息标记为 interrupted。
        # running 状态只存在于进程内存（ChatRun），进程重启后这些消息永远不会被更新，
        # 必须在此兜底标记，前端才能据此显示「继续」按钮。
        try:
            cursor = await self._db.execute("UPDATE messages SET status='interrupted' WHERE status='running'")
            if cursor.rowcount > 0:
                await self._db.commit()
                logger.info("[SessionStore] Marked %d interrupted messages on startup", cursor.rowcount)
        except Exception:
            pass
        # 后台任务：进程重启时 daemon 线程已死，仍处于 running 的任务无法继续执行，
        # 标为 interrupted（保留 session 里已生成的部分结果，用户可手动「继续」）。
        try:
            cursor = await self._db.execute(
                "UPDATE background_tasks SET status='interrupted', ended_at=? WHERE status='running'",
                (time.time(),),
            )
            if cursor.rowcount > 0:
                await self._db.commit()
                logger.info("[SessionStore] Marked %d interrupted background tasks on startup", cursor.rowcount)
        except Exception:
            pass

        # 存量数据迁移：把历史消息里内联的图片 base64 卡片落盘为资产文件。
        # 一次性把几十 MB 的 data URI 从 DB 里挪走，否则每次点开会话都要传/解析数 MB。
        await self._migrate_inline_image_cards_once()


    async def close(self) -> None:
        if self._singleton:
            return  # 单例连接由进程生命周期管理，不关闭
        if self._db:
            await self._db.close()
