"""Deliver File Tool — 把本地生成的文件（pptx/pdf 等）以「文件卡片」形式交付到聊天消息。

典型场景：ppt-generate skill 渲染出 pptx 后调用本工具，前端在消息里渲染
icon + 文件名的卡片，点击进入 /ppt-preview 预览页或直接下载。

卡片数据（cards=[{"type": "file", ...}]）经 ToolResult → SSE → 前端 CardRenderer，
全链路与 web_search 的 search_result 卡片一致。
"""
from __future__ import annotations

from pathlib import Path

from ethan.tools.base import BaseTool, ToolResult

# 允许交付的扩展名（按需扩充）
_ALLOWED_EXTS = {".pptx", ".pdf", ".docx", ".xlsx", ".csv", ".zip", ".md", ".html"}


def _resolve_jailed(path: str) -> Path | None:
    """解析路径并做 jail 校验：只允许 home 目录和 /tmp 下的文件。"""
    try:
        p = Path(path).expanduser().resolve()
    except Exception:
        return None
    home = Path.home().resolve()
    tmp = Path("/tmp").resolve()  # macOS 上 /tmp 是 /private/tmp 的软链，resolve 后再比
    if not (p.is_relative_to(home) or p.is_relative_to(tmp)):
        return None
    return p


def _detect_project(file_path: Path) -> tuple[str | None, int | None]:
    """pptx 同目录若存在 deck.json + pages/（项目制 deck），返回项目目录与页数。"""
    if file_path.suffix.lower() != ".pptx":
        return None, None
    project_dir = file_path.parent
    if not (project_dir / "deck.json").is_file():
        return None, None
    pages_dir = project_dir / "pages"
    if not pages_dir.is_dir():
        return None, None
    page_count = len(list(pages_dir.glob("*.json")))
    return (str(project_dir), page_count) if page_count else (None, None)


class DeliverFileTool(BaseTool):
    fast_path = False
    name = "deliver_file"
    description = (
        "Deliver a locally generated file (pptx/pdf/docx/xlsx/csv/zip/md/html) to the chat "
        "as a clickable file card with preview/download entry. Call this AFTER the file has "
        "been fully written to disk. The path must be absolute and under the user home or /tmp."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path of the file to deliver, e.g. /Users/x/Downloads/报告/报告.pptx",
            },
            "title": {
                "type": "string",
                "description": "Optional human-readable title shown on the card (defaults to filename).",
            },
        },
        "required": ["path"],
    }

    async def run(self, path: str, title: str = "") -> str | ToolResult:
        p = _resolve_jailed(path)
        if p is None:
            return f"Deliver failed: path must be under the user home directory or /tmp: {path}"
        if not p.is_file():
            return f"Deliver failed: file not found: {p}"
        if p.suffix.lower() not in _ALLOWED_EXTS:
            return f"Deliver failed: unsupported file type {p.suffix} (allowed: {', '.join(sorted(_ALLOWED_EXTS))})"

        project_dir, page_count = _detect_project(p)
        card = {
            "type": "file",
            "filename": p.name,
            "title": title or p.stem,
            "path": str(p),
            "size_kb": round(p.stat().st_size / 1024, 1),
            "kind": p.suffix.lower().lstrip("."),
        }
        if project_dir:
            card["project_dir"] = project_dir
            card["page_count"] = page_count

        return ToolResult(
            tool_call_id="",  # 由 registry 回填
            content=f"已交付文件 {p.name}（{card['size_kb']} KB），用户可点击卡片预览或下载。",
            cards=[card],
        )
