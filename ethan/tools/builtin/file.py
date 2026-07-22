"""File Tool — 读取和写入本地文件。"""
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


def _is_safe_path(path: str) -> bool:
    """是否落在「默认豁免」目录内（写入无需授权）：系统临时目录 /tmp 等。
    安全起见：密钥目录永不豁免。"""
    if _is_inside_secrets(path):
        return False
    try:
        import tempfile
        p = Path(path).expanduser().resolve()
        safe_roots = [Path("/tmp").resolve(), Path(tempfile.gettempdir()).resolve()]
        return any(root == p or root in p.parents for root in safe_roots)
    except Exception:
        return False


def _dir_scope(path: str) -> str:
    """授权记忆作用域 = 文件所在目录的绝对路径（授权该目录后，子目录/同目录文件免问）。"""
    try:
        return str(Path(path).expanduser().resolve().parent)
    except Exception:
        return path


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
            "offset": {
                "type": "integer",
                "description": "Start reading from this line number (1-based). Use for paginated reading of large files.",
                "default": 0,
            },
            "max_lines": {
                "type": "integer",
                "description": "Maximum lines to read (default: all). Combined with offset for pagination.",
                "default": 0,
            },
        },
        "required": ["path"],
    }

    def consent_check(self, path: str = "", **kwargs) -> str | None:
        if _is_inside_secrets(str(path)):
            # .secrets 目录硬拦截在 run() 中，这里无需弹授权
            return None
        return None

    def consent_scope(self, path: str = "", **kwargs) -> str:
        # 密钥文件按单文件授权（每个 secret 单独问一次），不做目录级放行
        try:
            return str(Path(path).expanduser().resolve())
        except Exception:
            return path or self.name

    async def run(self, path: str, max_lines: int = 0, offset: int = 0) -> str:
        p = Path(path).expanduser().resolve()
        if _is_inside_secrets(str(p)):
            return (
                "Error: 禁止读取 .secrets 目录下的文件。"
                "密钥只能通过 list_secrets / get_secret 工具访问。"
                "如果密钥不存在，请提示用户用 set_secret 配置。"
            )
        if not p.exists():
            return f"File not found: {p}"
        if not p.is_file():
            return f"Not a file: {p}"
        if p.stat().st_size > 1_000_000 and max_lines == 0:
            return f"File too large ({p.stat().st_size} bytes). Use offset + max_lines to read partially."

        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"Read error: {e}"

        lines = text.splitlines()
        start = max(offset - 1, 0) if offset > 0 else 0
        if max_lines > 0:
            lines = lines[start:start + max_lines]
        elif start > 0:
            lines = lines[start:]
        text = "\n".join(lines)

        # 不截断，file_read 有 no_compress=True，原样进 context
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
        # 写文件有副作用，执行前请求授权。/tmp 等临时目录默认豁免（无需授权）。
        # 同一会话内授权过该目录后，其子目录/同目录文件不再弹（见 consent_scope + is_granted）。
        if _is_safe_path(str(path)):
            return None
        # 文案显式告知 scope 是目录级，避免用户以为只授了单个文件
        scope = _dir_scope(str(path))
        return f"写入文件 {path}（授权后本会话对 {scope} 目录及其子目录的写入都不再询问）"

    def consent_scope(self, path: str = "", **kwargs) -> str:
        # 目录级授权：授权某目录后，该目录及子目录内的写入都免问
        return _dir_scope(str(path))

    async def run(self, path: str, content: str, append: bool = False) -> str:
        p = Path(path).expanduser().resolve()
        if _is_inside_secrets(str(p)):
            return (
                "Error: 禁止写入 .secrets 目录下的文件。"
                "密钥只能通过 set_secret 工具 / ethan secret 命令管理。"
            )
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
        if _is_inside_secrets(str(p)):
            return (
                "Error: 禁止列出 .secrets 目录。"
                "密钥只能通过 list_secrets / get_secret 工具访问。"
                "如果密钥不存在，请提示用户用 set_secret 配置。"
            )
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
