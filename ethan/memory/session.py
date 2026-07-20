"""Session 管理 — 对话会话的持久化。

每次对话是一个 Session，包含完整的消息历史，存储在 SQLite 中。
支持创建、恢复、列出、删除。
"""
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite

from ethan.providers.base import Message


@dataclass
class Session:
    id: str
    title: str
    model: str
    created_at: float
    updated_at: float
    messages: list[Message] = field(default_factory=list)
    snippet: str | None = None
    source: str = "web"  # web | repl | lark | cli | desktop | custom
    mode: str = ""  # "" = 工作助手; 规范英文 key，如 "legal"/"companion"（见 core/modes.py）


def _generate_id() -> str:
    ts = time.strftime("%Y%m%d_%H%M")
    short = uuid.uuid4().hex[:4]
    return f"s_{ts}_{short}"


def _auto_title(messages: list[Message]) -> str:
    """从第一条用户消息提取占位标题（已清洗 markdown / 命令前缀）。"""
    import re
    for m in messages:
        if m.role == "user" and m.content:
            t = m.content.strip()
            # 去掉 markdown 标记（**粗体**、# 标题、`代码`、_斜体_、~删除~）
            t = re.sub(r'[*#`_~]', '', t)
            # 去掉命令前缀（/help xxx → xxx；/review url 保留 url 由 _review_title 处理）
            t = re.sub(r'^/(?:help|new|model|token|btw|stop)\s+', '', t)
            t = t.replace("\n", " ").strip()
            if not t:
                t = m.content.strip().replace("\n", " ")
            return t[:40] + ("…" if len(t) > 40 else "")
    return "新对话"


