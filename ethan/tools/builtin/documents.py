"""文档库工具 —— 让 Agent 把产出的文档写进统一目录并交付。

为什么需要它：file_write 可以写任意路径，Agent 习惯往 /tmp 丢，导致产出被系统清理
（实测 57 个交付文件仅 1 个存活）。本工具把「写入文档库 + 交付到聊天」合并成一步，
路径由文档库根目录决定，Agent 只需给出分类子路径。

配套约束（见 system_prompt）：产出的文档优先走本工具，而不是 file_write + deliver_file。
"""
from __future__ import annotations

from ethan.core.services.file_jail import build_file_card
from ethan.documents.library import ensure_root, relative_to_root, resolve_in_root
from ethan.tools.base import BaseTool, ToolResult


class DocSaveTool(BaseTool):
    fast_path = False
    cacheable = False
    # 写文件 = 有副作用，与 file_write 同款：三方渠道非主人会话会被 ChannelGuardProvider
    # 直接拒绝，不让非主人往主人的文档库里塞东西。
    side_effect = True
    # content 含文档绝对路径，模型后续要用 file_read 逐字读取，不能被压缩改写
    no_compress = True
    name = "doc_save"
    description = (
        "Save a document (markdown/txt/html/csv) into the user's document library and deliver it "
        "to the chat as a file card. Use this INSTEAD OF file_write for any document meant for the "
        "user to keep — documents written here persist in ~/.ethan/documents/ and appear in the "
        "Documents page. Specify a category subpath so the library stays organized, e.g. "
        "'work/coze/每日MR/2026-09-28-mr动态.md'. Parent directories are created automatically."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Path RELATIVE to the document library root, e.g. "
                    "'work/coze/每日MR/2026-09-28-mr动态.md'. Choose a sensible category "
                    "directory by topic; do not include a leading slash."
                ),
            },
            "content": {
                "type": "string",
                "description": "Full document content.",
            },
            "title": {
                "type": "string",
                "description": "Optional human-readable title shown on the file card.",
            },
            "session_id": {
                "type": "string",
                "description": "Optional session id to link this document to its source conversation.",
            },
        },
        "required": ["path", "content"],
    }

    async def run(self, path: str, content: str, title: str = "", session_id: str = "") -> str | ToolResult:
        ensure_root()
        target = resolve_in_root(path)
        if target is None:
            return f"Save failed: invalid document path: {path}"
        if target.suffix.lower() not in {".md", ".markdown", ".txt", ".html", ".htm", ".csv"}:
            return (
                "Save failed: doc_save only handles text documents "
                "(.md/.markdown/.txt/.html/.htm/.csv). Use file_write + deliver_file for other types."
            )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as e:
            return f"Save failed: {e}"

        rel = relative_to_root(target)
        # 记录来源对话，供文档页「定位到对话」按钮跳转
        if session_id:
            from ethan.documents.library import Library
            Library().update(rel, session_id=session_id)

        card = build_file_card(str(target), title)
        if card is None:
            return f"Document saved to {target}, but could not build a file card."

        return ToolResult(
            tool_call_id="",
            content=(
                f"已保存文档：{card['title']}（{rel}，{card['size_kb']} KB）\n"
                f"文件路径：{target}\n"
                f"文档已存入文档库，用户可在「文档」页查看；如需引用内容，用 file_read 读取 {target}。"
            ),
            cards=[card],
        )


class DocListTool(BaseTool):
    fast_path = False
    cacheable = False
    # 返回结构化清单（路径要逐字回传给 doc_save/file_read），压缩会破坏可用性
    no_compress = True
    name = "doc_list"
    description = (
        "List documents in the user's document library, optionally filtered by a category prefix. "
        "Use this to find existing documents before updating them, or to answer questions about "
        "what documents the user has."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prefix": {
                "type": "string",
                "description": "Optional category prefix to filter by, e.g. 'work/coze'. Empty lists all.",
            },
            "limit": {
                "type": "integer",
                "description": "Max entries to return (default 50).",
            },
        },
        "required": [],
    }

    async def run(self, prefix: str = "", limit: int = 50) -> str:
        ensure_root()
        from ethan.documents.library import list_flat

        items = list_flat()
        if prefix:
            p = prefix.strip("/")
            items = [i for i in items if i.path.startswith(p + "/") or i.path == p]
        items = items[: max(1, limit)]
        if not items:
            return "文档库为空" + (f"（前缀 {prefix} 下没有文档）" if prefix else "") + "。"

        lines = [f"文档库共 {len(items)} 个文档" + (f"（前缀 {prefix}）" if prefix else "") + "："]
        for i in items:
            flag = "📌" if i.meta.pinned else ("⭐" if i.meta.favorite else "  ")
            lines.append(f"{flag} {i.path}  ({i.size_kb} KB)")
        return "\n".join(lines)
