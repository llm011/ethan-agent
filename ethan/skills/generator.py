"""Skill 生成器 — 从对话经验中自动提炼 Skill（Hermes 风格）。"""
import re
from pathlib import Path

from ethan.providers.base import BaseProvider, Message

MIN_TURNS = 5        # 至少 N 轮用户消息才分析（比记忆提取 3 轮更克制——skill 是更重的产物）
MIN_CONV_LEN = 300   # 对话内容至少 N 字才分析

GENERATE_PROMPT = """分析以下对话，判断是否包含一个值得提炼成可复用 Skill 的模式或流程。

判断标准（同时满足才生成）：
- 解决了有一定复杂度的问题（不是简单问答或闲聊）
- 包含明确的步骤、方法或流程，未来可能反复用到
- 有合适的触发词可以匹配相似请求

如果值得提炼，生成 Skill 文件（Markdown + YAML frontmatter）。
如果不值得，只输出 NO_SKILL，不要解释。

Skill 格式：
---
name: short-kebab-case-name
trigger: keyword1|keyword2|keyword3
description: 一句话描述（≤20字）
fast_path: false
---

Skill 正文（清晰的步骤/要点，100-300字）

---
对话内容：
{conversation}
"""


class SkillGenerator:
    def __init__(self, provider: BaseProvider | None = None, model: str | None = None, user_id: str = ""):
        self._provider = provider
        self._user_id = user_id

    async def maybe_generate(self, messages: list[Message]) -> Path | None:
        """分析对话，如果值得则自动生成 Skill 文件。返回文件路径或 None。"""
        from ethan.core.paths import user_skills_dir
        skills_dir = user_skills_dir()
        turns = sum(1 for m in messages if m.role == "user")
        if turns < MIN_TURNS:
            return None

        conversation = "\n".join(
            f"{'User' if m.role == 'user' else 'Ethan'}: {m.content[:300]}"
            for m in messages if m.content and m.role in ("user", "assistant")
        )
        if len(conversation) < MIN_CONV_LEN:
            return None

        # 用廉价模型分析
        provider = self._provider
        try:
            from ethan.core.config import get_config
            from ethan.memory.consolidator import get_lite_model
            from ethan.providers.manager import create_provider
            cfg = get_config()
            cheap_model = get_lite_model(cfg.defaults.model)
            provider = create_provider(cheap_model)
        except Exception:
            pass

        prompt = GENERATE_PROMPT.format(conversation=conversation[:3000])
        try:
            resp = await provider.chat(
                [Message(role="user", content=prompt)],
                system="你是一个 Skill 提炼助手。只输出 Skill 文件内容或 NO_SKILL。",
            )
        except Exception:
            return None

        text = resp.content.strip()
        if "NO_SKILL" in text or "---" not in text:
            return None

        name_match = re.search(r"name:\s*(.+)", text)
        if not name_match:
            return None
        name = re.sub(r"[^a-z0-9\-]", "-", name_match.group(1).strip().lower()).strip("-")
        if not name:
            return None

        # 去重：已存在则不覆盖（同时检查目录格式和旧平铺格式）
        skill_dir = skills_dir / name
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists() or (skills_dir / f"{name}.md").exists():
            return None

        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(text, encoding="utf-8")
        return skill_file
