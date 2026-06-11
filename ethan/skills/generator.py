"""Skill 生成器 — 从对话经验中自动提炼 Skill（Hermes 风格）。"""
from pathlib import Path

from ethan.core.config import CONFIG_DIR
from ethan.providers.base import BaseProvider, Message

SKILLS_DIR = CONFIG_DIR / "skills"

GENERATE_PROMPT = """分析以下对话，判断是否包含一个值得提炼成可复用 Skill 的模式或流程。

判断标准：
- 解决了一个有一定复杂度的问题
- 包含可复用的步骤或方法
- 未来可能再次遇到类似问题

如果值得提炼，请生成一个 Skill 文件（Markdown + YAML frontmatter）。
如果不值得（只是简单问答或闲聊），返回 "NO_SKILL"。

Skill 格式：
---
name: short-kebab-case-name
trigger: keyword1|keyword2|keyword3
description: 一句话描述
---

Skill 正文（步骤、要点、注意事项等）

---
对话内容：
{conversation}
"""


class SkillGenerator:
    def __init__(self, provider: BaseProvider):
        self._provider = provider

    async def maybe_generate(self, messages: list[Message]) -> Path | None:
        """分析对话，如果值得则自动生成 Skill 文件。返回文件路径或 None。"""
        conversation = "\n".join(
            f"{'User' if m.role == 'user' else 'Ethan'}: {m.content}"
            for m in messages if m.content and m.role in ("user", "assistant")
        )

        if len(conversation) < 200:
            return None

        prompt = GENERATE_PROMPT.format(conversation=conversation)
        resp = await self._provider.chat(
            [Message(role="user", content=prompt)],
            system="你是一个 Skill 提炼助手。只输出 Skill 文件内容或 NO_SKILL。",
        )

        text = resp.content.strip()
        if "NO_SKILL" in text or "---" not in text:
            return None

        # 提取 name
        import re
        name_match = re.search(r"name:\s*(.+)", text)
        if not name_match:
            return None
        name = name_match.group(1).strip()

        # 保存
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        path = SKILLS_DIR / f"{name}.md"
        path.write_text(text, encoding="utf-8")
        return path
