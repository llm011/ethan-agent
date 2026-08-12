"""wait_for_user 工具 — Agent 等待用户完成外部操作后继续。

场景：OAuth 授权（飞书/GitHub）、需要用户在浏览器中操作后确认、
需要用户填写验证码/确认码等。

工具本身标记 intercept=True，agent loop 在 ToolExecutor 之前拦截：
  1. 向 SSE 流 yield WaitForUserEvent
  2. await Future（300s 超时 → 走 "timeout"）
  3. 把用户确认/输入作为 tool result 写入 working messages
"""
from __future__ import annotations

from ethan.tools.base import BaseTool


class WaitForUserTool(BaseTool):
    """等待用户完成外部操作后继续（长超时，非危险操作）。"""

    fast_path = True
    cacheable = False
    side_effect = False
    intercept = True  # agent loop 拦截，不进 executor

    name = "wait_for_user"
    description = (
        "等待用户完成外部操作后继续。用于 OAuth 授权、需要用户在浏览器中操作后确认、"
        "需要用户填写验证码等场景。"
        "调用后会阻塞等待用户回应（默认 300 秒超时，超时后返回 'timeout'）。"
        "input_type='confirm' 显示确认/取消按钮；input_type='text' 显示文本输入框。"
        "不用于业务多选分支（用 ask_user）或危险操作授权（系统自动处理）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "向用户展示的提示信息，应包含需要用户执行的操作说明（如授权链接）",
            },
            "input_type": {
                "type": "string",
                "enum": ["confirm", "text"],
                "description": "confirm：显示确认/取消按钮；text：显示文本输入框",
                "default": "confirm",
            },
            "placeholder": {
                "type": "string",
                "description": "input_type='text' 时的输入框 placeholder",
                "default": "",
            },
            "confirm_label": {
                "type": "string",
                "description": "确认按钮的文本",
                "default": "已完成",
            },
            "cancel_label": {
                "type": "string",
                "description": "取消按钮的文本",
                "default": "取消",
            },
            "timeout": {
                "type": "integer",
                "description": "超时秒数（默认 300，最大 600）",
                "default": 300,
            },
        },
        "required": ["prompt"],
    }

    async def run(
        self,
        prompt: str = "",
        input_type: str = "confirm",
        placeholder: str = "",
        confirm_label: str = "已完成",
        cancel_label: str = "取消",
        timeout: int = 300,
    ) -> str:
        # 正常不会被调用：agent loop 在 ToolExecutor 之前拦截。
        return "timeout"
