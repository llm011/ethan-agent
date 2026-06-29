"""File Tool — 读取和写入本地文件。"""
import os
from pathlib import Path

from ethan.tools.base import BaseTool


def _is_inside_secrets(path: str) -> bool:
    """路径是否落在 ~/.ethan/.secrets/ 目录内。"""
    try:
        from ethan.core.config import CONFIG_DIR
        secrets_dir = (CONFIG_DIR / ".secrets").resolve()
        p = Path(path).expanduser().resolve()
        return secrets_dir in p.parents or p == secrets_dir
    except Exception:
        return ".secrets" in Path(path).parts


class FileReadTool(BaseTool):
    no_compress = True  # 文件原文必须逐字给模型，绝不压成摘要（否则模型反复重读拿不到真内容）
    name = "file_read"
    description = "Read the contents of a local file. Use when you need to see what's in a file."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative file path.",
            },
            "max_lines": {
                "type": "integer",
                "description": "Maximum lines to read (default: all).",
                "default": 0,
            },
        },
        "required": ["path"],
    }

    def consent_check(self, path: str = "", **kwargs) -> str | None:
        if _is_inside_secrets(str(path)):
            return f"读取密钥文件 {path}（密钥请改用 get_secret 工具）"
        return None

    async def run(self, path: str, max_lines: int = 0) -> str:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"File not found: {p}"
        if not p.is_file():
            return f"Not a file: {p}"
        if p.stat().st_size > 1_000_000:
            return f"File too large ({p.stat().st_size} bytes). Use max_lines to read partially."

        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"Read error: {e}"

        if max_lines > 0:
            lines = text.splitlines()[:max_lines]
            text = "\n".join(lines)
            if len(text) > 8000:
                text = text[:8000] + "\n...(truncated)"

        if len(text) > 8000:
            text = text[:8000] + "\n...(truncated)"

        return text or "(empty file)"


class FileWriteTool(BaseTool):
    fast_path = True  # fast 档也需要写文件（沉淀经验/改技能等），否则模型只能用 terminal python 硬写，绕路又危险
    side_effect = True
    name = "file_write"
    description = "Write content to a local file. Creates parent directories if needed."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or relative file path.",
            },
            "content": {
                "type": "string",
                "description": "Content to write.",
            },
            "append": {
                "type": "boolean",
                "description": "Append to file instead of overwriting (default: false).",
                "default": False,
            },
        },
        "required": ["path", "content"],
    }

    def consent_check(self, path: str = "", **kwargs) -> str | None:
        # 写文件有副作用，执行前请求授权（同一会话授权过不再弹，见 consent 的 session 记忆）
        return f"写入文件 {path}"

    async def run(self, path: str, content: str, append: bool = False) -> str:
        p = Path(path).expanduser().resolve()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            p.write_text(content, encoding="utf-8") if not append else p.open(mode).write(content)
            return f"Written to {p} ({len(content)} chars)"
        except Exception as e:
            return f"Write error: {e}"


class FileListTool(BaseTool):
    fast_path = False
    name = "file_list"
    description = "List files and directories at a given path."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path (default: current directory).",
                "default": ".",
            },
        },
        "required": [],
    }

    async def run(self, path: str = ".") -> str:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"Path not found: {p}"
        if not p.is_dir():
            return f"Not a directory: {p}"

        entries = []
        try:
            for item in sorted(p.iterdir()):
                prefix = "📁 " if item.is_dir() else "📄 "
                entries.append(f"{prefix}{item.name}")
        except PermissionError:
            return f"Permission denied: {p}"

        if not entries:
            return "(empty directory)"
        return "\n".join(entries[:100])
