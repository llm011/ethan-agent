"""Skill 注册表 — 管理已加载的 Skills，支持按关键词匹配。"""
from ethan.skills.loader import Skill, load_all_skills

# 超过此长度的 skill content 会截断，避免 token 膨胀
_MAX_SKILL_CONTENT = 800


class SkillRegistry:
    def __init__(self):
        self._skills: list[Skill] = []

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

    def match(self, query: str) -> list[Skill]:
        """根据用户输入匹配相关 Skills（关键词匹配）。"""
        query_lower = query.lower()
        matched = []
        for skill in self._skills:
            for trigger in skill.trigger:
                if trigger.lower() in query_lower:
                    matched.append(skill)
                    break
        return matched

    def build_context(self, query: str, max_skills: int = 3) -> str:
        """为 LLM 构建 Skill 上下文注入内容。

        只注入匹配的 skill，content 超长时截断，避免 token 膨胀。
        未匹配时不注入任何内容。
        """
        matched = self.match(query)[:max_skills]
        if not matched:
            return ""

        parts = []
        for skill in matched:
            content = skill.content
            if len(content) > _MAX_SKILL_CONTENT:
                content = content[:_MAX_SKILL_CONTENT] + "\n…(truncated)"
            parts.append(f"[Skill: {skill.name}]\n{content}")
        return "\n\n".join(parts)
