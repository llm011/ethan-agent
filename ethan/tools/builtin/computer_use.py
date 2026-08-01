"""Computer Use Tool — 通过 cua-driver 控制本机 macOS 桌面。

两种模式（自动切换，不设 CUA_BRIDGE_HOST 时走模式 1，不影响宿主机直跑）：

模式 1 — SDK 直连（宿主机原生跑 ethan）:
    依赖 cua-computer 包（pyproject.toml 可选 extra `computer`）+ cua-driver serve。
    Computer(use_host_computer_server=True) → 本机 UDS。

模式 2 — Bridge 模式（Docker 容器跑 ethan）:
    宿主机跑 cua-bridge（TCP→UDS 桥），容器内设置 CUA_BRIDGE_HOST 即激活。
    纯 stdlib socket 通信，不需要 cua-computer 包。
    安装 bridge: curl -fsSL https://raw.githubusercontent.com/llm011/ethan-agent/main/deploy/cua-bridge/install.sh | bash
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import socket
from typing import Any

from ethan.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


# ── 模式 1: SDK 直连（宿主机原生） ──────────────────────────────────────────

_computer: Any = None
_computer_lock: asyncio.Lock | None = None
_computer_init_failed: bool = False


async def _get_interface():
    """获取 cua Computer 接口（懒连接）。

    ImportError（包未安装）→ 永久标记，不重试。
    连接失败（cua-driver 没起）→ 每次调用都重试，方便用户启动 driver 后立即可用。
    """
    global _computer, _computer_lock, _computer_init_failed

    if _computer_lock is None:
        _computer_lock = asyncio.Lock()

    async with _computer_lock:
        if _computer_init_failed:
            raise RuntimeError(
                "cua-computer 包未安装。请运行：uv add cua-computer"
            )
        if _computer is not None:
            return _computer.interface

        try:
            from computer import Computer  # noqa: PLC0415
        except ImportError:
            _computer_init_failed = True  # 包不存在，永久标记
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
            # 连接失败不永久标记——driver 没起时 _computer 保持 None，
            # 下次调用会重新尝试，用户启动 driver 后无需重启 ethan。
            raise RuntimeError(
                f"无法连接 cua-driver (localhost:8000)：{e}\n"
                "请先安装并启动 cua-driver：\n"
                "  curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh | bash\n"
                "  cua-driver serve"
            ) from e


# ── 模式 2: Bridge 客户端（Docker 容器） ────────────────────────────────────

class _BridgeClient:
    """通过 cua-bridge（TCP）连接宿主机 cua-driver 的客户端。

    纯 stdlib 实现，不需要 cua-computer 包。
    cua-driver 的 UDS 协议是请求-响应模式：客户端发 JSON 后必须半关闭，
    driver 才处理并返回响应。bridge 透明处理这个半关闭。
    """

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        # 缓存当前焦点窗口（screenshot 时自动更新，click/type 等复用）
        self._focus_pid: int | None = None
        self._focus_window: int | None = None

    def _call_sync(self, name: str, arguments: dict | None = None) -> dict:
        """同步 TCP 调用 cua-driver 工具，返回完整 JSON 响应。"""
        req = json.dumps({"method": "call", "name": name, "arguments": arguments or {}})
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(30)  # 截图等操作可能较慢
        try:
            s.connect((self.host, self.port))
            s.sendall(req.encode())
            s.shutdown(socket.SHUT_WR)  # 半关闭：告诉 bridge 请求已发完
            chunks: list[bytes] = []
            while True:
                d = s.recv(65536)
                if not d:
                    break
                chunks.append(d)
            resp = b"".join(chunks).decode()
            return json.loads(resp)
        finally:
            try:
                s.close()
            except OSError:
                pass

    async def call(self, name: str, arguments: dict | None = None) -> dict:
        """异步包装（避免阻塞事件循环）。"""
        return await asyncio.to_thread(self._call_sync, name, arguments)

    async def ensure_focus(self) -> tuple[int, int]:
        """获取/刷新当前焦点窗口的 (pid, window_id)。

        cua-driver 的 click/type 等工具需要 pid 寻址。
        screenshot 时自动调用此方法，后续 click/type 复用缓存的 pid。
        """
        if self._focus_pid is not None and self._focus_window is not None:
            return self._focus_pid, self._focus_window

        r = await self.call("list_windows")
        if not r.get("ok"):
            raise RuntimeError(f"list_windows 失败: {r.get('error', '?')}")

        sc = r.get("result", {}).get("structuredContent", {})
        # 兼容多种可能的返回格式
        windows = sc.get("windows", []) if isinstance(sc, dict) else sc
        if not windows:
            raise RuntimeError("未找到任何窗口，请确认宿主机有可见窗口")

        # 找前台窗口（尝试多种可能的字段名）
        for w in windows:
            if not isinstance(w, dict):
                continue
            if w.get("is_frontmost") or w.get("frontmost") or w.get("focused") or w.get("is_active"):
                self._focus_pid = w.get("pid") or w.get("owner_pid")
                self._focus_window = w.get("window_id") or w.get("id") or w.get("windowID")
                if self._focus_pid is not None:
                    break

        # fallback: 取第一个有 pid 的窗口
        if self._focus_pid is None:
            for w in windows:
                if not isinstance(w, dict):
                    continue
                pid = w.get("pid") or w.get("owner_pid")
                if pid:
                    self._focus_pid = pid
                    self._focus_window = w.get("window_id") or w.get("id") or w.get("windowID")
                    break

        if self._focus_pid is None:
            raise RuntimeError("无法确定前台窗口的 pid")

        return self._focus_pid, self._focus_window or 0

    def invalidate_focus(self) -> None:
        """清除焦点窗口缓存（窗口关闭/切换时调用）。"""
        self._focus_pid = None
        self._focus_window = None


_bridge_client: _BridgeClient | None = None
_bridge_lock = asyncio.Lock()


async def _get_bridge_client() -> _BridgeClient:
    """获取/创建 bridge 客户端单例（首次调用时验证连接）。"""
    global _bridge_client
    if _bridge_client is not None:
        return _bridge_client

    async with _bridge_lock:
        if _bridge_client is not None:
            return _bridge_client

        host = os.environ.get("CUA_BRIDGE_HOST", "")
        port = int(os.environ.get("CUA_BRIDGE_PORT", "8000"))
        client = _BridgeClient(host, port)

        # 验证连接
        r = await client.call("get_screen_size")
        if not r.get("ok"):
            raise RuntimeError(
                f"cua-bridge 连接失败 ({host}:{port}): {r.get('error', '?')}\n"
                "请确认宿主机已安装并启动 cua-bridge：\n"
                "  curl -fsSL https://raw.githubusercontent.com/llm011/ethan-agent/main/deploy/cua-bridge/install.sh | bash"
            )

        _bridge_client = client
        logger.info("[ComputerUse] bridge 已连接 %s:%s", host, port)
        return _bridge_client


def _bridge_enabled() -> bool:
    """是否激活 bridge 模式。"""
    return bool(os.environ.get("CUA_BRIDGE_HOST"))


# ── 工具类 ───────────────────────────────────────────────────────────────────

class ComputerUseTool(BaseTool):
    """通过 cua-driver 控制本机桌面的截图/鼠标/键盘操作。

    自动检测运行模式：
    - 设置了 CUA_BRIDGE_HOST 环境变量 → bridge 模式（Docker 容器）
    - 否则 → SDK 直连模式（宿主机原生）
    """

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
        # 自动分发：bridge 模式 vs SDK 直连
        if _bridge_enabled():
            return await self._run_via_bridge(
                action, x=x, y=y, end_x=end_x, end_y=end_y,
                text=text, key=key, keys=keys, direction=direction,
                clicks=clicks, target=target,
            )
        return await self._run_via_sdk(
            action, x=x, y=y, end_x=end_x, end_y=end_y,
            text=text, key=key, keys=keys, direction=direction,
            clicks=clicks, target=target,
        )

    # ── 模式 1: SDK 直连（原有逻辑，不变） ──────────────────────────────

    async def _run_via_sdk(
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
                await iface.move_cursor(x, y)
                if direction == "up":
                    await iface.scroll_up(clicks)
                elif direction == "down":
                    await iface.scroll_down(clicks)
                else:
                    # left/right 不被 cua GenericInterface 原生支持，退化为通知
                    return ToolResult(
                        tool_call_id="",
                        content=f"Horizontal scroll ({direction}) is not supported by cua-driver. Use keyboard shortcuts instead (e.g. shift+scroll).",
                        is_error=True,
                    )
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

    # ── 模式 2: Bridge（Docker 容器 → cua-bridge → cua-driver UDS） ──────

    async def _run_via_bridge(
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
            client = await _get_bridge_client()
        except RuntimeError as e:
            return ToolResult(tool_call_id="", content=str(e), is_error=True)

        try:
            if action == "screenshot":
                pid, wid = await client.ensure_focus()
                r = await client.call("get_window_state", {
                    "pid": pid,
                    "window_id": wid,
                    "capture_mode": "vision",  # 只截图，不 walk AX 树
                })
                if not r.get("ok"):
                    # 窗口可能已关闭，清除缓存重试一次
                    client.invalidate_focus()
                    pid, wid = await client.ensure_focus()
                    r = await client.call("get_window_state", {
                        "pid": pid,
                        "window_id": wid,
                        "capture_mode": "vision",
                    })
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"截图失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                sc = r.get("result", {}).get("structuredContent", {})
                b64 = sc.get("screenshot_png_b64", "")
                if not b64:
                    return ToolResult(
                        tool_call_id="",
                        content="截图返回为空，请确认 cua-driver 有屏幕录制权限",
                        is_error=True,
                    )
                media_type = sc.get("screenshot_mime_type", "image/png")
                return ToolResult(
                    tool_call_id="",
                    content="Screenshot taken.",
                    images=[{"data": b64, "media_type": media_type}],
                )

            elif action == "get_screen_size":
                r = await client.call("get_screen_size")
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"获取屏幕尺寸失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                sc = r.get("result", {}).get("structuredContent", {})
                return f"Screen size: {sc.get('width', '?')}×{sc.get('height', '?')}"

            elif action in ("click", "double_click", "right_click"):
                if x is None or y is None:
                    return ToolResult(
                        tool_call_id="",
                        content=f"{action} requires x and y",
                        is_error=True,
                    )
                pid, wid = await client.ensure_focus()
                # click 工具支持 button 参数；double_click/right_click 有独立工具
                if action == "click":
                    r = await client.call("click", {
                        "pid": pid, "x": x, "y": y, "button": "left",
                    })
                elif action == "double_click":
                    r = await client.call("double_click", {
                        "pid": pid, "x": x, "y": y,
                    })
                else:  # right_click
                    r = await client.call("right_click", {
                        "pid": pid, "x": x, "y": y,
                    })
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"{action} 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                return f"{action.replace('_', ' ').title()} ({x}, {y})"

            elif action == "move":
                if x is None or y is None:
                    return ToolResult(
                        tool_call_id="",
                        content="move requires x and y",
                        is_error=True,
                    )
                pid, _ = await client.ensure_focus()
                r = await client.call("move_cursor", {"pid": pid, "x": x, "y": y})
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"move 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                return f"Moved cursor to ({x}, {y})"

            elif action == "drag":
                if x is None or y is None or end_x is None or end_y is None:
                    return ToolResult(
                        tool_call_id="",
                        content="drag requires x, y, end_x, end_y",
                        is_error=True,
                    )
                pid, _ = await client.ensure_focus()
                r = await client.call("drag", {
                    "pid": pid,
                    "from_x": x, "from_y": y,
                    "to_x": end_x, "to_y": end_y,
                })
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"drag 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                return f"Dragged from ({x}, {y}) to ({end_x}, {end_y})"

            elif action == "type":
                if not text:
                    return ToolResult(
                        tool_call_id="",
                        content="type requires text",
                        is_error=True,
                    )
                pid, _ = await client.ensure_focus()
                r = await client.call("type_text", {
                    "pid": pid, "text": text,
                })
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"type 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                return f"Typed: {text[:80]}{'…' if len(text) > 80 else ''}"

            elif action == "press":
                if not key:
                    return ToolResult(
                        tool_call_id="",
                        content="press requires key",
                        is_error=True,
                    )
                pid, _ = await client.ensure_focus()
                r = await client.call("press_key", {
                    "pid": pid, "key": key,
                })
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"press 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                return f"Pressed key: {key}"

            elif action == "hotkey":
                if not keys:
                    return ToolResult(
                        tool_call_id="",
                        content="hotkey requires keys array",
                        is_error=True,
                    )
                pid, _ = await client.ensure_focus()
                r = await client.call("hotkey", {
                    "pid": pid, "keys": keys,
                })
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"hotkey 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                return f"Hotkey: {'+'.join(keys)}"

            elif action == "scroll":
                if x is None or y is None:
                    return ToolResult(
                        tool_call_id="",
                        content="scroll requires x and y",
                        is_error=True,
                    )
                if direction in ("left", "right"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"Horizontal scroll ({direction}) is not supported. Use keyboard shortcuts instead.",
                        is_error=True,
                    )
                pid, _ = await client.ensure_focus()
                # 先移动光标到目标位置
                await client.call("move_cursor", {"pid": pid, "x": x, "y": y})
                r = await client.call("scroll", {
                    "pid": pid,
                    "direction": direction,
                    "amount": clicks,
                })
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"scroll 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                return f"Scrolled {direction} {clicks} clicks at ({x}, {y})"

            elif action == "launch":
                if not target:
                    return ToolResult(
                        tool_call_id="",
                        content="launch requires target (app name)",
                        is_error=True,
                    )
                r = await client.call("launch_app", {"name": target})
                if not r.get("ok"):
                    # 清除焦点缓存，新 app 可能成为前台
                    client.invalidate_focus()
                    return ToolResult(
                        tool_call_id="",
                        content=f"launch 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                # 新 app 启动后清除焦点缓存，下次 screenshot 会重新获取
                client.invalidate_focus()
                return f"Launched: {target}"

            elif action == "open":
                if not target:
                    return ToolResult(
                        tool_call_id="",
                        content="open requires target (URL or path)",
                        is_error=True,
                    )
                # cua-driver 没有 open 工具，用 launch_app 启动默认浏览器 + type URL
                # 先尝试启动 Safari（macOS 默认浏览器）
                r = await client.call("launch_app", {"name": "Safari"})
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"无法启动浏览器来打开 {target}: {r.get('error', '?')}",
                        is_error=True,
                    )
                client.invalidate_focus()
                # 等待浏览器启动
                await asyncio.sleep(1)
                # 聚焦地址栏并输入 URL
                pid, _ = await client.ensure_focus()
                await client.call("hotkey", {"pid": pid, "keys": ["cmd", "l"]})
                await asyncio.sleep(0.3)
                await client.call("type_text", {"pid": pid, "text": target})
                await asyncio.sleep(0.2)
                await client.call("press_key", {"pid": pid, "key": "return"})
                return f"Opened: {target}"

            else:
                return ToolResult(
                    tool_call_id="",
                    content=f"Unknown action: {action}",
                    is_error=True,
                )

        except Exception as e:
            logger.exception("[ComputerUse/bridge] action=%s failed", action)
            return ToolResult(
                tool_call_id="",
                content=f"Action '{action}' failed: {e}",
                is_error=True,
            )
