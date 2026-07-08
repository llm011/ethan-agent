"""Computer Use Tool — 通过 cua-computer SDK 控制本机桌面。

依赖 cua-computer 包（已在 pyproject.toml 的可选依赖中）和 cua-driver 后台服务：

安装 cua-driver（macOS）:
    curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh | bash
    cua-driver serve   # 或注册为 launchd 服务：cua-driver install

cua-driver 默认监听 localhost:8000，本工具使用 use_host_computer_server=True 模式连接。
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

from ethan.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# 进程级单例 Computer 实例（懒初始化，首次调用时连接 cua-driver）
_computer: Any = None
_computer_lock: asyncio.Lock | None = None
_computer_init_failed: bool = False


async def _get_interface():
    """获取 cua Computer 接口（懒连接，失败后不重试）。"""
    global _computer, _computer_lock, _computer_init_failed

    if _computer_lock is None:
        _computer_lock = asyncio.Lock()

    async with _computer_lock:
        if _computer_init_failed:
            raise RuntimeError(
                "cua-driver 连接失败。请先安装并启动 cua-driver：\n"
                "  curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh | bash\n"
                "  cua-driver serve"
            )
        if _computer is not None:
            return _computer.interface

        try:
            from computer import Computer  # noqa: PLC0415
        except ImportError:
            _computer_init_failed = True
            raise RuntimeError(
                "cua-computer 包未安装。请运行：uv add cua-computer"
            )

        try:
            c = Computer(use_host_computer_server=True, api_port=8000, verbosity=0, telemetry_enabled=False)
            await c.run()
            _computer = c
            logger.info("[ComputerUse] 已连接 cua-driver (localhost:8000)")
            return _computer.interface
        except Exception as e:
            _computer_init_failed = True
            raise RuntimeError(f"无法连接 cua-driver (localhost:8000)：{e}") from e


class ComputerUseTool(BaseTool):
    """通过 cua SDK 控制本机桌面的截图/鼠标/键盘操作。"""

    name = "computer_use"
    cacheable = False
    side_effect = True
    no_compress = True   # 截图是图片数据，不能走文字摘要
    fast_path = False    # 按需激活

    description = (
        "Control the local macOS desktop: take screenshots, click, type, scroll, "
        "open URLs/apps, and more. Always screenshot first to see the current state. "
        "Coordinates are in pixels (origin top-left)."
    )

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "Action to perform. One of: screenshot, click, double_click, "
                    "right_click, move, drag, type, press, hotkey, scroll, "
                    "open, launch, get_screen_size."
                ),
                "enum": [
                    "screenshot", "click", "double_click", "right_click",
                    "move", "drag", "type", "press", "hotkey", "scroll",
                    "open", "launch", "get_screen_size",
                ],
            },
            "x": {"type": "integer", "description": "X coordinate (for click/move/drag)"},
            "y": {"type": "integer", "description": "Y coordinate (for click/move/drag)"},
            "end_x": {"type": "integer", "description": "End X coordinate (drag only)"},
            "end_y": {"type": "integer", "description": "End Y coordinate (drag only)"},
            "text": {"type": "string", "description": "Text to type (type action)"},
            "key": {"type": "string", "description": "Key to press, e.g. 'Return', 'Escape', 'cmd+c'"},
            "keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keys for hotkey, e.g. ['cmd', 'c']",
            },
            "direction": {
                "type": "string",
                "enum": ["up", "down", "left", "right"],
                "description": "Scroll direction",
            },
            "clicks": {"type": "integer", "description": "Number of scroll clicks (default 3)"},
            "target": {"type": "string", "description": "URL or file path to open, or app name to launch"},
        },
        "required": ["action"],
    }

    async def run(  # type: ignore[override]
        self,
        action: str,
        x: int | None = None,
        y: int | None = None,
        end_x: int | None = None,
        end_y: int | None = None,
        text: str | None = None,
        key: str | None = None,
        keys: list[str] | None = None,
        direction: str = "down",
        clicks: int = 3,
        target: str | None = None,
    ) -> str | ToolResult:
        try:
            iface = await _get_interface()
        except RuntimeError as e:
            return ToolResult(tool_call_id="", content=str(e), is_error=True)

        try:
            if action == "screenshot":
                raw = await iface.screenshot()
                if isinstance(raw, bytes):
                    b64 = base64.b64encode(raw).decode()
                    media_type = "image/png"
                else:
                    # 有时返回 base64 字符串
                    b64 = raw
                    media_type = "image/png"
                return ToolResult(
                    tool_call_id="",
                    content="Screenshot taken.",
                    images=[{"data": b64, "media_type": media_type}],
                )

            elif action == "get_screen_size":
                size = await iface.get_screen_size()
                return f"Screen size: {size.get('width', '?')}×{size.get('height', '?')}"

            elif action == "click":
                if x is None or y is None:
                    return ToolResult(tool_call_id="", content="click requires x and y", is_error=True)
                await iface.left_click(x, y)
                return f"Clicked ({x}, {y})"

            elif action == "double_click":
                if x is None or y is None:
                    return ToolResult(tool_call_id="", content="double_click requires x and y", is_error=True)
                await iface.double_click(x, y)
                return f"Double-clicked ({x}, {y})"

            elif action == "right_click":
                if x is None or y is None:
                    return ToolResult(tool_call_id="", content="right_click requires x and y", is_error=True)
                await iface.right_click(x, y)
                return f"Right-clicked ({x}, {y})"

            elif action == "move":
                if x is None or y is None:
                    return ToolResult(tool_call_id="", content="move requires x and y", is_error=True)
                await iface.move_cursor(x, y)
                return f"Moved cursor to ({x}, {y})"

            elif action == "drag":
                if x is None or y is None or end_x is None or end_y is None:
                    return ToolResult(tool_call_id="", content="drag requires x, y, end_x, end_y", is_error=True)
                await iface.drag_to(x, y, end_x, end_y)
                return f"Dragged from ({x}, {y}) to ({end_x}, {end_y})"

            elif action == "type":
                if not text:
                    return ToolResult(tool_call_id="", content="type requires text", is_error=True)
                await iface.type_text(text)
                return f"Typed: {text[:80]}{'…' if len(text) > 80 else ''}"

            elif action == "press":
                if not key:
                    return ToolResult(tool_call_id="", content="press requires key", is_error=True)
                await iface.press(key)
                return f"Pressed key: {key}"

            elif action == "hotkey":
                if not keys:
                    return ToolResult(tool_call_id="", content="hotkey requires keys array", is_error=True)
                await iface.hotkey(*keys)
                return f"Hotkey: {'+'.join(keys)}"

            elif action == "scroll":
                if x is None or y is None:
                    return ToolResult(tool_call_id="", content="scroll requires x and y", is_error=True)
                if direction == "up":
                    await iface.scroll_up(clicks)
                elif direction == "down":
                    await iface.scroll_down(clicks)
                else:
                    await iface.scroll(x, y)
                return f"Scrolled {direction} {clicks} clicks at ({x}, {y})"

            elif action == "open":
                if not target:
                    return ToolResult(tool_call_id="", content="open requires target (URL or path)", is_error=True)
                await iface.open(target)
                return f"Opened: {target}"

            elif action == "launch":
                if not target:
                    return ToolResult(tool_call_id="", content="launch requires target (app name)", is_error=True)
                await iface.launch(target)
                return f"Launched: {target}"

            else:
                return ToolResult(tool_call_id="", content=f"Unknown action: {action}", is_error=True)

        except Exception as e:
            logger.exception("[ComputerUse] action=%s failed", action)
            return ToolResult(tool_call_id="", content=f"Action '{action}' failed: {e}", is_error=True)
