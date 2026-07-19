"""主动写入记忆工具 — 让 agent 即时将用户信息持久化到结构化记忆库。

旧实现写 facts.json（已退役）；现在构造 explicit 候选走准入管道，
与自动提取的记忆同库同语义（证据溯源 + merge/supersede）。
"""
from ethan.tools.base import BaseTool


class MemoryWriteTool(BaseTool):
    fast_path = False
    side_effect = True
    name = "memory_write"
    description = (
        "Proactively save a factual memory about the user (preference, personal info, decision) "
        "to long-term memory. Call this when the user shares something worth remembering across "
        "conversations — e.g. their name, job, preferences, or a one-off decision. "
        "Never include raw secrets/tokens/API keys in the content; reference them by key name only "
        "(e.g., 'token is in secrets with key=github_pat')."
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
        from ethan.core.context import get_session_id
        from ethan.memory.admission import run_incremental_admission
        from ethan.memory.legacy_migration import _classify, _legacy_key
        from ethan.memory.records import (
            EvidenceLevel,
            MemoryCandidate,
            MemoryDomain,
            ScopeType,
        )
        from ethan.memory.store import MemoryStore

        content = content.strip()
        if not content:
            return "Nothing to remember (empty content)."

        memory_type, dimension = _classify(content, category)
        # correction 语义：用户纠正了之前的事 → corrected 准入会 supersede 同 key 旧记忆
        evidence_level = (
            EvidenceLevel.CORRECTED.value if category == "correction" else EvidenceLevel.EXPLICIT.value
        )
        candidate = MemoryCandidate(
            memory_type=memory_type,
            dimension=dimension,
            memory_key=_legacy_key(content),
            content=content,
            scope_type=ScopeType.USER.value,
            scope_id="self",
            memory_domain=MemoryDomain.GENERAL.value,
            evidence_level=evidence_level,
            confidence=0.95,
            importance=0.7,
            source_session_id=get_session_id() or "agent_proactive",
            source_message_id="",
            source_role="user",
            source_quote=content[:1000],
            extractor_name="agent_proactive",
            extractor_version="v1",
        )
        store = MemoryStore()
        try:
            inserted_ids = set(store.create_candidate_batch([candidate]))
            if not inserted_ids:
                return f"Already remembered: {content}"
            result = run_incremental_admission(store, [candidate])
            if result.admitted:
                return f"Remembered: {content}"
            if result.merged:
                return f"Reinforced existing memory: {content}"
            return f"Noted: {content}"
        finally:
            store.close()
