"""主动写入记忆工具 — 让 agent 即时将用户信息持久化到 facts.json。"""
from ethan.memory.facts import FactStore
from ethan.tools.base import BaseTool


class MemoryWriteTool(BaseTool):
    fast_path = False
    side_effect = True
    name = "memory_write"
    description = (
        "Proactively save a factual memory about the user (preference, personal info, decision) "
        "to long-term memory. Call this when the user shares something worth remembering across "
        "conversations — e.g. their name, job, preferences, or a one-off decision."
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": (
                    "The fact to remember as a clear statement, e.g. "
                    "'User prefers dark mode' or 'User works at Acme Corp as an engineer'"
                ),
            },
            "category": {
                "type": "string",
                "description": "Category: preference | decision | knowledge | correction",
                "default": "preference",
            },
        },
        "required": ["content"],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, content: str, category: str = "preference") -> str:
        from ethan.core.paths import user_facts_path
        store = FactStore(path=user_facts_path())
        store.add(content, confidence=0.95, source="agent_proactive", category=category)
        return f"Remembered: {content}"
