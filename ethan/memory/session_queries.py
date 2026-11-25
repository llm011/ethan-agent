"""session queries responsibilities; public facade: memory.session."""
from __future__ import annotations

from .session_models import PaginatedList, Session


class SessionQueriesMixin:
    async def list_recent(
        self,
        limit: int = 20,
        offset: int = 0,
        *,
        source: str = "",
        mode: str | None = None,
        exclude_sources: list[str] | None = None,
        exclude_title_prefixes: list[str] | None = None,
        include_title_prefixes: list[str] | None = None,
        has_images: bool = False,
    ) -> list[Session]:
        """最近会话列表。source 非空时按渠道过滤；mode 非 None 时按对话模式过滤
        （传空串可筛默认模式会话）。exclude_sources 排除指定渠道。过滤在 SQL 层做，分页对过滤后结果生效。
        include_title_prefixes 非空时只保留标题以任一前缀开头的会话（OR 关系）。
        has_images=True 时只返回含图片消息的会话（EXISTS 子查询，仅在开启时付出成本）。
        每行附带 first_query（第一条 user 消息前 80 字）填入 snippet，供列表卡片预览。"""
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
        if has_images:
            # EXISTS 短路：找到第一条 images 非空即命中，不走全表
            where.append(
                "EXISTS (SELECT 1 FROM messages m WHERE m.session_id = sessions.id AND m.images IS NOT NULL AND m.images != '[]' AND m.images != '')"
            )
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        count_params = list(params)
        params.extend([limit, offset])
        sessions: PaginatedList = PaginatedList()
        # total count for pagination
        async with self._db.execute(
            f"SELECT COUNT(*) FROM sessions{where_sql}",
            tuple(count_params),
        ) as cursor:
            total = (await cursor.fetchone())[0]
        # first_query 子查询：每行一次索引查找，取第一条 user 消息前 80 字填 snippet
        async with self._db.execute(
            "SELECT id, title, model, created_at, updated_at, COALESCE(source, 'web') as source, COALESCE(mode, '') as mode, "
            "(SELECT substr(m.content, 1, 80) FROM messages m WHERE m.session_id = sessions.id AND m.role = 'user' ORDER BY m.id LIMIT 1) as first_query, "
            "COALESCE(pinned_at, 0) as pinned_at, COALESCE(last_read_at, 0) as last_read_at "
            f"FROM sessions{where_sql} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            tuple(params),
        ) as cursor:
            async for row in cursor:
                snippet = row[7] if len(row) > 7 and row[7] else None
                sessions.append(
                    Session(
                        id=row[0],
                        title=row[1],
                        model=row[2],
                        created_at=row[3],
                        updated_at=row[4],
                        source=row[5] if len(row) > 5 else "web",
                        mode=row[6] if len(row) > 6 else "",
                        snippet=snippet,
                        pinned_at=row[8] if len(row) > 8 else 0.0,
                        last_read_at=row[9] if len(row) > 9 else 0.0,
                    )
                )
        # Attach total as attribute for callers that need it
        sessions.total = total  # type: ignore[attr-defined]
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
                sessions.append(
                    Session(
                        id=row[0],
                        title=row[1],
                        model=row[2],
                        created_at=row[3],
                        updated_at=row[4],
                        source=row[5] if len(row) > 5 else "web",
                        mode=row[6] if len(row) > 6 else "",
                    )
                )
        return sessions


    async def find_today_session(self, source: str) -> Session | None:
        """查找当天（本地时区）指定 source 的第一个 session。

        用于心跳等按天聚合的场景：一天只开一个会话窗口，所有消息都往里面放。
        返回当天最早创建的匹配 session，没有则返回 None。
        """
        from datetime import datetime, timedelta

        from ethan.core.timezone import get_local_timezone

        tz = get_local_timezone()
        now = datetime.now(tz)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        async with self._db.execute(
            "SELECT id, title, model, created_at, updated_at, "
            "COALESCE(source, 'web'), COALESCE(mode, '') "
            "FROM sessions WHERE source = ? AND created_at >= ? AND created_at < ? "
            "ORDER BY created_at ASC LIMIT 1",
            (source, today_start.timestamp(), tomorrow_start.timestamp()),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return Session(
                id=row[0],
                title=row[1],
                model=row[2],
                created_at=row[3],
                updated_at=row[4],
                source=row[5],
                mode=row[6],
            )


    async def count_today_runs(self, session_id: str) -> int:
        """统计某 session 今天（本地时区）的执行次数（按 user 消息计数）。

        用于定时任务 session 轮转：当天执行次数超阈值时新建 session，
        避免高频任务的会话无限膨胀。
        """
        from datetime import datetime, timedelta

        from ethan.core.timezone import get_local_timezone

        tz = get_local_timezone()
        now = datetime.now(tz)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        async with self._db.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role = 'user' "
            "AND created_at >= ? AND created_at < ?",
            (session_id, today_start.timestamp(), tomorrow_start.timestamp()),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


    def _session_filter_clauses(
        self,
        *,
        source: str = "",
        mode: str | None = None,
        exclude_title_prefixes: list[str] | None = None,
        include_title_prefixes: list[str] | None = None,
        has_images: bool = False,
        alias: str = "s",
    ) -> tuple[list[str], list]:
        """构造会话级过滤 SQL 片段（search/count_search 与搜索词 AND 合成用）。
        与 list_recent 的过滤语义保持一致。返回 (sql_parts, params)，列统一带 alias 前缀。"""
        parts: list[str] = []
        params: list = []
        if source:
            parts.append(f"COALESCE({alias}.source, 'web') = ?")
            params.append(source)
        if mode is not None:
            parts.append(f"COALESCE({alias}.mode, '') = ?")
            params.append(mode)
        if exclude_title_prefixes:
            for prefix in exclude_title_prefixes:
                parts.append(f"{alias}.title NOT LIKE ?")
                params.append(f"{prefix}%")
        if include_title_prefixes:
            ors = " OR ".join(f"{alias}.title LIKE ?" for _ in include_title_prefixes)
            parts.append(f"({ors})")
            params.extend(f"{prefix}%" for prefix in include_title_prefixes)
        if has_images:
            parts.append(
                "EXISTS (SELECT 1 FROM messages m WHERE m.session_id = "
                f"{alias}.id AND m.images IS NOT NULL AND m.images != '[]' AND m.images != '')"
            )
        return parts, params


    async def search(
        self,
        query: str,
        limit: int = 50,
        offset: int = 0,
        *,
        source: str = "",
        mode: str | None = None,
        exclude_title_prefixes: list[str] | None = None,
        include_title_prefixes: list[str] | None = None,
        has_images: bool = False,
    ) -> list[Session]:
        """全文搜索：匹配 session 标题或消息内容。返回去重后的 session 列表。

        支持与 list_recent 一致的会话级过滤（source/mode/标题前缀/含图），
        过滤条件在 SQL 层与搜索词 AND 合成。标题命中与内容命中需合并去重后统一按
        updated_at 排序，故多取 offset+limit 条候选，再做内存切片实现分页。
        """
        q = f"%{query}%"
        filter_parts, filter_params = self._session_filter_clauses(
            source=source, mode=mode,
            exclude_title_prefixes=exclude_title_prefixes,
            include_title_prefixes=include_title_prefixes,
            has_images=has_images,
        )
        filter_sql = (" AND " + " AND ".join(filter_parts)) if filter_parts else ""
        fetch_n = offset + limit
        sessions: dict[str, Session] = {}
        # 先搜标题
        async with self._db.execute(
            "SELECT s.id, s.title, s.model, s.created_at, s.updated_at, COALESCE(s.mode, ''), COALESCE(s.last_read_at, 0) FROM sessions s "
            f"WHERE s.title LIKE ?{filter_sql} ORDER BY s.updated_at DESC LIMIT ?",
            tuple([q] + filter_params + [fetch_n]),
        ) as cursor:
            async for row in cursor:
                sessions[row[0]] = Session(
                    id=row[0], title=row[1], model=row[2], created_at=row[3], updated_at=row[4], mode=row[5],
                    last_read_at=row[6],
                )
        # 再搜消息内容，找到对应的 session
        async with self._db.execute(
            """SELECT s.id, s.title, s.model, s.created_at, s.updated_at, m.content, COALESCE(s.mode, ''), COALESCE(s.last_read_at, 0)
               FROM sessions s
               JOIN messages m ON m.session_id = s.id
               WHERE m.content LIKE ? AND m.role IN ('user', 'assistant')""" + filter_sql +
            " ORDER BY s.updated_at DESC LIMIT ?",
            tuple([q] + filter_params + [fetch_n * 2]),
        ) as cursor:
            async for row in cursor:
                sid = row[0]
                content = row[5]
                idx = content.lower().find(query.lower())
                if idx >= 0:
                    start = max(0, idx - 20)
                    end = min(len(content), idx + len(query) + 20)
                    snippet = (
                        ("..." if start > 0 else "")
                        + content[start:end].replace("\n", " ")
                        + ("..." if end < len(content) else "")
                    )
                else:
                    snippet = None

                if sid not in sessions:
                    sessions[sid] = Session(
                        id=row[0],
                        title=row[1],
                        model=row[2],
                        created_at=row[3],
                        updated_at=row[4],
                        snippet=snippet,
                        mode=row[6],
                        last_read_at=row[7],
                    )
                elif snippet and not sessions[sid].snippet:
                    sessions[sid].snippet = snippet
        # 按 updated_at 倒序返回（含 offset 切片）
        ordered = sorted(sessions.values(), key=lambda s: s.updated_at, reverse=True)
        return ordered[offset:offset + limit]


    async def count_search(
        self,
        query: str,
        *,
        source: str = "",
        mode: str | None = None,
        exclude_title_prefixes: list[str] | None = None,
        include_title_prefixes: list[str] | None = None,
        has_images: bool = False,
    ) -> int:
        """统计搜索匹配的去重 session 总数（标题或消息内容匹配，含会话级过滤）。"""
        q = f"%{query}%"
        filter_parts, filter_params = self._session_filter_clauses(
            source=source, mode=mode,
            exclude_title_prefixes=exclude_title_prefixes,
            include_title_prefixes=include_title_prefixes,
            has_images=has_images,
        )
        filter_sql = (" AND " + " AND ".join(filter_parts)) if filter_parts else ""
        async with self._db.execute(
            """SELECT COUNT(DISTINCT s.id) FROM sessions s
               LEFT JOIN messages m ON m.session_id = s.id AND m.role IN ('user', 'assistant')
               WHERE (s.title LIKE ? OR m.content LIKE ?)""" + filter_sql,
            tuple([q, q] + filter_params),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
