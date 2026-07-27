"""Decide 工具 — Adaptive Planning 的结构化决策出口。

替代之前「在 thought 里输出『决策: X』标记」的文本协议：
- 旧方案问题：reasoning model 把标记放在 thought 里 → 用户看不到但代码也检测不到；
  非 reasoning model 把标记放在 content 里 → 用户直接看到「决策: B」这种诡异文本。
- 新方案：模型通过 tool_call 表达决策，agent loop 在执行前拦截，读 choice 字段，
  不真正执行、不进 working 上下文、不展示给用户。

工具本身只做 schema 占位，run() 不会被调用（agent loop 在 ToolExecutor 之前拦截）。
"""
from __future__ import annotations

from ethan.tools.base import BaseTool


class DecideTool(BaseTool):
    """结构化决策出口。模型在决策提示轮调用本工具表达 A/B/C 选择。"""

    fast_path = True
    cacheable = False
    side_effect = False
    # 关键标记：agent loop 见到此工具的 tool_call 时拦截，不执行、不进 working
    # （在 agent.py 的 _is_decision_call / _intercept_decision 逻辑里识别）
    intercept = True

    name = "decide"
    description = (
        "在系统提示你做 A/B/C 决策时，调用本工具表达选择。"
        "不要在回复正文里写「决策: X」之类的标记，直接调本工具即可。"
        "choice 取值："
        "A=最后 1 步收尾，本轮调完工具就能交付；"
        "B=还需 2 步以上，应先 plan_write 列步骤；"
        "C=需要更多信息或工具失败，希望补充上下文或向用户提问。"
        "reason 简述一句理由（不超过 50 字）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "choice": {
                "type": "string",
                "enum": ["A", "B", "C"],
                "description": "决策选择：A/B/C",
            },
            "reason": {
                "type": "string",
                "description": "一句理由（不超过 50 字）",
                "default": "",
            },
        },
        "required": ["choice"],
    }

    async def run(self, choice: str, reason: str = "") -> str:
        # 正常不会被调用：agent loop 在 ToolExecutor 之前拦截 decide。
        # 留个兜底，防止某条路径漏过拦截。
        return f"已决策：{choice}" + (f"（{reason}）" if reason else "")
