"""维度注册表 — 结构化记忆维度体系的单一事实源。

extractors 的白名单校验与提取 prompt 的维度段落都从这里生成：

- 新增维度 = 注册表加一行，无需改校验逻辑或手写 prompt
- prompt 由注册表自动生成，保证模型看到的维度与校验白名单严格一致
  （此前 prompt 只列了 ~19/64 维，模型根本不知道其余维度存在——这是
  preference/decision/activity 召回率仅 0.25~0.35 的直接原因；
  companion 域 prompt 最详细所以 R=0.88，本注册表把同等待遇推广到全域）
- 每个 memory_type 带一句"角色定位"（引导模型识别该类记忆），
  每个维度带判别边界 + 正例
- ``custom.*`` 前缀维度不在此表，由 extractors 放行但强制 observed 门槛
  （永不直进 active，留给人工/日结复评）
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DimensionSpec:
    name: str           # 完整维度名（含 memory_type 前缀，如 identity.location）
    memory_type: str
    description: str    # 一句话判别边界（什么算、什么不算）
    example: str = ""   # 正例（prompt 用）
    note: str = ""      # 晋升/保留规则（主要是 companion 域）


@dataclass(frozen=True, slots=True)
class TypeSpec:
    memory_type: str
    role: str           # 角色定位：引导模型识别这类记忆的一句话


TYPE_ROLES: tuple[TypeSpec, ...] = (
    TypeSpec("personal_information", "用户的身份与背景事实（称呼/语言/城市/职业/经历/家庭/长期目标）"),
    TypeSpec("preference", "用户的偏好与厌恶——包括明确说「不喜欢/别这样」的 negative 偏好"),
    TypeSpec("activity", "用户正在进行的事——项目/职责/近期目标/卡点/截止/在等谁/刚完成什么"),
    TypeSpec("decision", "用户的决定——选了什么/放弃了什么/为什么/约束/承诺/共识/期限/改口"),
    TypeSpec("relationship", "与用户长期相关的协作关系与分工"),
    TypeSpec("methodology", "用户做事的方法论——如何定目标、拆问题、找信息、做分析、定标准、做决策、走流程、用工具、协作、控质量、复盘"),
    TypeSpec("companion", "用户的情绪状态与支持需求（仅陪伴模式提取）"),
)


DIMENSIONS: tuple[DimensionSpec, ...] = (
    # ── personal_information（14）──
    DimensionSpec("identity.preferred_name", "personal_information", "希望被称呼的名字/昵称", "「叫我小渔就好」"),
    DimensionSpec("identity.pronouns", "personal_information", "人称代词偏好", "「用‘他’称呼我就行」"),
    DimensionSpec("identity.language", "personal_information", "日常使用的语言", "「平时主要用中文」"),
    DimensionSpec("identity.location", "personal_information", "常驻城市/地区", "「我住在深圳」"),
    DimensionSpec("identity.timezone", "personal_information", "所在时区", "「我这边 UTC+8」"),
    DimensionSpec("identity.occupation", "personal_information", "职业身份", "「我是搜索引擎工程师」"),
    DimensionSpec("identity.role", "personal_information", "当前岗位/职责角色", "「我在团队里负责排序模块」"),
    DimensionSpec("identity.organization", "personal_information", "所在公司/组织", "「我在字节跳动工作」"),
    DimensionSpec("identity.education", "personal_information", "教育背景", "「我硕士学的是计算机」"),
    DimensionSpec("identity.professional_background", "personal_information", "职业经历/过往背景", "「之前在腾讯做了五年搜索」"),
    DimensionSpec("identity.expertise", "personal_information", "专业强项领域", "「最熟的是检索排序」"),
    DimensionSpec("identity.relationship", "personal_information", "家庭/亲密关系状况", "「我有两个孩子」"),
    DimensionSpec("identity.accessibility", "personal_information", "无障碍/特殊需求", "「字号麻烦调大一点」"),
    DimensionSpec("identity.long_term_goal", "personal_information", "长期目标（半年以上）", "「三年内想转管理岗」"),
    # ── preference（11）──
    DimensionSpec("preference.communication", "preference", "沟通方式偏好（怎么表达/汇报）", "「先说结论再展开」"),
    DimensionSpec("preference.language", "preference", "交流语言偏好", "「跟我用中文就行」"),
    DimensionSpec("preference.tone", "preference", "语气偏好", "「别客套，直接说」"),
    DimensionSpec("preference.tools", "preference", "工具/软件偏好", "「主力编辑器是 VS Code」"),
    DimensionSpec("preference.work_habits", "preference", "工作习惯", "「早上先处理最难的事」"),
    DimensionSpec("preference.schedule", "preference", "时间安排偏好", "「别在中午找我开会」"),
    DimensionSpec("preference.content", "preference", "内容形式偏好（格式/图表/详略）", "「给我表格不要长文」"),
    DimensionSpec("preference.decision_tradeoff", "preference", "决策取舍偏好（速度 vs 质量等）", "「宁可慢一天也要测全」"),
    DimensionSpec("preference.boundary", "preference", "不愿被打扰的边界", "「下班时间别发消息」"),
    DimensionSpec("preference.negative", "preference", "明确厌恶/不希望的方式", "「别用敬语，听着难受」"),
    DimensionSpec("preference.response_verbosity", "preference", "回复详略偏好", "「回答简短点」"),
    # ── activity（7）──
    DimensionSpec("activity.project", "activity", "正在做的项目/事项", "「最近在搞 memory 重构」"),
    DimensionSpec("activity.responsibility", "activity", "当前承担的职责", "「这周轮到我 oncall」"),
    DimensionSpec("activity.goal", "activity", "近期目标（本周/本季度）", "「这个季度要把 P95 降下来」"),
    DimensionSpec("activity.blocker", "activity", "当前卡点/阻塞", "「卡在评测数据不够」"),
    DimensionSpec("activity.deadline", "activity", "近期截止", "「周五前要交方案」"),
    DimensionSpec("activity.waiting", "activity", "在等待他人/外部的事", "「等 jason 合 PR」"),
    DimensionSpec("activity.recent_completion", "activity", "刚完成的事", "「昨天刚发完版」"),
    # ── decision（8）──
    DimensionSpec("decision.chosen", "decision", "已做出的选择", "「决定用 SQLite 不引入新组件」"),
    DimensionSpec("decision.rejected", "decision", "明确放弃的选项", "「放弃了自研 embedding 服务」"),
    DimensionSpec("decision.rationale", "decision", "决定背后的理由", "「选它是因为运维成本最低」"),
    DimensionSpec("decision.constraint", "decision", "决定的约束条件", "「预算不能超过每月两百」"),
    DimensionSpec("decision.commitment", "decision", "对他人做出的承诺", "「我答应周五前给结论」"),
    DimensionSpec("decision.agreement", "decision", "双方达成的一致", "「说好先做迁移再优化」"),
    DimensionSpec("decision.deadline", "decision", "决定必须落地的期限", "「下周三前定稿」"),
    DimensionSpec("decision.correction", "decision", "对之前说法/决定的纠正、改口", "「之前说用 A，现在改 B 了」"),
    # ── relationship（3）──
    DimensionSpec("relationship.role", "relationship", "协作对象及其角色", "「jason 是我的合作方」"),
    DimensionSpec("relationship.coordination", "relationship", "与协作对象的分工/协同方式", "「他管 router 我管 memory」"),
    DimensionSpec("relationship.relevance", "relationship", "某人对用户的长期相关性", "「这个客户一直很重要」"),
    # ── methodology（11）──
    DimensionSpec("methodology.goal_framing", "methodology", "如何定义目标/框定问题", "「先定义清楚什么算解决」"),
    DimensionSpec("methodology.problem_decomposition", "methodology", "如何拆解问题", "「按数据流分层拆」"),
    DimensionSpec("methodology.information_gathering", "methodology", "如何收集信息/调研", "「先看日志再猜原因」"),
    DimensionSpec("methodology.analysis_reasoning", "methodology", "如何分析推理", "「用对照实验排除变量」"),
    DimensionSpec("methodology.evaluation_criteria", "methodology", "如何定评估标准", "「以 P/R/F1 为准，不看感觉」"),
    DimensionSpec("methodology.decision_style", "methodology", "如何做决策", "「列出所有选项再逐个排除」"),
    DimensionSpec("methodology.execution_workflow", "methodology", "执行流程/工作流", "「先写测试再实现」"),
    DimensionSpec("methodology.tool_usage", "methodology", "使用工具的方法", "「复杂查询都走 SQL」"),
    DimensionSpec("methodology.communication_collaboration", "methodology", "协作沟通方法", "「结论先同步群里再细聊」"),
    DimensionSpec("methodology.quality_control", "methodology", "质量控制方法", "「每次改动必须跑全量测试」"),
    DimensionSpec("methodology.reflection_improvement", "methodology", "复盘改进方法", "「每周五复盘一次」"),
    # ── companion（10，仅陪伴模式）──
    DimensionSpec("companion.current_emotion", "companion", "当前情绪：用户明确说出的当前感受、强度和时间", "「最近因为发布延期感到焦虑」", "In-episode/带 TTL，默认不晋升稳定特征"),
    DimensionSpec("companion.emotional_event", "companion", "情绪事件：引发感受的具体事件及必要上下文", "「评审中的否定让用户感到挫败」", "作为历史情节保留、不泛化人格"),
    DimensionSpec("companion.current_stressor", "companion", "压力源/困扰：明确、重复出现的压力源或担忧", "「不确定的截止时间会持续带来压力」", "用户明确说明长期存在或多次重复才晋升"),
    DimensionSpec("companion.support_need", "companion", "当下支持需求：希望被倾听、澄清、陪伴还是获得建议", "「这次只想说说，不需要方案」", "仅用户明确说「以后这种情况……」才晋升"),
    DimensionSpec("companion.soothing_preference", "companion", "安抚偏好：哪些回应方式确实有帮助或令人不适", "「先确认感受再讨论方案会更舒服」", "用户明确评价或纠正才确认"),
    DimensionSpec("companion.support_boundary", "companion", "情感边界：用户不希望讨论、追问或使用的表达方式", "「不希望被追问家庭细节」", "用户明确设定边界"),
    DimensionSpec("companion.explicit_value", "companion", "价值/意义：用户明确表达的重要价值、信念或内心意义", "「用户很看重自主选择」", "必须用户直接陈述，高敏感可要求确认"),
    DimensionSpec("companion.important_inner_experience", "companion", "重要内心经历：对用户有长期影响的内心经历或体验", "「第一次被裁让用户很久不敢放松」"),
    DimensionSpec("companion.relationship_context", "companion", "关系上下文：与当前困扰长期相关的人和关系", "「某位同事是当前项目合作方」", "仅保存服务所需最小信息"),
    DimensionSpec("companion.requested_follow_up", "companion", "后续跟进请求：用户明确拜托后续记挂/回访的事", "「下周问问我发版顺不顺利」"),
)

_BY_TYPE: dict[str, list[DimensionSpec]] = {}
for _spec in DIMENSIONS:
    _BY_TYPE.setdefault(_spec.memory_type, []).append(_spec)

_ROLE_BY_TYPE = {t.memory_type: t.role for t in TYPE_ROLES}

CUSTOM_PREFIX = "custom."


def valid_dimensions(memory_type: str) -> set[str]:
    """该 memory_type 的合法维度集合（白名单校验用）。"""
    return {spec.name for spec in _BY_TYPE.get(memory_type, [])}


def known_memory_types() -> set[str]:
    return set(_BY_TYPE)


def build_dimension_prompt(*, is_companion: bool) -> str:
    """由注册表生成提取 prompt 的维度段落。

    非陪伴模式：6 个 general 类型全部列出（含逐维判别边界+正例），
    并明确禁止 companion 维度。陪伴模式：追加 companion 段（含晋升规则）。
    """
    sections: list[str] = []
    for type_spec in TYPE_ROLES:
        memory_type = type_spec.memory_type
        if memory_type == "companion" and not is_companion:
            continue
        specs = _BY_TYPE.get(memory_type, [])
        if not specs:
            continue
        lines = [f"【{memory_type}】{type_spec.role}"]
        for spec in specs:
            line = f"- {spec.name}：{spec.description}"
            if spec.note:
                line += f"（{spec.note}）"
            if spec.example:
                line += f" 示例:{spec.example}"
            lines.append(line)
        if memory_type == "methodology":
            lines.append(
                "methodology 候选的 structured 必含 scenario(什么场景),trigger(何时触发),"
                "steps(怎么做),heuristics,evaluation_criteria,anti_patterns。"
            )
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
