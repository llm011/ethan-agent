"""记忆压缩器 — 用廉价模型做对话摘要和 key facts 提取。

两个触发点：
  1. 热区溢出攒够一批 → compress(): 生成温区 rolling summary
  2. 温区累积够了 → extract_cold(): 提取 key facts 并精简 summary
"""
from ethan.providers.base import BaseProvider, Message
from ethan.providers.manager import create_provider
from ethan.core.config import get_config


# 自动推断廉价模型
_CHEAP_MODEL_MAP = {
    "claude-opus": "claude-haiku-4-5",
    "claude-sonnet": "claude-haiku-4-5",
    "claude-haiku": "claude-haiku-4-5",
    "gemini-2.5-pro": "gemini-2.5-flash-lite",
    "gemini-2.5-flash": "gemini-2.5-flash-lite",
    "gemini-3-pro": "gemini-3-flash",
    "gemini-3-flash": "gemini-3-flash",
    "gpt-5": "gpt-4o-mini",
    "gpt-4o": "gpt-4o-mini",
    "gpt-4o-mini": "gpt-4o-mini",
}


def _infer_cheap_model(main_model: str) -> str:
    """根据主模型推断用于压缩的廉价模型。"""
    for prefix, cheap in _CHEAP_MODEL_MAP.items():
        if main_model.startswith(prefix):
            return cheap
    # 默认回退到主模型自身
    return main_model


class Consolidator:
    """用廉价模型做记忆压缩。"""

    def __init__(self, main_model: str, summary_model: str | None = None):
        self._cheap_model = summary_model or _infer_cheap_model(main_model)
        self._provider: BaseProvider | None = None

    async def _get_provider(self) -> BaseProvider:
        if self._provider is None:
            self._provider = create_provider(self._cheap_model)
        return self._provider

    async def compress(self, messages: list[Message], existing_summary: str = "") -> str:
        """将一批消息压缩成摘要文本。"""
        provider = await self._get_provider()

        conversation = "\n".join(
            f"{'用户' if m.role == 'user' else 'AI'}: {m.content}"
            for m in messages if m.content and m.role in ("user", "assistant")
        )

        prompt_parts = []
        if existing_summary:
            prompt_parts.append(f"已有的对话摘要：\n{existing_summary}\n")
        prompt_parts.append(f"新的对话内容：\n{conversation}")
        prompt_parts.append("\n请将以上对话内容压缩成一段简洁的摘要（中文，100-200字），保留关键信息和用户意图。只输出摘要，不要其他内容。")

        resp = await provider.chat(
            [Message(role="user", content="\n".join(prompt_parts))],
            system="你是一个对话摘要助手，负责将对话压缩成简洁的摘要。",
        )
        return resp.content.strip()

    async def extract_cold(self, warm_summary: str, existing_facts: str = "") -> tuple[str, str]:
        """从温区 summary 中提取 key facts（冷区），并精简 summary。

        返回: (key_facts, condensed_summary)
        """
        provider = await self._get_provider()

        prompt_parts = []
        if existing_facts:
            prompt_parts.append(f"已有的长期记忆：\n{existing_facts}\n")
        prompt_parts.append(f"对话摘要：\n{warm_summary}")
        prompt_parts.append("""
请完成两件事：
1. 提取值得长期记住的 key facts（用户偏好、重要决定、关键信息），用简短的要点列出
2. 将剩余的对话摘要精简为 1-2 句话

格式：
[KEY_FACTS]
- fact 1
- fact 2
[SUMMARY]
精简后的摘要
""")

        resp = await provider.chat(
            [Message(role="user", content="\n".join(prompt_parts))],
            system="你是一个记忆管理助手，负责提取长期记忆和精简对话摘要。",
        )

        text = resp.content.strip()

        # 解析输出
        key_facts = existing_facts
        condensed = ""

        if "[KEY_FACTS]" in text and "[SUMMARY]" in text:
            facts_part = text.split("[KEY_FACTS]")[1].split("[SUMMARY]")[0].strip()
            summary_part = text.split("[SUMMARY]")[1].strip()
            if existing_facts:
                key_facts = f"{existing_facts}\n{facts_part}"
            else:
                key_facts = facts_part
            condensed = summary_part
        else:
            condensed = text[:200]

        return key_facts, condensed
