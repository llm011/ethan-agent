"""主动写入行为规则工具 — 让 agent 即时将用户指令持久化到 procedures.json。"""
from ethan.memory.procedures import ProcedureStore
from ethan.tools.base import BaseTool


class ProcedureWriteTool(BaseTool):
    fast_path = False
    name = "procedure_write"
    description = (
        "Proactively save a behavioral rule or standing instruction to long-term procedural memory. "
        "Call this when the user tells you how to behave going forward — e.g. 'always reply in English', "
        "'don't use Korean', 'use X phrase to motivate me', or any persistent behavioral directive."
    )
    parameters = {
        "type": "object",
        "properties": {
            "rule": {
                "type": "string",
                "description": "The behavioral rule written as a clear directive, e.g. 'Always reply in Chinese'",
            },
            "context": {
                "type": "string",
                "description": "Optional: when or why this rule applies",
            },
        },
        "required": ["rule"],
    }

    async def run(self, rule: str, context: str = "") -> str:
        store = ProcedureStore()
        store.add(rule, context=context)
        return f"Rule saved: {rule}"