def _count_content(text: str) -> int:
    """中英文混合的内容量度：中文按字数，英文按单词数，取两者之和。

    例：
      "你好" → 2
      "hello world" → 2
      "你好 hello world" → 4
      "hi" → 1
    """
    import re
    if not text:
        return 0
    # 中日韩字符（含全角标点）每个算 1
    cjk = len(re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', text))
    # 去掉 CJK 后按空白拆分英文单词
    non_cjk = re.sub(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', ' ', text)
    words = [w for w in non_cjk.split() if w and any(c.isalnum() for c in w)]
    return cjk + len(words)


# 首条问题内容量少于该值视为「太短」，推迟到第 2 轮再生成智能标题
# （中文按字、英文按单词，混合求和）
SHORT_QUESTION_CHARS = 3


async def _generate_smart_title(messages: list[Message], retries: int = 3) -> str | None:
    """用廉价模型生成 ≤20 字的简洁标题；lite 模型可用时失败重试 retries 次。

    返回 None 表示「没生成出来」，调用方据此决定是否保留占位标题，绝不拿兜底值覆盖：
    - 没有可用的 lite 模型（create_provider 抛错）→ 返回 None，不重试。
    - lite 模型可用但调用全部失败（超时/限流/endpoint 抖动）→ 退避重试后返回 None。
    """
    import asyncio

    from ethan.core.config import get_config
    from ethan.memory.consolidator import get_lite_model
    from ethan.providers.manager import create_provider

    turns = [(m.role, m.content[:100]) for m in messages if m.role in ("user", "assistant") and m.content][:6]
    if not turns:
        return None

    conv = "\n".join(f"{'用户' if r == 'user' else 'AI'}: {c}" for r, c in turns)
    prompt = f"根据以下对话，用不超过15个汉字或30个英文字符生成一个简洁的标题，只输出标题本身：\n\n{conv}"

    try:
        cfg = get_config()
        cheap_model = get_lite_model(cfg.defaults.model)
        provider = create_provider(cheap_model)
    except Exception:
        return None

    for attempt in range(retries):
        try:
            resp = await provider.chat([Message(role="user", content=prompt)],
                                       system="你是一个标题生成助手，只输出标题，不加引号或标点。")
            title = resp.content.strip().strip('"\'""').strip()
            if title:
                return title[:20]
        except Exception:
            pass
        if attempt < retries - 1:
            await asyncio.sleep(0.5 * (attempt + 1))
    return None


_PROTECTED_PREFIXES = ("[定时]", "[后台]", "[心跳]")


def _review_title(text: str) -> str | None:
    """从 /review 命令中解析 PR 标题，格式如 'PR #70 llm011/ethan-agent'。"""
    import re as _re
    t = text.strip()
    if not (t.lower().startswith("/review ") or t.lower() == "/review"):
        return None
    target = t[7:].strip()
    if not target:
        return None
    # 匹配 GitHub PR URL: github.com/owner/repo/pull/123
    m = _re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)", target)
    if m:
        return f"PR #{m.group(2)} {m.group(1)}"
    # 匹配 GitLab MR URL: gitlab.com/owner/repo/-/merge_requests/123
    m = _re.search(r"gitlab\.com/([^/]+/[^/]+)/-/merge_requests/(\d+)", target)
    if m:
        return f"MR !{m.group(2)} {m.group(1)}"
    return None


async def decide_title(messages: list[Message], current_title: str = "") -> str | None:
    """统一的标题策略，返回应设置的标题；返回 None 表示本轮不改标题。

    - 第 1 轮：首条问题内容量 ≥3（中文按字、英文按单词）直接生成智能标题；否则先用清洗后的原文占位。
    - 第 2 轮：仅当首条问题太短（之前是占位）时补生成智能标题；失败则放弃，保留占位。
    - 第 3 轮起：不再自动重试，避免用户突然看到标题变化。用户可用 🔄 按钮手动重试。
    """
    # 保护特殊标题（定时/后台/心跳等），不被自动标题覆盖
    if any(current_title.startswith(p) for p in _PROTECTED_PREFIXES):
        return None

    user_msgs = [m for m in messages if m.role == "user" and m.content]
    n = len(user_msgs)
    if n == 1:
        first = user_msgs[0].content.strip()
        # /review 命令：直接从 URL 解析出 "PR #xx owner/repo" 格式标题
        review = _review_title(first)
        if review:
            return review
        if _count_content(first) >= SHORT_QUESTION_CHARS:
            return await _generate_smart_title(messages) or _auto_title(messages)
        return _auto_title(messages)
    if n == 2:
        first = user_msgs[0].content.strip()
        if _count_content(first) < SHORT_QUESTION_CHARS:
            return await _generate_smart_title(messages) or _auto_title(messages)
        # 首条够长但 round 1 智能标题失败（或被 API 路径用首条消息当了初始标题）：
        # 仍是占位/截断标题时再试一次智能生成；已有好标题则跳过
        if any(current_title == p for p in ("", "新对话")) or current_title == _auto_title(messages):
            return await _generate_smart_title(messages) or _auto_title(messages)
        return None
    # 第 3 轮起不再自动重试：占位标题已足够可读，用户可手动点 🔄 触发 regen_title
    return None


class SessionStore:
    """SQLite-backed session 存储。"""

    def __init__(self, db_path: Path | None = None):
        # 不传时按当前 user context 求值，避免模块级缓存击穿 per-user 隔离
        if db_path is None:
            from ethan.core.paths import user_sessions_db_path
            db_path = user_sessions_db_path()
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        # WAL + busy_timeout：sessions.db 需支持主 chat 流程写 + 后台 _maybe_consolidate
        # / collect_signals / 12 点夜间任务并发读。非 WAL 模式下读会阻塞写，
        # 且没有 busy_timeout 兜底会立即抛 database is locked，异常被 try/except
        # 吞掉后可能留下 -shm/-wal 残留文件破坏一致性。
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
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
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        await self._db.commit()
        # Migration: add columns if they don't exist (for existing databases)
        for col, definition in [("created_at", "REAL"), ("usage", "TEXT"), ("tool_steps", "TEXT"), ("thought", "TEXT"), ("quote", "TEXT"), ("a2ui", "TEXT"), ("mcp_apps", "TEXT"), ("images", "TEXT"), ("matched_skills", "TEXT"), ("ttfb_ms", "INTEGER"), ("total_ms", "INTEGER")]:
            try:
                await self._db.execute(f"ALTER TABLE messages ADD COLUMN {col} {definition}")
                await self._db.commit()
            except Exception:
                pass  # Column already exists
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

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def create(self, model: str, source: str = "web", mode: str = "") -> Session:
        now = time.time()
        session = Session(
            id=_generate_id(),
            title="新对话",
            model=model,
            created_at=now,
            updated_at=now,
            source=source,
            mode=mode,
        )
        await self._db.execute(
            "INSERT INTO sessions (id, title, model, created_at, updated_at, source, mode) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session.id, session.title, session.model, session.created_at, session.updated_at, source, mode),
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
        )
        await self._db.execute(
            "INSERT INTO sessions (id, title, model, created_at, updated_at, source, mode) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session.id, session.title, session.model, session.created_at, session.updated_at, source, mode),
        )
        await self._db.commit()
        return session

    async def save_message(self, session_id: str, msg: Message) -> int:
        import json
        tool_calls_json = json.dumps([
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in msg.tool_calls
        ]) if msg.tool_calls else None

        msg_created_at = msg.created_at if msg.created_at else time.time()
        usage_json = json.dumps(msg.usage) if msg.usage else None
        tool_steps_json = json.dumps(msg.tool_steps) if msg.tool_steps else None
        quote_json = json.dumps(msg.quote, ensure_ascii=False) if msg.quote else None
        a2ui_json = json.dumps(msg.a2ui, ensure_ascii=False) if msg.a2ui else None
        mcp_apps_json = json.dumps(msg.mcp_apps, ensure_ascii=False) if msg.mcp_apps else None
        images_json = json.dumps(msg.images, ensure_ascii=False) if msg.images else None
        matched_skills_json = json.dumps(msg.matched_skills, ensure_ascii=False) if msg.matched_skills else None

        cursor = await self._db.execute(
            "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, created_at, usage, tool_steps, thought, quote, a2ui, images, matched_skills, ttfb_ms, total_ms, mcp_apps) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, msg.role, msg.content, tool_calls_json, msg.tool_call_id, msg_created_at, usage_json, tool_steps_json, msg.thought, quote_json, a2ui_json, images_json, matched_skills_json, msg.ttfb_ms, msg.total_ms, mcp_apps_json),
        )
        await self._db.commit()
        return cursor.lastrowid  # 返回行 id，供「进度消息」复用同一条行做覆盖式 UPDATE

    async def update_message(self, row_id: int, session_id: str, msg: Message) -> None:
        """按主键 id 更新一条消息。

        用于「工具进度实时落库」：流式过程中先 INSERT 一条占位 assistant 消息（content 空、
        tool_steps 为当前步骤），每完成一个工具就 UPDATE 同一行覆盖 tool_steps；流结束后
        再 UPDATE 写入最终正文/usage/a2ui。这样工具过程实时留存，且整轮只占一行。
        """
        import json
        tool_calls_json = json.dumps([
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in msg.tool_calls
        ]) if msg.tool_calls else None
        usage_json = json.dumps(msg.usage) if msg.usage else None
        tool_steps_json = json.dumps(msg.tool_steps) if msg.tool_steps else None
        a2ui_json = json.dumps(msg.a2ui, ensure_ascii=False) if msg.a2ui else None
        mcp_apps_json = json.dumps(msg.mcp_apps, ensure_ascii=False) if msg.mcp_apps else None
        matched_skills_json = json.dumps(msg.matched_skills, ensure_ascii=False) if msg.matched_skills else None

        await self._db.execute(
            "UPDATE messages SET content=?, tool_calls=?, usage=?, tool_steps=?, thought=?, a2ui=?, mcp_apps=?, matched_skills=?, ttfb_ms=?, total_ms=?, created_at=? "
            "WHERE id=? AND session_id=?",
            (msg.content, tool_calls_json, usage_json, tool_steps_json, msg.thought, a2ui_json,
             mcp_apps_json, matched_skills_json, msg.ttfb_ms, msg.total_ms, msg.created_at or time.time(), row_id, session_id),
        )
        await self._db.commit()

    async def delete_message_by_id(self, row_id: int) -> None:
        """按主键 id 删除单条消息（新 run 替换旧 run 时丢弃残留的进度占位行用）。"""
        await self._db.execute("DELETE FROM messages WHERE id=?", (row_id,))
        await self._db.commit()


    async def update_title(self, session_id: str, title: str) -> None:
        await self._db.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, time.time(), session_id),
        )
        await self._db.commit()

    async def update_mode(self, session_id: str, mode: str) -> None:
        await self._db.execute(
            "UPDATE sessions SET mode = ?, updated_at = ? WHERE id = ?",
            (mode, time.time(), session_id),
        )
        await self._db.commit()

    async def touch(self, session_id: str) -> None:
        await self._db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (time.time(), session_id),
        )
        await self._db.commit()

    async def delete(self, session_id: str) -> bool:
        async with self._db.execute(
            "SELECT id FROM sessions WHERE id = ?", (session_id,)
        ) as cursor:
            if not await cursor.fetchone():
                return False
        await self._db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await self._db.commit()
        return True

    async def replace_messages(self, session_id: str, messages: list[Message]) -> None:
        """用新消息集替换该 session 的全部消息（/compact 压缩历史用）。

        保留 session 记录本身，只清空 messages 再重写，并 touch 更新时间。
        """
        await self._db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await self._db.commit()
        for msg in messages:
            await self.save_message(session_id, msg)
        await self.touch(session_id)

    async def load(self, session_id: str) -> Session | None:
        import json

        from ethan.providers.base import ToolCall

        async with self._db.execute(
            "SELECT id, title, model, created_at, updated_at, COALESCE(source, 'web'), COALESCE(mode, '') FROM sessions WHERE id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None

        session = Session(
            id=row[0], title=row[1], model=row[2],
            created_at=row[3], updated_at=row[4],
            source=row[5], mode=row[6],
        )

        async with self._db.execute(
            "SELECT id, role, content, tool_calls, tool_call_id, created_at, usage, tool_steps, thought, quote, a2ui, images, matched_skills, ttfb_ms, total_ms, mcp_apps FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ) as cursor:
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
                session.messages.append(Message(
                    role=r[1], content=r[2],
                    id=r[0],
                    tool_calls=tool_calls,
                    tool_call_id=r[4],
                    created_at=r[5],
                    usage=usage,
                    tool_steps=tool_steps,
                    thought=r[8],
                    quote=quote,
                    a2ui=a2ui,
                    images=images,
                    matched_skills=matched_skills,
                    ttfb_ms=ttfb_ms,
                    total_ms=total_ms,
                    mcp_apps=mcp_apps,
                ))

        return session

    async def list_recent(self, limit: int = 20, offset: int = 0,
                          source: str = "", mode: str | None = None,
                          exclude_sources: list[str] | None = None,
                          exclude_title_prefixes: list[str] | None = None,
                          include_title_prefixes: list[str] | None = None) -> list[Session]:
        """最近会话列表。source 非空时按渠道过滤；mode 非 None 时按对话模式过滤
        （传空串可筛默认模式会话）。exclude_sources 排除指定渠道。过滤在 SQL 层做，分页对过滤后结果生效。
        include_title_prefixes 非空时只保留标题以任一前缀开头的会话（OR 关系）。"""
        where = []
        params: list = []
        if source:
            where.append("COALESCE(source, 'web') = ?")
            params.append(source)
        if mode is not None:
            where.append("COALESCE(mode, '') = ?")
            params.append(mode)
        if exclude_sources:
            placeholders = ",".join("?" * len(exclude_sources))
            where.append(f"COALESCE(source, 'web') NOT IN ({placeholders})")
            params.extend(exclude_sources)
        if exclude_title_prefixes:
            for prefix in exclude_title_prefixes:
                where.append("title NOT LIKE ?")
                params.append(f"{prefix}%")
        if include_title_prefixes:
            ors = " OR ".join("title LIKE ?" for _ in include_title_prefixes)
            where.append(f"({ors})")
            params.extend(f"{prefix}%" for prefix in include_title_prefixes)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        params.extend([limit, offset])
        sessions = []
        async with self._db.execute(
            "SELECT id, title, model, created_at, updated_at, COALESCE(source, 'web') as source, COALESCE(mode, '') as mode "
            f"FROM sessions{where_sql} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            tuple(params),
        ) as cursor:
            async for row in cursor:
                sessions.append(Session(
                    id=row[0], title=row[1], model=row[2],
                    created_at=row[3], updated_at=row[4],
                    source=row[5] if len(row) > 5 else "web",
                    mode=row[6] if len(row) > 6 else "",
                ))
        return sessions

    async def list_in_range(
        self,
        start_ts: float,
        end_ts: float,
        *,
        exclude_sources: list[str] | None = None,
        exclude_title_prefixes: list[str] | None = None,
    ) -> list[Session]:
        """List sessions created in ``[start_ts, end_ts)``.

        Daily memory consolidation needs a precise local-day window.  Keeping
        the filtering in SQL avoids scanning an arbitrary ``list_recent`` cap
        and missing sessions on high-volume days.
        """
        if end_ts <= start_ts:
            raise ValueError("end_ts must be greater than start_ts")
        where = ["created_at >= ?", "created_at < ?"]
        params: list = [float(start_ts), float(end_ts)]
        if exclude_sources:
            placeholders = ",".join("?" * len(exclude_sources))
            where.append(f"COALESCE(source, 'web') NOT IN ({placeholders})")
            params.extend(exclude_sources)
        if exclude_title_prefixes:
            for prefix in exclude_title_prefixes:
                where.append("title NOT LIKE ?")
                params.append(f"{prefix}%")
        sessions: list[Session] = []
        async with self._db.execute(
            "SELECT id, title, model, created_at, updated_at, "
            "COALESCE(source, 'web') as source, COALESCE(mode, '') as mode "
            f"FROM sessions WHERE {' AND '.join(where)} ORDER BY created_at ASC",
            tuple(params),
        ) as cursor:
            async for row in cursor:
                sessions.append(Session(
                    id=row[0], title=row[1], model=row[2],
                    created_at=row[3], updated_at=row[4],
                    source=row[5] if len(row) > 5 else "web",
                    mode=row[6] if len(row) > 6 else "",
                ))
        return sessions

    async def search(self, query: str, limit: int = 50) -> list[Session]:
        """全文搜索：匹配 session 标题或消息内容。返回去重后的 session 列表。"""
        q = f"%{query}%"
        sessions: dict[str, Session] = {}
        # 先搜标题
        async with self._db.execute(
            "SELECT id, title, model, created_at, updated_at, COALESCE(mode, '') FROM sessions WHERE title LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (q, limit),
        ) as cursor:
            async for row in cursor:
                sessions[row[0]] = Session(id=row[0], title=row[1], model=row[2], created_at=row[3], updated_at=row[4], mode=row[5])
        # 再搜消息内容，找到对应的 session
        async with self._db.execute(
            """SELECT s.id, s.title, s.model, s.created_at, s.updated_at, m.content, COALESCE(s.mode, '')
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
                    sessions[sid] = Session(id=row[0], title=row[1], model=row[2], created_at=row[3], updated_at=row[4], snippet=snippet, mode=row[6])
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

    # ── sessions.db 轮转（防止无限膨胀） ──────────────────────────

    SESSION_DB_SIZE_THRESHOLD = 10 * 1024 * 1024  # 10 MB

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
        async with self._db.execute(
            "SELECT MIN(created_at), MAX(created_at) FROM sessions"
        ) as cursor:
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


def list_archived_dbs() -> list[tuple[Path, str, str]]:
    """列出当前用户的所有归档 session DB，按起始日期排序。

    返回 [(path, start_date, end_date), ...]
    如 [(archive/sessions.2026-01-01~2026-02-10.db, '2026-01-01', '2026-02-10'), ...]
    """
    import re

    from ethan.core.paths import user_session_archive_dir

    archive_dir = user_session_archive_dir()
    if not archive_dir.exists():
        return []
    pattern = re.compile(r"sessions\.(\d{4}-\d{2}-\d{2})~(\d{4}-\d{2}-\d{2})(?:\.\d+)?\.db")
    result = []
    for f in archive_dir.glob("sessions.*~*.db"):
        m = pattern.match(f.name)
        if m:
            result.append((f, m.group(1), m.group(2)))
    result.sort(key=lambda x: x[1])
    return result

