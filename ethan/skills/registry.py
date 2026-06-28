"""Skill 注册表 — 管理已加载的 Skills，支持按关键词匹配。"""
from ethan.skills.loader import Skill, load_all_skills
from ethan.skills.stats import SkillStats

# 超过此长度的 skill content 会截断，避免 token 膨胀
# 复杂 Skill（如 HA 设备列表）需要更大空间；可在 config 里调整
_MAX_SKILL_CONTENT = 3000


class SkillRegistry:
    def __init__(self, user_id: str = ""):
        from ethan.core.paths import user_skill_stats_path
        self._user_id = user_id
        self._skills: list[Skill] = []
        # per-profile 技能统计；user_id 为空（default profile）时读顶层路径
        stats_path = user_skill_stats_path()
        self._stats = SkillStats(path=stats_path) if stats_path else SkillStats()

    def load(self) -> None:
        """从磁盘加载所有 Skills。"""
        self._skills = load_all_skills(self._user_id)

    def all(self) -> list[Skill]:
        return list(self._skills)

    def get(self, name: str) -> Skill | None:
        for s in self._skills:
            if s.name == name:
                return s
        return None

    def match(self, query: str, channel: str = "", mode: str = "") -> list[Skill]:
        """根据用户输入匹配相关 Skills。

        channel 非空时过滤渠道。匹配分两类：
        - 模式专属 skill（skill.modes 非空）：只在所列 mode 生效，且一旦处于该 mode
          就**无条件命中**——用户显式切到该模式即是最强意图信号，不再卡触发词。
          其它模式下完全不出现（零污染）。
        - 通用 skill（skill.modes 为空）：在所有模式可用，按触发词关键词匹配。
        """
        query_lower = query.lower()
        matched = []
        for skill in self._skills:
            if skill.channels and channel and channel not in skill.channels:
                continue
            if skill.modes:
                # 模式专属：处于其模式即命中，否则跳过（不参与触发词匹配）
                if mode in skill.modes:
                    matched.append(skill)
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

    def build_context(self, query: str, channel: str = "", mode: str = "", max_skills: int = 3) -> str:
        """为 LLM 构建 Skill 上下文注入内容。

        只注入匹配的 skill，content 超长时截断，避免 token 膨胀。
        未匹配时不注入任何内容。mode 透传给 match 做模式过滤。
        """
        matched = self.match(query, channel=channel, mode=mode)[:max_skills]
        if not matched:
            return ""

        parts = []
        for skill in matched:
            content = skill.content
            if len(content) > _MAX_SKILL_CONTENT:
                content = content[:_MAX_SKILL_CONTENT] + "\n…(truncated)"
            parts.append(f"[Skill: {skill.name}]\n{content}")
        return "\n\n".join(parts)
