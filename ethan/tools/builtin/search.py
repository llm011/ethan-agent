"""File search tools — 基于 ripgrep 和 fd 的高性能文件搜索。"""
import asyncio
import shutil
from ethan.tools.base import BaseTool


class RipgrepTool(BaseTool):
    fast_path = False
    name = "rg_search"
    description = (
        "Search file contents with ripgrep (rg). Extremely fast, respects .gitignore. "
        "Use for: finding code patterns, searching text across files. "
        "Returns matching lines with file path and line number."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Search pattern (supports regex)"},
            "path": {"type": "string", "description": "Directory or file to search in (default: current dir)"},
            "case_sensitive": {"type": "boolean", "description": "Case-sensitive search (default: false)", "default": False},
            "file_type": {"type": "string", "description": "Limit to file type, e.g. 'py', 'js', 'ts' (optional)"},
            "max_results": {"type": "integer", "description": "Maximum number of results (default: 50)", "default": 50},
        },
        "required": ["pattern"],
    }

    async def run(self, pattern: str, path: str = ".", case_sensitive: bool = False,
                  file_type: str = "", max_results: int = 50) -> str:
        rg = shutil.which("rg")
        if not rg:
            return "rg (ripgrep) not found. Install with: brew install ripgrep"

        cmd = [rg, "--line-number", "--no-heading", "--color=never"]
        if not case_sensitive:
            cmd.append("--ignore-case")
        if file_type:
            cmd.extend(["--type", file_type])
        cmd.extend(["--max-count", "5"])  # max 5 matches per file
        cmd.append(pattern)
        cmd.append(path)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            output = stdout.decode(errors="replace").strip()
            if not output:
                return f"No matches found for pattern: {pattern}"
            lines = output.splitlines()
            if len(lines) > max_results:
                lines = lines[:max_results]
                output = "\n".join(lines) + f"\n\n...(truncated, showing {max_results}/{len(lines)} results)"
            else:
                output = "\n".join(lines)
            return output or "No matches found."
        except asyncio.TimeoutError:
            return "Search timed out (>15s)"
        except Exception as e:
            return f"Search error: {e}"


class FdTool(BaseTool):
    fast_path = False
    name = "fd_find"
    description = (
        "Find files and directories with fd (fast find). Respects .gitignore by default. "
        "Use for: locating files by name pattern, listing files of a type. "
        "Faster and friendlier than 'find'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Filename pattern (supports regex and glob)"},
            "path": {"type": "string", "description": "Directory to search in (default: current dir)"},
            "file_type": {"type": "string", "description": "'f' for files, 'd' for dirs, 'l' for symlinks (default: all)"},
            "extension": {"type": "string", "description": "Filter by extension, e.g. 'py', 'ts' (optional)"},
            "max_results": {"type": "integer", "description": "Maximum results (default: 50)", "default": 50},
        },
        "required": ["pattern"],
    }

    async def run(self, pattern: str, path: str = ".", file_type: str = "",
                  extension: str = "", max_results: int = 50) -> str:
        fd = shutil.which("fd")
        if not fd:
            return "fd not found. Install with: brew install fd"

        cmd = [fd, "--color=never"]
        if file_type in ("f", "d", "l"):
            cmd.extend(["--type", file_type])
        if extension:
            cmd.extend(["--extension", extension])
        cmd.extend(["--max-results", str(max_results)])
        cmd.append(pattern)
        cmd.append(path)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            output = stdout.decode(errors="replace").strip()
            if not output:
                return f"No files found matching: {pattern}"
            return output
        except asyncio.TimeoutError:
            return "Search timed out (>15s)"
        except Exception as e:
            return f"Search error: {e}"
