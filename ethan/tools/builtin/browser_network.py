"""Browser network implementation; browser.py keeps compatibility exports."""
from __future__ import annotations

import json

from ethan.browser.hub import BrowserError

from .browser_compat import browser as B
from .browser_runtime import _BrowserToolBase


class BrowserNetworkTool(_BrowserToolBase):
    name = "browser_network"
    description = (
        "监控 session 的网络请求。start 开始抓包;stop 停止并清空;list 列出已捕获请求(可按 URL/类型过滤);"
        "detail 查看指定请求的详情(含响应体,最多 10000 字符)。"
        "常用场景:抓 API 响应数据代替从 DOM 里抠,排查请求失败原因。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "stop", "list", "detail"]},
            "session": {"type": "string", "description": "目标 session_id"},
            "filter": {"type": "string", "description": "list 时按 URL 或资源类型过滤(字符串包含匹配)"},
            "request_id": {"type": "string", "description": "detail 时的 requestId"},
        },
        "required": ["action", "session"],
    }

    async def run(self, action: str, session: str = "", filter: str = "", request_id: str = "") -> str:  # noqa: A002
        self._authorize()
        try:
            if action == "start":
                return json.dumps(await B._call("network_start", {"sessionId": session}), ensure_ascii=False)
            if action == "stop":
                return json.dumps(await B._call("network_stop", {"sessionId": session}), ensure_ascii=False)
            if action == "list":
                params: dict = {"sessionId": session}
                if filter:
                    params["filter"] = filter
                return json.dumps(await B._call("network_list", params), ensure_ascii=False)
            if action == "detail":
                return json.dumps(await B._call("network_detail", {"sessionId": session, "requestId": request_id}), ensure_ascii=False)
            return f"未知 action: {action}"
        except BrowserError as e:
            return f"浏览器错误: {e}" + (" (可重新 snapshot 后重试)" if e.retryable else "")


