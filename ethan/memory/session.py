"""Session 管理 — 对话会话的持久化。

每次对话是一个 Session，包含完整的消息历史，存储在 SQLite 中。
支持创建、恢复、列出、删除。
"""
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite

from ethan.core.config import CONFIG_DIR
from ethan.providers.base import Message

DB_PATH = CONFIG_DIR / "sessions.db"


@dataclass
class Session:
    id: str
    title: str
    model: str
    created_at: float
    updated_at: float
    messages: list[Message] = field(default_factory=list)
    snippet: str | None = None


def _generate_id() -> str:
    ts = time.strftime("%Y%m%d_%H%M")
    short = uuid.uuid4().hex[:4]
    return f"s_{ts}_{short}"


def _auto_title(messages: list[Message]) -> str:
    """从第一条用户消息提取标题。"""
    for m in messages:
        if m.role == "user" and m.content:
            title = m.content.strip().replace("\n", " ")
            return title[:40] + ("…" if len(title) > 40 else "")
    return "新对话"


class SessionStore:
    """SQLite-backed session 存储。"""

    def __init__(self, db_path: Path = DB_PATH):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
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
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def create(self, model: str) -> Session:
        now = time.time()
        session = Session(
            id=_generate_id(),
            title="新对话",
            model=model,
            created_at=now,
            updated_at=now,
        )
        await self._db.execute(
            "INSERT INTO sessions (id, title, model, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (session.id, session.title, session.model, session.created_at, session.updated_at),
        )
        await self._db.commit()
        return session

    async def save_message(self, session_id: str, msg: Message) -> None:
        import json
        tool_calls_json = json.dumps([
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in msg.tool_calls
        ]) if msg.tool_calls else None

        msg_created_at = msg.created_at if msg.created_at else time.time()

        await self._db.execute(
            "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, msg.role, msg.content, tool_calls_json, msg.tool_call_id, msg_created_at),
        )
        await self._db.commit()

    async def update_title(self, session_id: str, title: str) -> None:
        await self._db.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, time.time(), session_id),
        )
        await self._db.commit()

    async def touch(self, session_id: str) -> None:
        await self._db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (time.time(), session_id),
        )
        await self._db.commit()

    async def load(self, session_id: str) -> Session | None:
        import json
        from ethan.providers.base import ToolCall

        async with self._db.execute(
            "SELECT id, title, model, created_at, updated_at FROM sessions WHERE id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

        session = Session(
            id=row[0], title=row[1], model=row[2],
            created_at=row[3], updated_at=row[4],
        )

        async with self._db.execute(
            "SELECT role, content, tool_calls, tool_call_id, created_at FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ) as cursor:
            async for r in cursor:
                tool_calls = []
                if r[2]:
                    for tc in json.loads(r[2]):
                        tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"]))
                session.messages.append(Message(
                    role=r[0], content=r[1],
                    tool_calls=tool_calls,
                    tool_call_id=r[3],
                    created_at=r[4],
                ))

        return session

    async def list_recent(self, limit: int = 20, offset: int = 0) -> list[Session]:
        sessions = []
        async with self._db.execute(
            "SELECT id, title, model, created_at, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cursor:
            async for row in cursor:
                sessions.append(Session(
                    id=row[0], title=row[1], model=row[2],
                    created_at=row[3], updated_at=row[4],
                ))
        return sessions

    async def search(self, query: str, limit: int = 50) -> list[Session]:
        """全文搜索：匹配 session 标题或消息内容。返回去重后的 session 列表。"""
        q = f"%{query}%"
        sessions: dict[str, Session] = {}
        # 先搜标题
        async with self._db.execute(
            "SELECT id, title, model, created_at, updated_at FROM sessions WHERE title LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (q, limit),
        ) as cursor:
            async for row in cursor:
                sessions[row[0]] = Session(id=row[0], title=row[1], model=row[2], created_at=row[3], updated_at=row[4])
        # 再搜消息内容，找到对应的 session
        async with self._db.execute(
            """SELECT s.id, s.title, s.model, s.created_at, s.updated_at, m.content
               FROM sessions s
               JOIN messages m ON m.session_id = s.id
               WHERE m.content LIKE ? AND m.role IN ('user', 'assistant')
               ORDER BY s.updated_at DESC LIMIT ?""",
            (q, limit * 2),
        ) as cursor:
            async for row in cursor:
                sid = row[0]
                content = row[5]
                idx = content.lower().find(query.lower())
                if idx >= 0:
                    start = max(0, idx - 20)
                    end = min(len(content), idx + len(query) + 20)
                    snippet = ("..." if start > 0 else "") + content[start:end].replace("\n", " ") + ("..." if end < len(content) else "")
                else:
                    snippet = None

                if sid not in sessions:
                    sessions[sid] = Session(id=row[0], title=row[1], model=row[2], created_at=row[3], updated_at=row[4], snippet=snippet)
                elif snippet and not sessions[sid].snippet:
                    sessions[sid].snippet = snippet
        # 按 updated_at 倒序返回
        return sorted(sessions.values(), key=lambda s: s.updated_at, reverse=True)[:limit]

    async def cleanup_empty(self) -> int:
        """删除没有任何消息的空 session，返回删除数量。"""
        cursor = await self._db.execute(
            "DELETE FROM sessions WHERE id NOT IN (SELECT DISTINCT session_id FROM messages)"
        )
        await self._db.commit()
        return cursor.rowcount

