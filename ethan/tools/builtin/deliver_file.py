"""Deliver File Tool — 把本地生成的文件（pptx/pdf 等）以「文件卡片」形式交付到聊天消息。

典型场景：ppt-generate skill 渲染出 pptx 后调用本工具，前端在消息里渲染
icon + 文件名的卡片，点击进入 /ppt-preview 预览页或直接下载。

卡片数据（cards=[{"type": "file", ...}]）经 ToolResult → SSE → 前端 CardRenderer，
全链路与 web_search 的 search_result 卡片一致。
"""
from __future__ import annotations

from ethan.core.file_jail import DELIVER_EXTS, build_file_card, resolve_jailed
from ethan.tools.base import BaseTool, ToolResult


class DeliverFileTool(BaseTool):
    fast_path = False
    cacheable = False  # 同路径重复交付时文件内容已变，且缓存命中路径会丢 cards 载荷
    name = "deliver_file"
    description = (
        "Deliver a locally generated file (pptx/pdf/docx/xlsx/csv/zip/md/html/mp4) to the chat "
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
        # 先做细分校验以给出可操作的报错（build_file_card 只返回 None 不区分原因）
        p = resolve_jailed(path)
        if p is None:
            return f"Deliver failed: path must be under the user home directory or /tmp: {path}"
        if not p.is_file():
            return f"Deliver failed: file not found: {p}"
        if p.suffix.lower() not in DELIVER_EXTS:
            return f"Deliver failed: unsupported file type {p.suffix} (allowed: {', '.join(sorted(DELIVER_EXTS))})"

        # 卡片构造收敛在 file_jail.build_file_card，与正文兜底扫描共用，避免字段漂移
        card = build_file_card(str(p), title)
        if card is None:
            return f"Deliver failed: cannot build file card for {p}"

        # 注意：content 中必须包含完整绝对路径，让历史上下文追踪机制能提取到，
        # 后续轮次模型可以直接用 file_read 读取该文件，无需重新生成。
        return ToolResult(
            tool_call_id="",  # 由 registry 回填
            content=(
                f"已交付文件：{card['title']}（{p.name}，{card['size_kb']} KB）\n"
                f"文件路径：{p}\n"
                f"用户可点击卡片预览或下载；如需引用文件内容，用 file_read 读取 {p}。"
            ),
            cards=[card],
        )
