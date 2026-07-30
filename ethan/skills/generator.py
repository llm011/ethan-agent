"""Skill 生成器 — 从对话经验中自动提炼 Skill（Hermes 风格）。

生成前会先扫描现有 skill 清单，若发现主题相似的 skill，则增量补充到现有文件，
而不是新建一个重复的 —— 避免 skill 膨胀（曾经一次对话生成 17 个 code-review 变体）。
"""
import re
import time
from pathlib import Path

from ethan.providers.base import BaseProvider, Message

MIN_TURNS = 5        # 至少 N 轮用户消息才分析（比记忆提取 3 轮更克制——skill 是更重的产物）
MIN_CONV_LEN = 300   # 对话内容至少 N 字才分析

GENERATE_PROMPT = """分析以下对话，判断是否包含一个值得提炼成可复用 Skill 的模式或流程。

判断标准（同时满足才生成）：
- 解决了有一定复杂度的问题（不是简单问答或闲聊）
- 包含明确的步骤、方法或流程，未来可能反复用到
- 有合适的触发词可以匹配相似请求

现有 Skills 清单（name | triggers | description）：
{existing_skills}

判定优先级：
1. 如果对话的模式和某个现有 skill 高度重叠（主题/流程相似），输出 UPDATE 增量补充其缺失的点，不要新建。
   ——「高度重叠」指解决的是同一类问题，哪怕措辞不同。宁可补充也不要重复。
2. 只有在现有 skill 都不覆盖该主题时，才输出 CREATE 新建。
3. 不值得提炼时，只输出 NO_SKILL，不要解释。

输出格式（严格遵循，不要多余解释）：

如果是 UPDATE：
UPDATE: <现有 skill 的 name>
<要补充的内容，100-300字，只写现有 skill 里没有的点>

如果是 CREATE：
---创建新 skill---
---
name: short-kebab-case-name
trigger: keyword1|keyword2|keyword3
description: 一句话描述（≤20字）
fast_path: false
---
Skill 正文（清晰的步骤/要点，100-300字）

如果是 NO_SKILL：
NO_SKILL

---
对话内容：
{conversation}
"""


class SkillGenerator:
    def __init__(self, provider: BaseProvider | None = None, model: str | None = None, user_id: str = ""):
        self._provider = provider
        self._user_id = user_id

    async def maybe_generate(self, messages: list[Message]) -> Path | None:
        """分析对话，如果值得则自动生成或补充 Skill。返回文件路径或 None。"""
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

        # 加载现有 skill 清单，让 LLM 判断是否已有相似主题
        existing_skills = self._build_existing_skills_brief()

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

        prompt = GENERATE_PROMPT.format(
            existing_skills=existing_skills or "(暂无现有 skill)",
            conversation=conversation[:3000],
        )
        try:
            resp = await provider.chat(
                [Message(role="user", content=prompt)],
                system="你是一个 Skill 提炼助手。严格按格式输出：NO_SKILL / CREATE / UPDATE。",
            )
        except Exception:
            return None

        text = resp.content.strip()

        # 分支 1：不值得提炼
        if "NO_SKILL" in text:
            return None

        # 分支 2：增量补充到现有 skill
        if text.startswith("UPDATE:"):
            return self._apply_update(text, skills_dir)

        # 分支 3：新建 skill
        if "---" in text:
            return self._apply_create(text, skills_dir)

        return None

    def _build_existing_skills_brief(self) -> str:
        """构建现有 skill 清单：每行一个 skill 的 name + trigger + description。

        只取清单信息，不读 content —— 给 LLM 判断相似性用，避免 prompt 过大。
        """
        try:
            from ethan.skills.loader import load_all_skills
            skills = load_all_skills(self._user_id)
        except Exception:
            return ""
        lines = []
        for s in skills:
            triggers = " | ".join(s.trigger[:5])
            desc = (s.description or "")[:60]
            lines.append(f"- {s.name} | triggers: {triggers} | desc: {desc}")
        return "\n".join(lines)

    def _apply_update(self, text: str, skills_dir: Path) -> Path | None:
        """解析 UPDATE 指令，把补充内容追加到现有 skill 文件。

        格式：
            UPDATE: <skill_name>
            <补充内容>
        """
        lines = text.splitlines()
        if not lines or not lines[0].startswith("UPDATE:"):
            return None
        skill_name = lines[0][len("UPDATE:"):].strip()
        if not skill_name:
            return None

        # 定位现有 skill 文件（支持目录格式和旧平铺格式）
        skill_dir = skills_dir / skill_name
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            skill_file = skills_dir / f"{skill_name}.md"
            if not skill_file.exists():
                return None

        supplement = "\n".join(lines[1:]).strip()
        if not supplement:
            return None

        # 追加补充段落，保留原内容不动
        ts = time.strftime("%Y-%m-%d", time.localtime())
        block = f"\n\n<!-- auto-supplement: {ts} -->\n## 补充要点（自动生成）\n{supplement}\n"
        try:
            with open(skill_file, "a", encoding="utf-8") as f:
                f.write(block)
            return skill_file
        except Exception:
            return None

    def _apply_create(self, text: str, skills_dir: Path) -> Path | None:
        """解析 CREATE 指令，新建 skill 文件。"""
        # 兼容 "---创建新 skill---\n---\n..." 前缀：截取从第一个 "---\n" 开始
        idx = text.find("---\n")
        if idx < 0:
            return None
        skill_text = text[idx:]

        name_match = re.search(r"name:\s*(.+)", skill_text)
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
        skill_file.write_text(skill_text, encoding="utf-8")
        return skill_file
