"""Computer Use Tool — 通过 cua-driver 控制本机 macOS 桌面。

两种模式（自动切换）：

模式 1 — SDK 直连（宿主机原生跑 ethan）:
    依赖 cua-computer 包 + cua-driver serve。
    Computer(use_host_computer_server=True) → 本机 UDS。
    支持基础操作：screenshot/click/type/scroll/open/launch 等。
    窗口管理类操作（list_windows/set_focus 等）不支持，需 bridge 模式。

模式 2 — Bridge 模式（Docker 容器跑 ethan）:
    宿主机跑 cua-bridge（TCP→UDS 桥），容器内设置 CUA_BRIDGE_HOST 即激活。
    纯 stdlib socket 通信，不需要 cua-computer 包。
    支持全部操作，包括窗口管理、AX 树、剪贴板等。
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


# ── 图片压缩辅助 ────────────────────────────────────────────────────────────

def _to_webp(png_b64: str) -> tuple[str, str]:
    """PNG base64 → WebP base64（quality=75）。

    Pillow 不可用时回退 PNG。返回 (b64_data, media_type)。
    """
    try:
        from io import BytesIO  # noqa: PLC0415

        from PIL import Image  # noqa: PLC0415
    except ImportError:
        return png_b64, "image/png"

    try:
        png_bytes = base64.b64decode(png_b64)
        img = Image.open(BytesIO(png_bytes))
        buf = BytesIO()
        img.save(buf, format="WEBP", quality=75)
        webp_b64 = base64.b64encode(buf.getvalue()).decode()
        return webp_b64, "image/webp"
    except Exception as e:
        logger.warning("[ComputerUse] WebP 压缩失败，回退 PNG: %s", e)
        return png_b64, "image/png"


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


# ── 模式检测（纯检测，无副作用） ────────────────────────────────────────────

def _bridge_enabled() -> bool:
    """是否激活 bridge 模式（纯检测，无副作用）。"""
    if os.environ.get("CUA_BRIDGE_HOST"):
        return True
    return os.path.exists("/.dockerenv")


def _ensure_docker_bridge_env() -> None:
    """Docker 容器内设置 bridge 环境变量默认值（模块加载时调用一次）。"""
    if os.path.exists("/.dockerenv"):
        os.environ.setdefault("CUA_BRIDGE_HOST", "host.docker.internal")
        os.environ.setdefault("CUA_BRIDGE_PORT", "8000")


_ensure_docker_bridge_env()


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
        # 自动检测的焦点窗口缓存（screenshot 时自动更新，click/type 等复用）
        self._focus_pid: int | None = None
        self._focus_window: int | None = None
        # 通过 set_focus 显式设置的焦点（持久，直到 clear_focus 清除）
        self._explicit_pid: int | None = None
        self._explicit_window: int | None = None

    def _call_sync(self, name: str, arguments: dict | None = None) -> dict:
        """同步 TCP 调用 cua-driver 工具，返回完整 JSON 响应。"""
        req = json.dumps({"method": "call", "name": name, "args": arguments or {}})
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

    def set_focus(self, pid: int, window_id: int | None = None) -> None:
        """显式设置焦点 pid/window（持久，直到 clear_focus 清除）。

        后续所有 ensure_focus() 都返回此 pid，不自动检测。
        """
        self._explicit_pid = pid
        self._explicit_window = window_id

    def clear_focus(self) -> None:
        """清除显式设置的焦点，回到自动检测模式。"""
        self._explicit_pid = None
        self._explicit_window = None

    async def ensure_focus(
        self,
        pid_override: int | None = None,
        window_override: int | None = None,
    ) -> tuple[int, int]:
        """获取焦点窗口的 (pid, window_id)。

        三级优先级：
        1. pid_override / window_override 参数（单次调用临时覆盖）
        2. set_focus() 显式设置的 pid（持久，直到 clear_focus）
        3. 自动检测：list_windows 找 z_index 最高的可见窗口（带缓存）

        cua-driver 的 click/type 等工具需要 pid 寻址。
        screenshot 时自动调用此方法，后续 click/type 复用缓存的 pid。
        """
        # 1. 单次覆盖（最高优先级）
        if pid_override is not None:
            return pid_override, window_override or 0

        # 2. 显式 set_focus（持久）
        if self._explicit_pid is not None:
            return self._explicit_pid, self._explicit_window or 0

        # 3. 自动检测（带缓存）
        if self._focus_pid is not None and self._focus_window is not None:
            return self._focus_pid, self._focus_window

        r = await self.call("list_windows")
        if not r.get("ok"):
            raise RuntimeError(f"list_windows 失败: {r.get('error', '?')}")

        sc = r.get("result", {}).get("structuredContent", {})
        windows = sc.get("windows", []) if isinstance(sc, dict) else sc
        if not windows:
            raise RuntimeError("未找到任何窗口，请确认宿主机有可见窗口")

        # 过滤可见窗口（is_on_screen=true），按 z_index 降序找最前台窗口
        visible = [
            w for w in windows
            if isinstance(w, dict) and w.get("is_on_screen") and w.get("pid")
        ]
        if not visible:
            # fallback: 取第一个有 pid 的窗口
            visible = [w for w in windows if isinstance(w, dict) and w.get("pid")]

        if not visible:
            raise RuntimeError("无法确定前台窗口的 pid")

        visible.sort(key=lambda w: w.get("z_index", 0), reverse=True)
        w = visible[0]
        self._focus_pid = w["pid"]
        self._focus_window = w.get("window_id", 0)

        return self._focus_pid, self._focus_window

    def invalidate_focus(self) -> None:
        """清除自动检测的焦点缓存（保留显式 set_focus pid）。

        窗口关闭/切换时调用——只清缓存，不撤销 set_focus 的持久设置。
        """
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


# ── 工具类 ───────────────────────────────────────────────────────────────────

# Bridge 模式独有动作（SDK 模式不支持）
_SDK_UNSUPPORTED = frozenset({
    "list_windows", "list_apps", "set_focus", "activate_window",
    "hide_app", "minimize_window", "kill_app", "get_cursor_position",
    "set_value", "get_accessibility_tree", "zoom", "check_permissions",
})


class ComputerUseTool(BaseTool):
    """通过 cua-driver 控制本机桌面的截图/鼠标/键盘/窗口操作。

    自动检测运行模式：
    - 设置了 CUA_BRIDGE_HOST 环境变量或 /.dockerenv 存在 → bridge 模式（Docker 容器）
    - 否则 → SDK 直连模式（宿主机原生）
    """

    name = "computer_use"
    cacheable = False
    side_effect = True
    no_compress = True   # 截图是图片数据，不能走文字摘要
    fast_path = False    # 按需激活

    description = (
        "Control the local macOS desktop: take screenshots, click, type, scroll, "
        "open URLs/apps, manage windows, inspect accessibility tree, and more. "
        "Always screenshot first to see the current state. "
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
                    "open, launch, get_screen_size, paste_text, activate_app, "
                    "list_windows, list_apps, set_focus, activate_window, "
                    "hide_app, minimize_window, kill_app, get_cursor_position, "
                    "set_value, get_accessibility_tree, zoom, check_permissions, page."
                ),
                "enum": [
                    "screenshot", "click", "double_click", "right_click",
                    "move", "drag", "type", "press", "hotkey", "scroll",
                    "open", "launch", "get_screen_size", "paste_text",
                    "activate_app", "list_windows", "list_apps", "set_focus",
                    "activate_window", "hide_app", "minimize_window",
                    "kill_app", "get_cursor_position", "set_value",
                    "get_accessibility_tree", "zoom", "check_permissions", "page",
                ],
            },
            "x": {"type": "integer", "description": "X coordinate (for click/move/drag/zoom)"},
            "y": {"type": "integer", "description": "Y coordinate (for click/move/drag/zoom)"},
            "end_x": {"type": "integer", "description": "End X coordinate (drag/zoom only)"},
            "end_y": {"type": "integer", "description": "End Y coordinate (drag/zoom only)"},
            "text": {"type": "string", "description": "Text to type or paste (type/paste_text action)"},
            "key": {"type": "string", "description": "Key to press, e.g. 'Return', 'Escape', 'cmd+c'"},
            "keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keys for hotkey, e.g. ['cmd', 'c']",
            },
            "direction": {
                "type": "string",
                "enum": ["up", "down", "left", "right"],
                "description": "Scroll or page direction",
            },
            "clicks": {"type": "integer", "description": "Number of scroll clicks (default 3)"},
            "target": {
                "type": "string",
                "description": "URL/path/app name for open/launch/activate_app/activate_window",
            },
            "pid": {
                "type": "integer",
                "description": "Target process id. click/type/scroll/screenshot operate on this pid's window without foregrounding.",
            },
            "window_id": {"type": "integer", "description": "Target window id"},
            "title_filter": {
                "type": "string",
                "description": "Case-insensitive substring filter for list_windows/list_apps",
            },
            "visible_only": {
                "type": "boolean",
                "description": "list_windows: only return on-screen windows (default true)",
            },
            "element_token": {
                "type": "string",
                "description": "set_value: target element token from accessibility tree",
            },
            "value": {
                "description": "set_value: value to set (string/number/boolean)",
            },
            "capture_mode": {
                "type": "string",
                "enum": ["vision", "all"],
                "description": "screenshot: 'vision' (screenshot only) or 'all' (screenshot + AX tree)",
            },
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
        pid: int | None = None,
        window_id: int | None = None,
        title_filter: str | None = None,
        visible_only: bool = True,
        element_token: str | None = None,
        value: Any = None,
        capture_mode: str | None = None,
    ) -> str | ToolResult:
        # 自动分发：bridge 模式 vs SDK 直连
        if _bridge_enabled():
            return await self._run_via_bridge(
                action, x=x, y=y, end_x=end_x, end_y=end_y,
                text=text, key=key, keys=keys, direction=direction,
                clicks=clicks, target=target, pid=pid, window_id=window_id,
                title_filter=title_filter, visible_only=visible_only,
                element_token=element_token, value=value, capture_mode=capture_mode,
            )
        return await self._run_via_sdk(
            action, x=x, y=y, end_x=end_x, end_y=end_y,
            text=text, key=key, keys=keys, direction=direction,
            clicks=clicks, target=target, pid=pid, window_id=window_id,
            title_filter=title_filter, visible_only=visible_only,
            element_token=element_token, value=value, capture_mode=capture_mode,
        )

    # ── 模式 1: SDK 直连（宿主机原生） ──────────────────────────────────

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
        pid: int | None = None,
        window_id: int | None = None,
        title_filter: str | None = None,
        visible_only: bool = True,
        element_token: str | None = None,
        value: Any = None,
        capture_mode: str | None = None,
    ) -> str | ToolResult:
        # Bridge 独有动作在 SDK 模式下不可用
        if action in _SDK_UNSUPPORTED:
            return ToolResult(
                tool_call_id="",
                content=f"Action '{action}' is not supported in SDK mode (requires bridge mode)",
                is_error=True,
            )

        try:
            iface = await _get_interface()
        except RuntimeError as e:
            return ToolResult(tool_call_id="", content=str(e), is_error=True)

        try:
            if action == "screenshot":
                raw = await iface.screenshot()
                if isinstance(raw, bytes):
                    b64 = base64.b64encode(raw).decode()
                else:
                    # 有时返回 base64 字符串
                    b64 = raw
                b64, media_type = _to_webp(b64)
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

            elif action == "paste_text":
                if not text:
                    return ToolResult(tool_call_id="", content="paste_text requires text", is_error=True)
                import subprocess  # noqa: PLC0415
                # 备份当前剪贴板
                backup = subprocess.run(
                    ["pbpaste"], capture_output=True, text=True, timeout=3
                ).stdout
                # 写入新文本
                subprocess.run(["pbcopy"], input=text, text=True, timeout=3)
                # 粘贴
                await iface.hotkey("cmd", "v")
                # 等待 Electron 接收事件
                await asyncio.sleep(0.3)
                # 恢复原剪贴板
                subprocess.run(["pbcopy"], input=backup, text=True, timeout=3)
                return f"Pasted text: {text[:80]}{'…' if len(text) > 80 else ''}"

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

            elif action == "page":
                if direction == "up":
                    await iface.press("page_up")
                elif direction == "down":
                    await iface.press("page_down")
                else:
                    return ToolResult(
                        tool_call_id="",
                        content=f"page direction must be 'up' or 'down', got: {direction}",
                        is_error=True,
                    )
                return f"Paged {direction}"

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

            elif action == "activate_app":
                if not target:
                    return ToolResult(tool_call_id="", content="activate_app requires target (app name)", is_error=True)
                import subprocess  # noqa: PLC0415
                subprocess.run(
                    ["osascript", "-e", f'tell application "{target}" to activate'],
                    timeout=5,
                )
                return f"Activated app: {target}"

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
        pid: int | None = None,
        window_id: int | None = None,
        title_filter: str | None = None,
        visible_only: bool = True,
        element_token: str | None = None,
        value: Any = None,
        capture_mode: str | None = None,
    ) -> str | ToolResult:
        try:
            client = await _get_bridge_client()
        except RuntimeError as e:
            return ToolResult(tool_call_id="", content=str(e), is_error=True)

        try:
            if action == "screenshot":
                pid_, wid = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                mode = capture_mode or "vision"
                r = await client.call("get_window_state", {
                    "pid": pid_,
                    "window_id": wid,
                    "capture_mode": mode,
                })
                if not r.get("ok"):
                    # 不重试——重试只会选到同一个窗口，没有意义
                    return ToolResult(
                        tool_call_id="",
                        content=f"截图失败: {r.get('error', '?')}",
                        is_error=True,
                    )

                # 新协议：图片数据在 result.content[] 数组中
                content_list = r.get("result", {}).get("content", [])
                b64 = ""
                text_parts: list[str] = []
                for item in content_list:
                    if isinstance(item, dict):
                        if item.get("type") == "image":
                            b64 = item.get("data", "")
                        elif item.get("type") == "text":
                            text_parts.append(item.get("text", ""))

                # 兼容旧协议：screenshot_png_b64
                if not b64:
                    sc = r.get("result", {}).get("structuredContent", {})
                    b64 = sc.get("screenshot_png_b64", "")

                if not b64:
                    return ToolResult(
                        tool_call_id="",
                        content="截图返回为空，请确认 cua-driver 有屏幕录制权限",
                        is_error=True,
                    )

                b64, media_type = _to_webp(b64)

                content_text = "Screenshot taken."
                if text_parts:
                    content_text += "\n\nAccessibility tree:\n" + "\n".join(text_parts)

                return ToolResult(
                    tool_call_id="",
                    content=content_text,
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
                pid_, wid = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                # click 工具支持 button 参数；double_click/right_click 有独立工具
                if action == "click":
                    r = await client.call("click", {
                        "pid": pid_, "x": x, "y": y, "button": "left",
                    })
                elif action == "double_click":
                    r = await client.call("double_click", {
                        "pid": pid_, "x": x, "y": y,
                    })
                else:  # right_click
                    r = await client.call("right_click", {
                        "pid": pid_, "x": x, "y": y,
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
                pid_, _ = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                r = await client.call("move_cursor", {"pid": pid_, "x": x, "y": y})
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
                pid_, _ = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                r = await client.call("drag", {
                    "pid": pid_,
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
                pid_, _ = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                r = await client.call("type_text", {
                    "pid": pid_, "text": text,
                })
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"type 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                return f"Typed: {text[:80]}{'…' if len(text) > 80 else ''}"

            elif action == "paste_text":
                if not text:
                    return ToolResult(
                        tool_call_id="",
                        content="paste_text requires text",
                        is_error=True,
                    )
                # 备份当前剪贴板
                r = await client.call("get_clipboard")
                backup = r.get("result", {}).get("text", "") if r.get("ok") else ""
                # 写入新文本
                await client.call("set_clipboard", {"text": text})
                # 粘贴
                pid_, _ = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                await client.call("hotkey", {"pid": pid_, "keys": ["cmd", "v"]})
                await asyncio.sleep(0.3)
                # 恢复原剪贴板
                await client.call("restore_clipboard", {"text": backup})
                return f"Pasted text: {text[:80]}{'…' if len(text) > 80 else ''}"

            elif action == "press":
                if not key:
                    return ToolResult(
                        tool_call_id="",
                        content="press requires key",
                        is_error=True,
                    )
                pid_, _ = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                r = await client.call("press_key", {
                    "pid": pid_, "key": key,
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
                pid_, _ = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                r = await client.call("hotkey", {
                    "pid": pid_, "keys": keys,
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
                pid_, _ = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                # 先移动光标到目标位置
                await client.call("move_cursor", {"pid": pid_, "x": x, "y": y})
                r = await client.call("scroll", {
                    "pid": pid_,
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

            elif action == "page":
                pid_, _ = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                key_ = "page_up" if direction == "up" else "page_down" if direction == "down" else None
                if key_ is None:
                    return ToolResult(
                        tool_call_id="",
                        content=f"page direction must be 'up' or 'down', got: {direction}",
                        is_error=True,
                    )
                r = await client.call("press_key", {"pid": pid_, "key": key_})
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"page 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                return f"Paged {direction}"

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
                pid_, _ = await client.ensure_focus()
                await client.call("hotkey", {"pid": pid_, "keys": ["cmd", "l"]})
                await asyncio.sleep(0.3)
                await client.call("type_text", {"pid": pid_, "text": target})
                await asyncio.sleep(0.2)
                await client.call("press_key", {"pid": pid_, "key": "return"})
                return f"Opened: {target}"

            elif action == "activate_app":
                if not target:
                    return ToolResult(
                        tool_call_id="",
                        content="activate_app requires target (app name)",
                        is_error=True,
                    )
                r = await client.call("activate_app", {"name": target})
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"activate_app 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                client.invalidate_focus()
                return f"Activated app: {target}"

            elif action == "list_windows":
                r = await client.call("list_windows")
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"list_windows 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                sc = r.get("result", {}).get("structuredContent", {})
                windows = sc.get("windows", []) if isinstance(sc, dict) else sc

                # 应用过滤器
                if visible_only:
                    windows = [
                        w for w in windows
                        if isinstance(w, dict) and w.get("is_on_screen")
                    ]
                if title_filter:
                    tf = title_filter.lower()
                    windows = [
                        w for w in windows
                        if isinstance(w, dict) and tf in str(w.get("title", "")).lower()
                    ]

                lines = [f"Found {len(windows)} window(s):"]
                for w in windows:
                    if isinstance(w, dict):
                        lines.append(
                            f"  pid={w.get('pid')} wid={w.get('window_id')} "
                            f"title={w.get('title', '')!r} z={w.get('z_index', 0)} "
                            f"visible={w.get('is_on_screen')}"
                        )
                return "\n".join(lines)

            elif action == "list_apps":
                r = await client.call("list_apps")
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"list_apps 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                sc = r.get("result", {}).get("structuredContent", {})
                apps = sc.get("apps", []) if isinstance(sc, dict) else sc

                if title_filter:
                    tf = title_filter.lower()
                    apps = [
                        a for a in apps
                        if isinstance(a, dict) and tf in str(a.get("name", "")).lower()
                    ]

                lines = [f"Found {len(apps)} app(s):"]
                for a in apps:
                    if isinstance(a, dict):
                        lines.append(
                            f"  pid={a.get('pid')} name={a.get('name', '')!r} "
                            f"bundle={a.get('bundle_id', '')}"
                        )
                return "\n".join(lines)

            elif action == "set_focus":
                if pid is None:
                    return ToolResult(
                        tool_call_id="",
                        content="set_focus requires pid",
                        is_error=True,
                    )
                client.set_focus(pid, window_id)
                return f"Set focus to pid={pid}, window_id={window_id}"

            elif action == "activate_window":
                if not target:
                    return ToolResult(
                        tool_call_id="",
                        content="activate_window requires target (app name)",
                        is_error=True,
                    )
                # cua-driver 的 bring_to_front 在 macOS 不可用，用 launch_app 重新激活
                r = await client.call("launch_app", {"name": target})
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"activate_window 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                client.invalidate_focus()
                return f"Activated window: {target}"

            elif action == "hide_app":
                pid_, _ = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                r = await client.call("hotkey", {"pid": pid_, "keys": ["cmd", "h"]})
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"hide_app 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                client.invalidate_focus()
                return f"Hid app (pid={pid_})"

            elif action == "minimize_window":
                pid_, _ = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                r = await client.call("hotkey", {"pid": pid_, "keys": ["cmd", "m"]})
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"minimize_window 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                client.invalidate_focus()
                return f"Minimized window (pid={pid_})"

            elif action == "kill_app":
                if pid is None:
                    return ToolResult(
                        tool_call_id="",
                        content="kill_app requires pid",
                        is_error=True,
                    )
                r = await client.call("kill_app", {"pid": pid})
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"kill_app 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                client.invalidate_focus()
                return f"Killed app (pid={pid})"

            elif action == "get_cursor_position":
                r = await client.call("get_cursor_position")
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"get_cursor_position 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                sc = r.get("result", {}).get("structuredContent", {})
                return f"Cursor position: ({sc.get('x', '?')}, {sc.get('y', '?')})"

            elif action == "set_value":
                if not element_token:
                    return ToolResult(
                        tool_call_id="",
                        content="set_value requires element_token",
                        is_error=True,
                    )
                if value is None:
                    return ToolResult(
                        tool_call_id="",
                        content="set_value requires value",
                        is_error=True,
                    )
                pid_, _ = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                r = await client.call("set_value", {
                    "pid": pid_,
                    "element_token": element_token,
                    "value": value,
                })
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"set_value 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                return f"Set value: {value!r} on element {element_token}"

            elif action == "get_accessibility_tree":
                pid_, wid = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                r = await client.call("get_accessibility_tree", {
                    "pid": pid_,
                    "window_id": wid,
                })
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"get_accessibility_tree 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                # 提取 AX 树文本
                result = r.get("result", {})
                content_list = result.get("content", [])
                text_parts = []
                for item in content_list:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                        else:
                            text_parts.append(json.dumps(item, ensure_ascii=False))
                    else:
                        text_parts.append(str(item))
                if text_parts:
                    return "\n".join(text_parts)
                # fallback: structuredContent
                sc = result.get("structuredContent")
                if sc is not None:
                    return json.dumps(sc, ensure_ascii=False, indent=2)
                return json.dumps(result, ensure_ascii=False, indent=2)

            elif action == "zoom":
                if x is None or y is None or end_x is None or end_y is None:
                    return ToolResult(
                        tool_call_id="",
                        content="zoom requires x, y, end_x, end_y",
                        is_error=True,
                    )
                pid_, wid = await client.ensure_focus(
                    pid_override=pid, window_override=window_id,
                )
                r = await client.call("get_window_state", {
                    "pid": pid_,
                    "window_id": wid,
                    "capture_mode": "vision",
                })
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"zoom 截图失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                # 提取图片
                content_list = r.get("result", {}).get("content", [])
                b64 = ""
                for item in content_list:
                    if isinstance(item, dict) and item.get("type") == "image":
                        b64 = item.get("data", "")
                        break
                # 兼容旧协议
                if not b64:
                    sc = r.get("result", {}).get("structuredContent", {})
                    b64 = sc.get("screenshot_png_b64", "")
                if not b64:
                    return ToolResult(
                        tool_call_id="",
                        content="zoom 截图返回为空",
                        is_error=True,
                    )
                # 裁剪区域并放大
                try:
                    from io import BytesIO  # noqa: PLC0415

                    from PIL import Image  # noqa: PLC0415
                    png_bytes = base64.b64decode(b64)
                    img = Image.open(BytesIO(png_bytes))
                    # 规范化坐标
                    left = min(x, end_x)
                    top = min(y, end_y)
                    right = max(x, end_x)
                    bottom = max(y, end_y)
                    cropped = img.crop((left, top, right, bottom))
                    buf = BytesIO()
                    cropped.save(buf, format="WEBP", quality=80)
                    out_b64 = base64.b64encode(buf.getvalue()).decode()
                    return ToolResult(
                        tool_call_id="",
                        content=f"Zoomed region ({left},{top})-({right},{bottom})",
                        images=[{"data": out_b64, "media_type": "image/webp"}],
                    )
                except ImportError:
                    # Pillow 不可用，返回原图
                    b64, media_type = _to_webp(b64)
                    return ToolResult(
                        tool_call_id="",
                        content=f"Zoom requested ({x},{y})-({end_x},{end_y}) but Pillow unavailable, returning full screenshot",
                        images=[{"data": b64, "media_type": media_type}],
                    )

            elif action == "check_permissions":
                r = await client.call("check_permissions")
                if not r.get("ok"):
                    return ToolResult(
                        tool_call_id="",
                        content=f"check_permissions 失败: {r.get('error', '?')}",
                        is_error=True,
                    )
                sc = r.get("result", {}).get("structuredContent", {})
                return (
                    f"Permissions:\n"
                    f"  accessibility: {sc.get('accessibility', '?')}\n"
                    f"  screen_recording: {sc.get('screen_recording', '?')}"
                )

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
