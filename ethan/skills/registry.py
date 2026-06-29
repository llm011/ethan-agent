"""Skill 注册表 — 管理已加载的 Skills，支持按关键词匹配。"""
import hashlib
import json

from ethan.skills.loader import Skill, load_all_skills
from ethan.skills.stats import SkillStats

# 超过此长度的 skill content 会截断，避免 token 膨胀
# 复杂 Skill（如 HA 设备列表）需要更大空间；可在 config 里调整
_MAX_SKILL_CONTENT = 3000

# 进程级 router 缓存：skill 集合不变时复用已编码锚点，避免每请求重编码
_ROUTER_CACHE: dict[str, "EmbeddingRouter"] = {}


def _skill_fingerprint(skills: list[Skill]) -> str:
    """计算 skill 集合的稳定指纹（名字 + trigger + description）。

    用于判断是否需要重建 router：指纹相同 → 锚点不变 → 直接复用。
    """
    data = []
    for s in sorted(skills, key=lambda x: x.name):
        data.append({
            "name": s.name,
            "trigger": sorted(s.trigger),
            "desc": s.description,
        })
    # json 确保跨进程稳定，hashlib 指纹短
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


class SkillRegistry:
    def __init__(self, user_id: str = ""):
        from ethan.core.paths import user_skill_stats_path
        self._user_id = user_id
        self._skills: list[Skill] = []
        # per-profile 技能统计；user_id 为空（default profile）时读顶层路径
        stats_path = user_skill_stats_path()
        self._stats = SkillStats(path=stats_path) if stats_path else SkillStats()
        # embedding 路由器（可选）：模型/依赖缺失时不可用，match() 自动退回关键词
        self._router = None

    def load(self) -> None:
        """从磁盘加载所有 Skills。"""
        self._skills = load_all_skills(self._user_id)
        self._build_router()

    def _build_router(self) -> None:
        """构建 embedding 路由器索引；依赖或模型缺失时静默跳过。

        按 skill 集合指纹缓存：同一进程内 skill 不变时直接复用已编码锚点，
        避免每个请求都重新 ONNX 推理一遍静态锚点。
        """
        try:
            from ethan.skills.router import EmbeddingRouter
            fp = _skill_fingerprint(self._skills)
            cached = _ROUTER_CACHE.get(fp)
            if cached is not None:
                self._router = cached
                return
            router = EmbeddingRouter()
            if router.available and router.build(self._skills):
                self._router = router
                _ROUTER_CACHE[fp] = router
            else:
                self._router = None
        except Exception:
            self._router = None

    def all(self) -> list[Skill]:
        return list(self._skills)

    def get(self, name: str) -> Skill | None:
        for s in self._skills:
            if s.name == name:
                return s
        return None

    def match(self, query: str, channel: str = "") -> list[Skill]:
        """匹配相关 Skills。关键词子串匹配为基础（保 head 精度 + 强拒识），
        若可用，再用 embedding 路由器补一个语义命中（补 tail 召回）。
        channel 非空时过滤渠道。"""
        query_lower = query.lower()
        matched = []
        seen = set()
        for skill in self._skills:
            if skill.channels and channel and channel not in skill.channels:
                continue
            for trigger in skill.trigger:
                if trigger.lower() in query_lower:
                    matched.append(skill)
                    seen.add(skill.name)
                    break

        # embedding 路由补召回：关键词漏掉的 tail 改写，FLOOR=0.55 宁可漏不可错
        if self._router is not None:
            name = self._router.route(query)
            if name and name not in seen:
                skill = self.get(name)
                if skill and not (skill.channels and channel and channel not in skill.channels):
                    matched.append(skill)
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
