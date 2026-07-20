"""主动写入记忆工具 — 让 agent 即时将用户信息持久化到结构化记忆库。

构造 explicit/corrected 候选走准入管道，与自动提取的记忆同库同语义
（证据溯源 + merge/supersede）。memory_type / dimension 由调用方决定，
未传时按 category 做最保守的兜底（不借用拟合测试数据的硬编码关键词表）。
"""
import hashlib

from ethan.tools.base import BaseTool

# category 兜底映射：agent 未传 memory_type/dimension 时使用。
# 注意：召回链路（recall.py）只按 domain 过滤，不依赖 dimension 标签；
# dimension 只在 admission 的 supersede 判定里用于"同 dimension + 内容发散"，
# 所以兜底用最粗粒度的"misc"维度，避免和真实维度撞车误触发 supersede。
#
# memory_type → dimension 前缀映射：personal_information 的真实前缀是 identity（不是 personal_information），
# 其余类型同名前缀。用于 agent 传 memory_type 但不传 dimension 时的兜底，保证主动写入路径
# 与自动提取路径产出相同 dimension 字符串——否则 supersede 判定（existing.dimension == candidate.dimension）
# 永远配不上，主动写的 identity 记忆会和自动抽取的各存一份、旧值不被替换。
_TYPE_DIMENSION_PREFIX: dict[str, str] = {
    "personal_information": "identity",
    "preference": "preference",
    "activity": "activity",
    "decision": "decision",
    "relationship": "relationship",
    "methodology": "methodology",
    "companion": "companion",
}

_CATEGORY_FALLBACK = {
    "preference": ("preference", "preference.misc"),
    "decision": ("decision", "decision.misc"),
    "correction": ("decision", "decision.misc"),
    "knowledge": ("personal_information", "identity.misc"),
}


def _memory_key(content: str) -> str:
    """同内容多次主动写入应聚合到同一条记忆（content sha1 作为 key）。

    独立于 legacy_migration 的 _legacy_key（命名空间区分），
    但算法保持一致：sha1(content).hexdigest()[:16]。
    """
    return "proactive_" + hashlib.sha1(content.strip().encode()).hexdigest()[:16]


class MemoryWriteTool(BaseTool):
    fast_path = False
    side_effect = True
    name = "memory_write"
    description = (
        "Proactively save a factual memory about the user to long-term memory. "
        "Call this when the user shares something worth remembering across "
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
            "memory_type": {
                "type": "string",
                "description": (
                    "Type of memory. Choose the most specific one: "
                    "personal_information (identity: name, location, job, education) | "
                    "preference (likes/dislikes, tools, communication style) | "
                    "decision (one-off choices) | "
                    "relationship (agreements with the assistant) | "
                    "methodology (how the user works) | "
                    "activity (current tasks) | "
                    "skill_experience (skills). "
                    "Defaults to 'preference' if unclear."
                ),
                "default": "preference",
            },
            "dimension": {
                "type": "string",
                "description": (
                    "Sub-dimension in '<type>.<facet>' form, e.g. "
                    "'identity.location', 'preference.tools', 'decision.chosen'. "
                    "Use '<type>.misc' if no specific facet fits. "
                    "Important for supersede: same dimension + divergent content replaces the old memory."
                ),
                "default": "",
            },
            "category": {
                "type": "string",
                "description": (
                    "Legacy coarse category (deprecated, kept for backward compat). "
                    "Prefer memory_type + dimension. If both are provided, category is ignored. "
                    "Use 'correction' to mark this as a correction of a previous memory."
                ),
                "enum": ["preference", "decision", "knowledge", "correction"],
                "default": "preference",
            },
        },
        "required": ["content"],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(
        self,
        content: str,
        category: str = "preference",
        *,
        memory_type: str = "",
        dimension: str = "",
    ) -> str:
        from ethan.core.context import get_session_id
        from ethan.memory.admission import run_incremental_admission
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

        # correction 语义：用户纠正了之前的事 → corrected 准入会 supersede 同 key 旧记忆
        is_correction = category == "correction"

        # 优先用 agent 显式传的 memory_type / dimension；未传则按 category 兜底
        if memory_type:
            mt = memory_type
            # 兜底 dimension 用 _TYPE_DIMENSION_PREFIX 查前缀（personal_information → identity），
            # 保证和 dimensions.py 注册表 + extractor 路径产出的 dimension 字符串一致。
            prefix = _TYPE_DIMENSION_PREFIX.get(mt, mt)
            dim = dimension or f"{prefix}.misc"
        else:
            mt, dim = _CATEGORY_FALLBACK.get(category, ("preference", "preference.misc"))

        evidence_level = (
            EvidenceLevel.CORRECTED.value if is_correction else EvidenceLevel.EXPLICIT.value
        )
        candidate = MemoryCandidate(
            memory_type=mt,
            dimension=dim,
            memory_key=_memory_key(content),
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
            extractor_version="v2",
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
