"""知识库工具 — 让 agent 能查询和添加知识库内容。"""
from ethan.knowledge.base import KnowledgeBase
from ethan.tools.base import BaseTool


def _kb_for(user_id: str) -> KnowledgeBase:
    from ethan.knowledge.registry import get_knowledge_backend
    return get_knowledge_backend(user_id)


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


class KnowledgeReadTool(BaseTool):
    fast_path = True  # 与 search 成对：search 找到条目后常要读全文，fast 档也得直接可见
    name = "knowledge_read"
    description = (
        "读取本地个人知识库中某一条的完整内容（标题/标签/正文全文）。"
        "knowledge_search 只返回摘要列表，需要看某条的完整正文（或编辑前先读全文）时用它。"
        "source 用 knowledge_search 结果里的 source（文件路径）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "条目的 source（knowledge_search 返回的文件路径）"},
        },
        "required": ["source"],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, source: str) -> str:
        item = _kb_for(self._user_id).get(source)
        if item is None:
            return f"知识库中找不到该条目：{source}"
        tag_line = f"\ntags: {', '.join(item.tags)}" if item.tags else ""
        return f"# {item.title}{tag_line}\n[source: {item.source}]\n\n{item.content}"


class KnowledgeEditTool(BaseTool):
    fast_path = True  # 与 add/search 成对：「补充/修改知识库某条」是高频意图
    side_effect = True
    name = "knowledge_edit"
    description = (
        "编辑本地个人知识库中已有的一条（追加或整篇替换），而不是新建。"
        "用户说「在那条笔记/知识里再加一点、补充、改一下」时用它，避免每次都新建文档。\n"
        "- mode=append（默认）：把 content 追加到原正文末尾，保留原标题/标签。适合「再记一条」。\n"
        "- mode=replace：整篇替换正文（title/tags 不传则沿用原值）。适合修订。\n"
        "source 用 knowledge_search 的结果路径；不确定原文时先 knowledge_read 看全文再改。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "要编辑条目的 source（文件路径）"},
            "content": {"type": "string", "description": "追加或替换的 Markdown 内容"},
            "mode": {"type": "string", "enum": ["append", "replace"], "description": "append 追加（默认）/ replace 整篇替换", "default": "append"},
            "title": {"type": "string", "description": "仅 replace 时可选：新标题，不传沿用原标题"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "仅 replace 时可选：新标签，不传沿用原标签"},
        },
        "required": ["source", "content"],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, source: str, content: str, mode: str = "append",
                  title: str | None = None, tags: list[str] | None = None) -> str:
        kb = _kb_for(self._user_id)
        item = kb.get(source)
        if item is None:
            return f"知识库中找不到该条目：{source}"
        if mode == "replace":
            kb.update(item.source, title or item.title, content,
                      tags=tags if tags is not None else item.tags)
            return f"已替换知识库条目正文：{item.source}"
        kb.append(item.source, content)
        return f"已追加到知识库条目：{item.source}"
