"""ask_user 工具 — Agent 向用户请求确认或选择。

场景：业务流程确认、多选分支选择等非危险操作。
不用于文件操作、shell 执行等危险操作（那些走 consent）。

工具本身标记 intercept=True，agent loop 在 ToolExecutor 之前拦截：
  1. 向 SSE 流 yield AskUserEvent
  2. await Future（20s 超时 → 走 default）
  3. 把用户选择作为 tool result 写入 working messages
"""
from __future__ import annotations

from ethan.tools.base import BaseTool


class AskUserTool(BaseTool):
    """向用户请求确认或选择（非危险操作）。"""

    fast_path = True
    cacheable = False
    side_effect = False
    intercept = True  # agent loop 拦截，不进 executor

    name = "ask_user"
    description = (
        "向用户请求确认或选择。用于业务流程确认、多选分支等场景。"
        "不用于文件/shell 等危险操作的授权（那些由系统自动处理）。"
        "调用后会阻塞等待用户回复（20 秒超时走默认值）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "向用户展示的问题",
            },
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "展示给用户的选项文本"},
                        "value": {"type": "string", "description": "选项值（回传给模型）"},
                    },
                    "required": ["label", "value"],
                },
                "description": "选项列表（2-5 个）",
            },
            "default": {
                "type": "string",
                "description": "超时默认值（必须是某个 option 的 value）",
            },
        },
        "required": ["question", "options", "default"],
    }

    async def run(self, question: str = "", options: list = None, default: str = "") -> str:
        # 正常不会被调用：agent loop 在 ToolExecutor 之前拦截。
        return f"用户选择：{default}（超时默认）"
