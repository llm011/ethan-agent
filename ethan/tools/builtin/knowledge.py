"""知识库工具 — 让 agent 能查询和添加知识库内容。"""
from ethan.knowledge.base import FilesystemKnowledgeBase
from ethan.tools.base import BaseTool


def _kb_for(user_id: str) -> FilesystemKnowledgeBase:
    from ethan.core.paths import user_knowledge_dir
    return FilesystemKnowledgeBase(user_knowledge_dir())


class KnowledgeSearchTool(BaseTool):
    fast_path = True  # 常驻：本地个人知识库是高频核心能力，fast 档也要直接可见，
                      # 否则模型看不到它、会被 getnote 等「知识库」字样的 skill 抢走
    name = "knowledge_search"
    description = "搜索本地个人知识库（knowledge base）。用户说「查知识库/找我存过的资料」时用它；对用户已沉淀的主题，先于 web_search 调用。注意：这是 ethan 内置的本地知识库，不是 Get笔记等外部笔记服务。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Max results (default 3)", "default": 3},
        },
        "required": ["query"],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, query: str, limit: int = 3) -> str:
        results = _kb_for(self._user_id).search(query, limit=limit)
        if not results:
            return f"No results found in knowledge base for: {query}"
        lines = []
        for item in results:
            lines.append(f"## {item.title}\n{item.snippet()}\n[source: {item.source}]")
        return "\n\n".join(lines)


class KnowledgeAddTool(BaseTool):
    fast_path = True  # 常驻：与 knowledge_search 成对，「存到知识库」是高频意图
    side_effect = True
    name = "knowledge_add"
    description = "保存笔记/资料到本地个人知识库（knowledge base）。用户说「存到知识库/记到知识库」时用它。注意：这是 ethan 内置的本地知识库，不是 Get笔记等外部笔记服务；只有用户明确点名某个外部笔记服务时才走对应 skill。"
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Title of the note"},
            "content": {"type": "string", "description": "Markdown content to save"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"},
        },
        "required": ["title", "content"],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, title: str, content: str, tags: list[str] | None = None) -> str:
        path = _kb_for(self._user_id).add(title, content, tags=tags)
        return f"Saved to knowledge base: {path}"
