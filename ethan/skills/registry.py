"""Skill 注册表 — 管理已加载的 Skills，支持按关键词匹配。"""
from ethan.skills.loader import Skill, load_all_skills
from ethan.skills.stats import SkillStats

# 超过此长度的 skill content 会截断，避免 token 膨胀
# 复杂 Skill（如 HA 设备列表）需要更大空间；可在 config 里调整
_MAX_SKILL_CONTENT = 3000


class SkillRegistry:
    def __init__(self):
        self._skills: list[Skill] = []
        self._stats = SkillStats()

    def load(self) -> None:
        """从磁盘加载所有 Skills。"""
        self._skills = load_all_skills()

    def all(self) -> list[Skill]:
        return list(self._skills)

    def get(self, name: str) -> Skill | None:
        for s in self._skills:
            if s.name == name:
                return s
        return None

    def match(self, query: str, channel: str = "") -> list[Skill]:
        """根据用户输入匹配相关 Skills（关键词匹配）。channel 非空时过滤渠道。"""
        query_lower = query.lower()
        matched = []
        for skill in self._skills:
            if skill.channels and channel and channel not in skill.channels:
                continue
            for trigger in skill.trigger:
                if trigger.lower() in query_lower:
                    matched.append(skill)
                    break
        return matched

    def record_hit(self, skill_name: str):
        self._stats.record_hit(skill_name)

    def record_correction(self, skill_name: str, correction: str):
        self._stats.record_correction(skill_name, correction)

    def skills_needing_update(self, threshold: int = 2) -> list[str]:
        return [n for n in self._stats.all() if self._stats.needs_update(n, threshold)]

    def build_context(self, query: str, channel: str = "", max_skills: int = 3) -> str:
        """为 LLM 构建 Skill 上下文注入内容。

        只注入匹配的 skill，content 超长时截断，避免 token 膨胀。
        未匹配时不注入任何内容。
        """
        matched = self.match(query, channel=channel)[:max_skills]
        if not matched:
            return ""

        parts = []
        for skill in matched:
            content = skill.content
            if len(content) > _MAX_SKILL_CONTENT:
                content = content[:_MAX_SKILL_CONTENT] + "\n…(truncated)"
            parts.append(f"[Skill: {skill.name}]\n{content}")
        return "\n\n".join(parts)
