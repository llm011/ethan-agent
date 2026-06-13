"""知识库工具 — 让 agent 能查询和添加知识库内容。"""
from ethan.core.config import CONFIG_DIR
from ethan.knowledge.base import FilesystemKnowledgeBase
from ethan.tools.base import BaseTool

_KB_DIR = CONFIG_DIR / "knowledge"
_kb = FilesystemKnowledgeBase(_KB_DIR)


class KnowledgeSearchTool(BaseTool):
    fast_path = False
    name = "knowledge_search"
    description = "Search the personal knowledge base for information on a topic. Use before web_search for topics the user has documented."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Max results (default 3)", "default": 3},
        },
        "required": ["query"],
    }

    async def run(self, query: str, limit: int = 3) -> str:
        results = _kb.search(query, limit=limit)
        if not results:
            return f"No results found in knowledge base for: {query}"
        lines = []
        for item in results:
            lines.append(f"## {item.title}\n{item.snippet()}\n[source: {item.source}]")
        return "\n\n".join(lines)


class KnowledgeAddTool(BaseTool):
    fast_path = False
    name = "knowledge_add"
    description = "Save a note or piece of information to the personal knowledge base."
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Title of the note"},
            "content": {"type": "string", "description": "Markdown content to save"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"},
        },
        "required": ["title", "content"],
    }

    async def run(self, title: str, content: str, tags: list[str] | None = None) -> str:
        path = _kb.add(title, content, tags=tags)
        return f"Saved to knowledge base: {path}"
