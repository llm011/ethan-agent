"""File Tool — 读取和写入本地文件。"""
import os
from pathlib import Path

from ethan.tools.base import BaseTool


class FileReadTool(BaseTool):
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
