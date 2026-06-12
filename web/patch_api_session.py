import re

with open('../ethan/interface/api.py', 'r') as f:
    content = f.read()

# Patch list_sessions
list_sessions_pattern = re.compile(r'async def list_sessions\(limit: int = 50, q: str \| None = None\):.*?    \]\}', re.DOTALL)
new_list_sessions = '''async def list_sessions(limit: int = 50, offset: int = 0, q: str | None = None):
    store = SessionStore()
    await store.init()
    if q:
        sessions = await store.search(q, limit, offset)
    else:
        sessions = await store.list_recent(limit, offset)
    await store.close()
    return {"sessions": [
        {"id": s.id, "title": s.title, "model": s.model, "created_at": s.created_at, "updated_at": s.updated_at, "snippet": getattr(s, "snippet", None)}
        for s in sessions
    ]}'''
content = list_sessions_pattern.sub(new_list_sessions, content)

with open('../ethan/interface/api.py', 'w') as f:
    f.write(content)
print("API session patched")
