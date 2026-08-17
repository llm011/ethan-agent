"""桌面端工具 — 通过 WebSocket 控制桌面端的 countdown 和 notification。"""
from __future__ import annotations

from typing import Any

from ethan.desktop.hub import DesktopError, get_desktop_hub
from ethan.tools.base import BaseTool, ToolResult


class DesktopCountdownTool(BaseTool):
    fast_path = False  # 不在 base_tools 白名单，需经 find_tools 激活
    cacheable = False
    side_effect = True

    @property
    def name(self) -> str:
        return "desktop_countdown"

    @property
    def description(self) -> str:
        return (
            "Control the desktop countdown timer. Actions: "
            "'start' (begin countdown, optional minutes/label params, default 25min), "
            "'pause' (pause the timer), "
            "'resume' (resume paused timer), "
            "'reset' (reset to initial duration), "
            "'set_label' (update the displayed label without affecting timer), "
            "'close' (close the countdown window). "
            "Works by forwarding the command over WebSocket to the connected Ethan desktop app, "
            "so it works EVEN WHEN the server runs in Docker / headless / remote environments. "
            "If no desktop client is connected, the tool reports it explicitly — try it first "
            "rather than assuming it won't work based on the server's environment."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "pause", "resume", "reset", "close", "set_label"],
                    "description": "The countdown action to perform.",
                },
                "minutes": {
                    "type": "integer",
                    "description": "Duration in minutes (only for 'start' action). Default 25.",
                },
                "label": {
                    "type": "string",
                    "description": "Short label (max 10 chars) displayed above the countdown timer.",
                },
            },
            "required": ["action"],
        }

    async def run(self, **kwargs) -> str | ToolResult:
        action = kwargs.get("action", "start")
        minutes = kwargs.get("minutes")
        label = kwargs.get("label")
        hub = get_desktop_hub()
        if not hub.connected:
            return "错误：桌面端未连接。请确认 Ethan 桌面应用已启动并登录。"
        try:
            params: dict[str, Any] = {"action": action}
            if minutes is not None and action == "start":
                params["minutes"] = int(minutes)
            if label is not None and action in ("start", "set_label"):
                params["label"] = label[:10]
            await hub.notify("countdown", params)
            messages = {
                "start": f"倒计时已开始（{minutes or 25} 分钟）",
                "pause": "倒计时已暂停",
                "resume": "倒计时已继续",
                "reset": "倒计时已重置",
                "close": "倒计时窗口已关闭",
                "set_label": f"倒计时标签已更新：{label}",
            }
            return messages.get(action, f"已执行 countdown.{action}")
        except DesktopError as e:
            return f"桌面端操作失败：{e}"


class DesktopNotifyTool(BaseTool):
    fast_path = False  # full 档在 base_tools 直接可见（config.py），fast 档需 find_tools 激活
    cacheable = False
    side_effect = True

    @property
    def name(self) -> str:
        return "desktop_notify"

    @property
    def description(self) -> str:
        return (
            "Send a native desktop notification to the user (macOS/Windows system notification). "
            "Works by forwarding the notification over WebSocket to the connected Ethan desktop app, "
            "so it works EVEN WHEN the server runs in Docker / headless / remote environments "
            "where local notify-send or osascript would fail. "
            "Always prefer this tool over shell commands (notify-send/osascript) for desktop notifications. "
            "If no desktop client is connected, the tool reports it explicitly — try it first "
            "rather than assuming it won't work based on the server's environment."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Notification title.",
                },
                "body": {
                    "type": "string",
                    "description": "Notification body text.",
                },
            },
            "required": ["title", "body"],
        }

    async def run(self, **kwargs) -> str | ToolResult:
        title = kwargs.get("title", "")
        body = kwargs.get("body", "")
        hub = get_desktop_hub()
        if not hub.connected:
            return "错误：桌面端未连接。请确认 Ethan 桌面应用已启动并登录。"
        try:
            await hub.notify("notification", {"title": title, "body": body})
            return f"通知已发送：{title}"
        except DesktopError as e:
            return f"桌面端通知失败：{e}"
