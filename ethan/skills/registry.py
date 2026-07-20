"""Skill 注册表 — 管理已加载的 Skills，支持按关键词匹配。"""
import hashlib
import json
import logging
from pathlib import Path

from ethan.skills.loader import Skill, load_all_skills
from ethan.skills.stats import SkillStats

logger = logging.getLogger(__name__)

# 超过此长度的 skill content 会截断，避免 token 膨胀
# 复杂 Skill（如 HA 设备列表）需要更大空间；可在 config 里调整
_MAX_SKILL_CONTENT = 3000

# references 清单上限：超过此数量只列前 N 个 + "...还有 M 个"
_MAX_REFERENCES_LIST = 15

# 进程级 router 缓存：skill 集合不变时复用已编码锚点，避免每请求重编码
_ROUTER_CACHE: dict[str, "EmbeddingRouter"] = {}  # noqa: F821 — optional dep, forward ref


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


def _reference_summary(path: Path, max_len: int = 80) -> str:
    """读 references 文件取第一段非空文本（跳过 frontmatter / 标题 / 代码块），截到 max_len 字符。

    用于 build_context 的 references 清单——只给模型看「有哪些细节文档可查」，
    让模型用 skill_read 拉具体内容（pull-based，不全量灌入正文）。
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    lines = text.splitlines()
    in_front = False
    for i, ln in enumerate(lines):
        s = ln.strip()
        if i == 0 and s == "---":
            in_front = True
            continue
        if in_front:
            if s == "---":
                in_front = False
            continue
        if not s or s.startswith("#") or s.startswith("```") or s.startswith("|"):
            continue
        # 去掉 markdown 强调符号
        clean = s.lstrip("-*").strip()
        clean = clean.split("`")[0].strip()
        if clean:
            return clean[:max_len] + ("…" if len(clean) > max_len else "")
    return ""


def _build_references_block(skill: Skill) -> str:
    """构造 references 清单块：文件名 + 一行摘要。

    超过 _MAX_REFERENCES_LIST 个文件只列前 N 个 + "...还有 M 个"。
    无 references 返回空串。
    """
    refs = skill.references
    if not refs:
        return ""
    shown = refs[:_MAX_REFERENCES_LIST]
    lines = ["## References（用 skill_read 查阅详情）"]
    for p in shown:
        summary = _reference_summary(p)
        suffix = f": {summary}" if summary else ""
        lines.append(f"- {p.name}{suffix}")
    rest = len(refs) - len(shown)
    if rest > 0:
        lines.append(f"- …还有 {rest} 个（用 skill_read(name=\"{skill.name}\") 看完整目录）")
    return "\n".join(lines)


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

        判定链（缺一不可才进入 match() 的语义补召回）：
          1) router.available  → 模型文件(LR 头 + ONNX)是否在磁盘就绪
          2) router.build()     → LR 头能否加载 + 是否存在可路由 skill
          3) 运行时依赖(onnxruntime/transformers)是否在当前环境可导入
             —— 这步在 available/build 里不检查，会在首次 route() 时惰性失败，
                因此这里主动探一下，避免「显示已激活却永远不命中」的假象。
        仅当三者同时满足，self._router 才被设为非 None。
        """
        try:
            from ethan.skills.router import EmbeddingRouter

            fp = _skill_fingerprint(self._skills)
            cached = _ROUTER_CACHE.get(fp)
            if cached is not None:
                self._router = cached
                logger.info("[router] embedding 路由已激活（复用进程内缓存，指纹=%s）", fp[:8])
                return

            router = EmbeddingRouter()
            avail = router.available
            built = router.build(self._skills) if avail else False

            if avail and built:
                # 主动探测运行时依赖（available/build 不覆盖此步）；用 find_spec 不触发实际 import
                import importlib.util
                missing = [mod for mod in ("onnxruntime", "tokenizers", "numpy")
                           if importlib.util.find_spec(mod) is None]
                if missing:
                    # 模型就绪但依赖缺失 → route() 会始终返回 None，实为不可用
                    self._router = None
                    logger.warning(
                        "[router] embedding 路由显示就绪，但依赖缺失 %s，实际不可用"
                        "（route() 将始终返回 None）。请运行 "
                        "`pip install 'ethan-agent[embedding]'` 安装依赖。", missing,
                    )
                    return
                self._router = router
                _ROUTER_CACHE[fp] = router
                logger.info(
                    "[router] embedding 路由已激活：模型就绪，可路由 skill %d 个 → %s",
                    len(router._routable), sorted(router._routable),
                )
            else:
                self._router = None
                reason = "模型文件缺失" if not avail else "LR 头不可用或可路由 skill 为空"
                logger.info(
                    "[router] embedding 路由未激活（%s）。available=%s, build=%s。"
                    " 模型首次使用时自动下载，或运行 `ethan router pull` 手动拉取。",
                    reason, avail, built,
                )
        except Exception as e:
            self._router = None
            logger.warning("[router] embedding 路由构建异常，已回退关键词匹配：%s", e)

    def all(self) -> list[Skill]:
        return list(self._skills)

    def get(self, name: str) -> Skill | None:
        for s in self._skills:
            if s.name == name:
                return s
        return None

    def match(self, query: str, channel: str = "", mode: str = "") -> list[Skill]:
        """根据用户输入匹配相关 Skills。

        关键词子串匹配为基础（保 head 精度 + 强拒识）；若语义路由器可用，再补一个
        语义命中（补 tail 召回）。channel 非空时过滤渠道。匹配分两类：
        - 模式专属 skill（skill.modes 非空）：只在所列 mode 生效，且一旦处于该 mode
          就**无条件命中**——用户显式切到该模式即是最强意图信号，不再卡触发词。
          其它模式下完全不出现（零污染）。
        - 通用 skill（skill.modes 为空）：在所有模式可用，按触发词关键词匹配 + 语义补召回。

        skill.modes 里的每一项都经 resolve_mode 归一化为规范 key 再比较，因此外部
        技能作者写别名（如 `modes: legal` 而非 `法律`）也能匹配——消除跨仓库的隐式契约。
        无法识别的 mode 名保持原样（失败安全，不会误落到默认模式造成泄漏）。
        """
        from ethan.core.modes import resolve_mode

        query_lower = query.lower()
        matched = []
        seen = set()
        for skill in self._skills:
            if skill.channels and channel and channel not in skill.channels:
                continue
            if skill.modes:
                # 归一化别名 → 规范 key；无法识别的（resolve 回退默认、key 为空）保留原值，
                # 避免写错的 mode 名被归一成 "" 而误匹配默认模式。
                normalized = {resolve_mode(m).key or m for m in skill.modes}
                if mode in normalized:
                    matched.append(skill)
                continue
            for trigger in skill.trigger:
                if trigger.lower() in query_lower:
                    matched.append(skill)
                    seen.add(skill.name)
                    break

        # embedding 路由补召回：只补「通用 skill」（modes 为空）的 tail 召回。
        # 模式专属 skill 已在上面的 mode 分支完整处理（模式内无条件命中、模式外绝不出现），
        # 这里必须跳过它们——否则普通模式下语义路由可能命中如 legal-assistant，
        # 击穿模式隔离的零污染保证。
        if self._router is not None:
            name = self._router.route(query)
            if name and name not in seen:
                skill = self.get(name)
                if (skill and not skill.modes
                        and not (skill.channels and channel and channel not in skill.channels)):
                    matched.append(skill)
                    logger.info("[router] 语义补召回命中 skill=%s (query=%r)", name, query[:60])
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
            # references 清单追加在截断后的 content 之后，本身不参与 _MAX_SKILL_CONTENT 截断
            refs_block = _build_references_block(skill)
            if refs_block:
                parts.append(f"[Skill: {skill.name}]\n{content}\n\n{refs_block}")
            else:
                parts.append(f"[Skill: {skill.name}]\n{content}")
        return "\n\n".join(parts)
