"""记忆压缩器 — 用廉价模型做对话摘要和 key facts 提取。

两个触发点：
  1. 热区溢出攒够一批 → compress(): 生成温区 rolling summary
  2. 温区累积够了 → extract_cold(): 提取 key facts 并精简 summary

Phase 2c: 重要性评分 — 决策/偏好/纠正的轮次得到更高权重。
"""
from ethan.providers.base import BaseProvider, Message
from ethan.providers.manager import create_provider
from ethan.core.config import get_config


_CHEAP_MODEL_MAP = {
    "claude-opus": "claude-haiku-4.5",
    "claude-sonnet": "claude-haiku-4.5",
    "claude-haiku": "claude-haiku-4.5",
    "gemini-2.5-pro": "gemini-2.5-flash-lite",
    "gemini-2.5-flash": "gemini-2.5-flash-lite",
    "gemini-3-pro": "gemini-3-flash",
    "gemini-3-flash": "gemini-3-flash",
    "gemini-3.5-flash": "gemini-3.1-flash-lite-preview",
    "gemini-3.1-pro": "gemini-3.1-flash-lite-preview",
    "gemini-3.1-flash": "gemini-3.1-flash-lite-preview",
    "gpt-5": "gpt-4o-mini",
    "gpt-4o": "gpt-4o-mini",
    "gpt-4o-mini": "gpt-4o-mini",
}

# Keywords indicating high-importance turns
_HIGH_IMPORTANCE_SIGNALS = [
    "决定", "prefer", "偏好", "always", "never", "一定", "不要", "记住",
    "correct", "纠正", "错了", "不对", "wrong", "改成", "应该",
    "重要", "关键", "critical", "deadline", "截止",
]


def _score_importance(messages: list[Message]) -> float:
    """Score a pair of messages for importance (0.0-1.0)."""
    text = " ".join(m.content.lower() for m in messages if m.content)
    score = 0.3  # baseline
    for signal in _HIGH_IMPORTANCE_SIGNALS:
        if signal in text:
            score += 0.15
    return min(score, 1.0)


def _infer_cheap_model(main_model: str) -> str:
    for prefix, cheap in _CHEAP_MODEL_MAP.items():
        if main_model.startswith(prefix):
            return cheap
    return main_model


def get_lite_model(main_model: str | None = None) -> str:
    """获取轻量模型：优先 config.defaults.lite_model，空则按主模型推断。"""
    from ethan.core.config import get_config
    cfg = get_config()
    if cfg.defaults.lite_model:
        return cfg.defaults.lite_model
    return _infer_cheap_model(main_model or cfg.defaults.model)


class Consolidator:
    """用廉价模型做记忆压缩。"""

    def __init__(self, main_model: str, summary_model: str | None = None):
        self._cheap_model = summary_model or get_lite_model(main_model)
        self._provider: BaseProvider | None = None

    async def _get_provider(self) -> BaseProvider:
        if self._provider is None:
            self._provider = create_provider(self._cheap_model)
        return self._provider

    async def compress(self, messages: list[Message], existing_summary: str = "") -> str:
        """将一批消息压缩成摘要文本，高重要性内容保留更多细节。"""
        provider = await self._get_provider()

        # Score importance per pair
        importance = _score_importance(messages)

        conversation = "\n".join(
            f"{'用户' if m.role == 'user' else 'AI'}: {m.content}"
            for m in messages if m.content and m.role in ("user", "assistant")
        )

        prompt_parts = []
        if existing_summary:
            prompt_parts.append(f"已有的对话摘要：\n{existing_summary}\n")
        prompt_parts.append(f"新的对话内容：\n{conversation}")

        if importance > 0.6:
            prompt_parts.append("\n注意：这段对话包含重要的决策、偏好或纠正，请保留更多细节。")
            prompt_parts.append("请压缩为 150-300 字的摘要，关键决策和偏好要保留原文。只输出摘要。")
        else:
            prompt_parts.append("\n请将以上对话内容压缩成一段简洁的摘要（100-200字），保留关键信息和用户意图。只输出摘要。")

        resp = await provider.chat(
            [Message(role="user", content="\n".join(prompt_parts))],
            system="你是一个对话摘要助手，负责将对话压缩成简洁的摘要。",
        )
        return resp.content.strip()

    async def extract_cold(self, warm_summary: str, existing_facts: str = "") -> dict:
        """从温区 summary 中提取长期记忆，并精简 summary。

        返回 dict: {"key_facts": [...], "profile_psych": [...], "condensed": str}
        """
        provider = await self._get_provider()

        prompt_parts = []
        if existing_facts:
            prompt_parts.append(f"已有的长期记忆：\n{existing_facts}\n")
        prompt_parts.append(f"对话摘要：\n{warm_summary}")
        prompt_parts.append("""请从对话摘要中抽取用户的长期记忆，严格按以下格式输出（每个块都要有，没有内容的块留空即可，不要编造）：

[KEY_FACTS]
值得长期记住的关键事实（用户偏好、重要决定、关键信息），每条一个简短要点：
- 要点 1
- 要点 2

[SUMMARY]
将剩余对话精简为 1-2 句话。

抽取要求：每条要点要原子化、能脱离对话独立成立；若信息与已知的长期记忆冲突，输出最新的一条即可。""")

        resp = await provider.chat(
            [Message(role="user", content="\n".join(prompt_parts))],
            system="你是一个记忆管理助手，负责提取长期记忆和精简对话摘要。",
        )

        text = resp.content.strip()
        return _parse_extraction(text)


def _parse_block(text: str, marker: str) -> list[str]:
    """从 text 中抽取某个 [MARKER] 块下的 bullet 列表。块边界 = 下一个 [开头的标记或文末。"""
    if marker not in text:
        return []
    after = text.split(marker, 1)[1]
    # 块到下一个 [MARKER] 为止
    rest = after
    for i, ch in enumerate(after):
        if ch == "[" and i > 0 and after[i - 1] in ("\n", " "):
            rest = after[:i]
            break
    lines = [ln.strip().lstrip("- ").lstrip("•").strip() for ln in rest.split("\n")]
    return [ln for ln in lines if ln]


def _parse_extraction(text: str) -> dict:
    """解析 extract_cold 的输出。容错：标记缺失时对应字段为空。"""
    key_facts = _parse_block(text, "[KEY_FACTS]")
    profile_psych = _parse_block(text, "[PROFILE_PSYCH]")

    condensed = ""
    if "[SUMMARY]" in text:
        condensed = text.split("[SUMMARY]", 1)[1].strip()
    elif not (key_facts or profile_psych):
        # 完全没按格式，fallback 取前 200 字当摘要
        condensed = text[:200]
    return {
        "key_facts": key_facts,
        "profile_psych": profile_psych,
        "condensed": condensed,
    }
