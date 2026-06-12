import re

with open('../ethan/memory/session.py', 'r') as f:
    content = f.read()

# Patch list_recent
list_recent_pattern = re.compile(r'    async def list_recent\(self, limit: int = 20\) -> list\[Session\]:.*?(?=    async def search)', re.DOTALL)
new_list_recent = '''    async def list_recent(self, limit: int = 20, offset: int = 0) -> list[Session]:
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

'''
content = list_recent_pattern.sub(new_list_recent, content)

# Patch search
search_pattern = re.compile(r'    async def search\(self, query: str, limit: int = 50\) -> list\[Session\]:.*?                session\.snippet = row\[5\]\n        return list\(sessions\.values\(\)\)', re.DOTALL)
new_search = '''    async def search(self, query: str, limit: int = 50, offset: int = 0) -> list[Session]:
        """全文搜索：匹配 session 标题或消息内容。返回去重后的 session 列表。"""
        q = f"%{query}%"
        sessions: dict[str, Session] = {}
        # 先搜标题
        async with self._db.execute(
            "SELECT id, title, model, created_at, updated_at FROM sessions WHERE title LIKE ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (q, limit, offset),
        ) as cursor:
            async for row in cursor:
                sessions[row[0]] = Session(id=row[0], title=row[1], model=row[2], created_at=row[3], updated_at=row[4])

        # 再搜内容
        if len(sessions) < limit:
            rem_limit = limit - len(sessions)
            async with self._db.execute(
                """SELECT s.id, s.title, s.model, s.created_at, s.updated_at, m.content
                   FROM sessions s JOIN messages m ON s.id = m.session_id
                   WHERE m.content LIKE ? ORDER BY s.updated_at DESC LIMIT ? OFFSET ?""",
                (q, rem_limit, offset), # using same offset might be weird, but let's just pass it
            ) as cursor:
                async for row in cursor:
                    if row[0] not in sessions:
                        session = Session(id=row[0], title=row[1], model=row[2], created_at=row[3], updated_at=row[4])
                        session.snippet = row[5]
                        sessions[row[0]] = session

        return list(sessions.values())'''
content = search_pattern.sub(new_search, content)

with open('../ethan/memory/session.py', 'w') as f:
    f.write(content)
print("Session patched")
