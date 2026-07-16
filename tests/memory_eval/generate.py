"""Memory eval — 确定性样本生成器。

产出 data/extraction.jsonl 与 data/recall.jsonl，每领域 200 条。
固定 seed 可复现。运行：uv run python tests/memory_eval/generate.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SEED = 20260716

DOMAINS = [
    "personal_information",
    "preference",
    "methodology",
    "activity",
    "decision",
    "companion",
]
PER_DOMAIN = 200

# ── 填充池 ────────────────────────────────────────────────────────────────
NAMES = ["小明", "Calvin", "阿岚", "小满", "Jin", "阿伟", "小桐", "Ethan", "阿哲", "小渔",
         "志远", "Maya", "阿宁", "Leo", "小棠", "Iris", "阿凯", "Noah", "小禾", "Aria"]
GENDERS = ["男", "女", "非二元"]
AGES = [22, 25, 28, 31, 34, 37, 40, 45]
MBTIS = ["INTJ", "INFP", "ENTP", "ISTJ", "ENFJ", "ISTP", "INTP", "ESFP"]
INTERESTS = ["Agent", "检索系统", "量化交易", "摄影", "爬虫", "翻译", "桌游",
             "马拉松", "古典乐", "神经科学", "Rust", "机器学习", "登山", "烘焙", "区块链"]
LANGUAGES = ["中文", "English", "日語", "中英混用"]
TIMEZONES = ["Asia/Shanghai", "UTC+8", "America/New_York", "Europe/London"]
LOCATIONS = ["上海", "深圳", "杭州", "北京", "新加坡", "旧金山", "成都", "西雅图"]
EDUCATIONS = ["计算机硕士", "本科", "博士", "自学", "MBA", "统计学本科"]
RELATIONS = ["已婚", "单身", "和室友合租", "养了一只猫", "有两个孩子"]

OCCUPATIONS = ["搜索引擎工程师", "算法工程师", "产品经理", "独立开发者", "研究员",
               "数据科学家", "后端工程师", "创业公司 CTO", "量化研究员", "ML 工程师"]
RESEARCH = ["主动学习", "排序学习", "RAG", "多模态检索", "Agent 工具调用",
            "知识图谱", "对齐", "小样本学习", "图神经网络", "推荐系统"]

COMMS = ["先给结论再给证据", "可以用同行术语", "直接说问题别铺垫",
         "分点列清楚", "少用形容词多用数字"]
TRADEOFFS = ["没实测前偏好简单方案", "优先可回滚的低风险路径", "能用现成库就不自己造",
             "性能和可读性冲突时先可读", "延迟优先于功能丰富度"]
NEGATIVES = ["不要把推断写成已验证结论", "不接受没有 baseline 的性能主张",
             "别一上来就重构", "不要用 emoji", "别在正文里贴大段代码"]
TOOLS = ["Cursor", "VS Code", "Neovim", "JetBrains", "Vim"]
SCHEDULES = ["夜猫子", "早起型", "下午效率最高", "周末集中编码"]
BOUNDARIES = ["别追问家庭细节", "不要主动给心理建议", "技术讨论别扯到个人",
              "不要在回复里夹问候语"]
VERBOSITIES = ["简洁", "详细展开", "中等"]

METHOD_TRIGGER = ["比较技术方案", "读论文", "debug 复现", "做技术规划", "code review"]
METHOD_STEPS = {
    "比较技术方案": ["定义指标", "建评测集", "跑实验", "分析失败样例", "下结论"],
    "读论文": ["先看 claim", "看实验设置", "看 baseline", "看失败案例"],
    "debug 复现": ["最小复现", "二分定位", "看日志", "加断言"],
    "做技术规划": ["拆里程碑", "定验收", "估风险", "排优先级"],
    "code review": ["先看语义", "再看边界", "看测试覆盖", "看命名"],
}
METHODOLOGY = [
    ("methodology.evidence_standard", "技术主张必须用固定评测集验证，理论分析只算候选"),
    ("methodology.decision_process", "比较方案要先列淘汰依据再推荐"),
    ("methodology.information_source", "优先看一手源码和论文，二手博客只做线索"),
    ("methodology.complexity_management", "默认最小可验证方案，复杂度要有收益证明"),
    ("methodology.execution_strategy", "按 P0/P1 分阶段推进，每阶段有验收"),
]

GOALS = ["做出能长期理解用户的个人 Agent", "把检索准确率提到 SOTA",
         "半年内上线一个量化策略", "读透 30 篇 RAG 论文", "把产品做到 1k DAU"]
PROJECTS = ["Ethan Agent", "检索中台重构", "量化回测平台", "论文复现库", "个人知识库"]
FOCUSES = ["结构化记忆和每日压缩", "做多路召回", "压测延迟", "补端到端测试", "迁移到新 embedding"]
DEADLINES = ["本周五", "月底", "下周二", "Q3 结束前", "这周末"]
BLOCKERS = ["等数据权限审批", "评测集还没标注完", "依赖服务没就绪", "GPU 排队中"]
COMPLETIONS = ["刚把召回接进主循环", "做完每日压缩幂等", "修了 companion 泄漏", "发了 v0.5"]

DECISIONS_CHOSEN = ["决定先不引入 Episode", "选了 SQLite 存记忆", "用 lite model 做压缩",
                    "召回按 domain 隔离 companion"]
DECISIONS_REJECTED = ["否掉了向量单独判冲突", "放弃了七阶段状态机", "不做知识图谱"]
DECISIONS_RATIONALE = ["当前目标不依赖 Episode，复杂度收益不足", "SQLite 够用且可审计",
                       "embedding 相似不能单独决定 supersede"]
COMMITMENTS = ["这周把测试补齐", "明天给你 review", "下周补文档"]

EMOTIONS = ["焦虑", "挫败", "有点低落", "踏实", "兴奋"]
STRESSORS = ["发布延期", "评审被否定", "截止不确定", "需求反复变更"]
SOOTHING = ["这次只想被听见，不用给方案", "先确认我的感受再讨论", "陪我吐槽就好"]
SUPPORT_BOUNDARY = ["别追问家庭", "不要给心理诊断", "技术问题别扯情绪"]
VALUES = ["把事情做扎实比快重要", "诚实标注不确定性"]
DIAGNOSTIC_SENTENCES = [
    "我最近是不是抑郁了", "我可能是焦虑症", "这算不算创伤后反应",
    "我是不是依恋类型有问题", "会不会是双相",
]

# ── 场景构造器 ────────────────────────────────────────────────────────────
def _q(text: str) -> str:
    """extractor 要求 quote 是 user content 的精确子串；这里直接拿原句。"""
    return text


def ext_personal(rng, idx):
    """个人信息：含性别/年龄/MBTI/兴趣/称呼/语言/时区/常住地/教育/关系。"""
    name = rng.choice(NAMES)
    gender = rng.choice(GENDERS)
    age = rng.choice(AGES)
    mbti = rng.choice(MBTIS)
    interest = rng.choice(INTERESTS)
    occ = rng.choice(OCCUPATIONS)
    research = rng.choice(RESEARCH)
    lang = rng.choice(LANGUAGES)
    tz = rng.choice(TIMEZONES)
    loc = rng.choice(LOCATIONS)
    edu = rng.choice(EDUCATIONS)
    rel = rng.choice(RELATIONS)
    scenario = rng.choice(["single_explicit", "multi_fact_one_turn", "noise", "correction"])

    expected, messages = [], []
    if scenario == "single_explicit":
        c = f"你就叫我{name}吧。"
        messages.append({"id": 1, "role": "user", "content": c})
        expected.append(_personal_expected("identity.preferred_name", f"用户希望被叫做{name}",
                                           "explicit", _q(c), 1))
    elif scenario == "multi_fact_one_turn":
        c = (f"我叫{name}，{gender}，{age}岁，MBTI 是 {mbti}。"
             f"我做{occ}，研究方向是{research}。平时用{lang}，时区{tz}，人在{loc}。"
             f"学历{edu}，目前{rel}，一直对{interest}很感兴趣。")
        messages.append({"id": 1, "role": "user", "content": c})
        expected += [
            _personal_expected("identity.preferred_name", f"用户叫{name}", "explicit", "我叫" + name, 1),
            _personal_expected("identity.occupation", f"用户职业是{occ}", "explicit", f"我做{occ}", 1),
            _personal_expected("identity.expertise", f"用户研究方向是{research}", "explicit", f"研究方向是{research}", 1),
            _personal_expected("identity.language", f"用户使用{lang}", "explicit", f"平时用{lang}", 1),
            _personal_expected("identity.timezone", f"用户时区{tz}", "explicit", f"时区{tz}", 1),
            _personal_expected("identity.location", f"用户常住{loc}", "explicit", f"人在{loc}", 1),
            _personal_expected("identity.education", f"用户学历{edu}", "explicit", f"学历{edu}", 1),
            _personal_expected("identity.long_term_goal", f"用户长期兴趣是{interest}", "explicit", f"对{interest}很感兴趣", 1),
        ]
        # gap 维度：性别/年龄/MBTI
        expected += [
            _personal_expected("identity.gender", f"用户性别{gender}", "explicit", gender, 1, gap=True),
            _personal_expected("identity.age", f"用户年龄{age}", "explicit", f"{age}岁", 1, gap=True),
            _personal_expected("identity.mbti", f"用户 MBTI {mbti}", "explicit", f"MBTI 是 {mbti}", 1, gap=True),
        ]
    elif scenario == "noise":
        c = f"哈哈今天天气不错。对了叫我{name}，我是做{occ}的。那个 bug 你看了吗？"
        messages.append({"id": 1, "role": "user", "content": c})
        messages.append({"id": 2, "role": "assistant", "content": "看了，是空指针。"})
        expected += [
            _personal_expected("identity.preferred_name", f"用户叫{name}", "explicit", "叫我" + name, 1),
            _personal_expected("identity.occupation", f"用户职业{occ}", "explicit", f"做{occ}的", 1),
        ]
    else:  # correction
        c1 = f"叫我{name}吧。"
        messages.append({"id": 1, "role": "user", "content": c1})
        messages.append({"id": 2, "role": "assistant", "content": f"好的{name}。"})
        c3 = f"其实别叫{name}了，叫我 Calvin 吧。"
        messages.append({"id": 3, "role": "user", "content": c3})
        expected.append(_personal_expected("identity.preferred_name", "用户希望被叫做 Calvin",
                                           "corrected", _q(c3), 3))
    return _ext_case("ext_personal", idx, scenario, "", messages, expected)


def ext_preference(rng, idx):
    kind = rng.choice(["single_explicit", "negative_pref", "multi_fact_one_turn", "noise"])
    comm = rng.choice(COMMS)
    trade = rng.choice(TRADEOFFS)
    neg = rng.choice(NEGATIVES)
    tool = rng.choice(TOOLS)
    sched = rng.choice(SCHEDULES)
    boundary = rng.choice(BOUNDARIES)
    verb = rng.choice(VERBOSITIES)
    expected, messages = [], []
    if kind == "single_explicit":
        c = f"回复的时候{comm}。"
        messages.append({"id": 1, "role": "user", "content": c})
        expected.append(_pref_expected("preference.communication", f"用户偏好{comm}", "explicit", _q(comm), 1))
    elif kind == "negative_pref":
        c = f"记住，{neg}。"
        messages.append({"id": 1, "role": "user", "content": c})
        expected.append(_pref_expected("preference.negative", f"用户不接受：{neg}", "explicit", _q(neg), 1))
    elif kind == "multi_fact_one_turn":
        c = (f"几个偏好你记下：{comm}；{trade}；{neg}；编辑器我用{tool}；"
             f"我是{sched}；{boundary}；回复{verb}一点。")
        messages.append({"id": 1, "role": "user", "content": c})
        expected += [
            _pref_expected("preference.communication", f"用户偏好{comm}", "explicit", _q(comm), 1),
            _pref_expected("preference.decision_tradeoff", f"用户方案偏好：{trade}", "explicit", _q(trade), 1),
            _pref_expected("preference.negative", f"用户不接受：{neg}", "explicit", _q(neg), 1),
            _pref_expected("preference.tools", f"用户用{tool}", "explicit", f"编辑器我用{tool}", 1),
            _pref_expected("preference.schedule", f"用户作息{sched}", "explicit", f"我是{sched}", 1),
            _pref_expected("preference.boundary", f"用户边界：{boundary}", "explicit", _q(boundary), 1),
            _pref_expected("preference.response_verbosity", f"用户偏好{verb}", "explicit", f"回复{verb}一点", 1),
        ]
    else:
        c = f"随便聊聊。哦对了，{comm}，还有{neg}。"
        messages.append({"id": 1, "role": "user", "content": c})
        messages.append({"id": 2, "role": "assistant", "content": "收到。"})
        expected += [
            _pref_expected("preference.communication", f"用户偏好{comm}", "explicit", _q(comm), 1),
            _pref_expected("preference.negative", f"用户不接受：{neg}", "explicit", _q(neg), 1),
        ]
    return _ext_case("ext_pref", idx, kind, "", messages, expected)


def ext_methodology(rng, idx):
    trigger = rng.choice(METHOD_TRIGGER)
    steps = METHOD_STEPS[trigger]
    dim, content = rng.choice(METHODOLOGY)
    kind = rng.choice(["single_explicit", "observed_single", "observed_repeat"])
    expected, messages = [], []
    if kind == "single_explicit":
        c = f"我做技术决策时，{content}。比如{trigger}的时候，我会按这个顺序：{'，'.join(steps)}。"
        messages.append({"id": 1, "role": "user", "content": c})
        expected.append(_method_expected(dim, content, "explicit", trigger, steps, _q(content), 1))
    elif kind == "observed_single":
        c = f"这个方案先别定，我得先{steps[0]}再说。"
        messages.append({"id": 1, "role": "user", "content": c})
        expected.append(_method_expected(dim, content, "observed", trigger, steps, _q(steps[0]), 1,
                                         note="observed 单 session 不应晋升 active"))
    else:  # repeat across sessions
        c1 = f"比较方案别急着定，先{steps[0]}。"
        messages.append({"id": 1, "role": "user", "content": c1})
        messages.append({"id": 2, "role": "assistant", "content": "明白。"})
        c3 = f"对，还是那个习惯，{trigger}必须先{steps[0]}。"
        messages.append({"id": 3, "role": "user", "content": c3})
        expected.append(_method_expected(dim, content, "inferred", trigger, steps, _q(steps[0]), 3,
                                         note="observed 跨 2 session 升 active+inferred"))
    return _ext_case("ext_method", idx, kind, "", messages, expected)


def ext_activity(rng, idx):
    goal = rng.choice(GOALS)
    project = rng.choice(PROJECTS)
    focus = rng.choice(FOCUSES)
    deadline = rng.choice(DEADLINES)
    blocker = rng.choice(BLOCKERS)
    completion = rng.choice(COMPLETIONS)
    occ = rng.choice(OCCUPATIONS)
    kind = rng.choice(["single_explicit", "multi_fact_one_turn", "observed_single"])
    expected, messages = [], []
    if kind == "single_explicit":
        c = f"我现在的长期目标是{goal}。"
        messages.append({"id": 1, "role": "user", "content": c})
        expected.append(_activity_expected("activity.goal", f"用户长期目标：{goal}", "explicit", _q(goal), 1))
    elif kind == "multi_fact_one_turn":
        c = (f"我在做{project}，当前重点是{focus}。我本身是{occ}。"
             f"这个阶段{deadline}得到个里程碑，现在卡在{blocker}，不过刚{completion}。")
        messages.append({"id": 1, "role": "user", "content": c})
        expected += [
            _activity_expected("activity.project", f"用户在做{project}", "explicit", f"做{project}", 1),
            _activity_expected("activity.current_focus", f"用户当前焦点：{focus}", "explicit", f"重点是{focus}", 1),
            _activity_expected("activity.deadline", f"用户截止：{deadline}", "explicit", f"{deadline}得到个里程碑", 1),
            _activity_expected("activity.blocker", f"用户阻塞：{blocker}", "explicit", f"卡在{blocker}", 1),
            _activity_expected("activity.recent_completion", f"用户近期完成：{completion}", "explicit", f"刚{completion}", 1),
        ]
    else:
        c = f"今天主要在搞{focus}。"
        messages.append({"id": 1, "role": "user", "content": c})
        expected.append(_activity_expected("activity.current_focus", f"用户当前焦点：{focus}", "observed", _q(focus), 1,
                                           note="observed 单 session"))
    return _ext_case("ext_activity", idx, kind, "", messages, expected)


def ext_decision(rng, idx):
    chosen = rng.choice(DECISIONS_CHOSEN)
    rejected = rng.choice(DECISIONS_REJECTED)
    rationale = rng.choice(DECISIONS_RATIONALE)
    commit = rng.choice(COMMITMENTS)
    kind = rng.choice(["single_explicit", "multi_fact_one_turn", "assistant_unconfirmed"])
    expected, messages = [], []
    if kind == "single_explicit":
        c = f"我决定{chosen}，理由是{rationale}。"
        messages.append({"id": 1, "role": "user", "content": c})
        expected.append(_decision_expected("decision.chosen", f"用户决定：{chosen}", "explicit", _q(chosen), 1))
        expected.append(_decision_expected("decision.rationale", f"理由：{rationale}", "explicit", _q(rationale), 1))
    elif kind == "multi_fact_one_turn":
        c = f"技术决定记一下：{chosen}，因为{rationale}；另外{rejected}；我承诺{commit}。"
        messages.append({"id": 1, "role": "user", "content": c})
        expected += [
            _decision_expected("decision.chosen", f"用户决定：{chosen}", "explicit", _q(chosen), 1),
            _decision_expected("decision.rationale", f"理由：{rationale}", "explicit", _q(rationale), 1),
            _decision_expected("decision.rejected", f"用户否决：{rejected}", "explicit", _q(rejected), 1),
            _decision_expected("decision.commitment", f"用户承诺：{commit}", "explicit", _q(commit), 1),
        ]
    else:  # assistant_unconfirmed: 助手提议，用户没确认 → 不应写入
        messages.append({"id": 1, "role": "user", "content": "这个架构你怎么看？"})
        messages.append({"id": 2, "role": "assistant", "content": f"我建议{chosen}，理由是{rationale}。"})
        messages.append({"id": 3, "role": "user", "content": "嗯我再想想。"})
        expected.append(_decision_expected("decision.chosen", "（不应写入：助手提议未获确认）", "explicit",
                                           "嗯我再想想", 3, note="assistant_unconfirmed 负样本，预期 NOOP"))
    return _ext_case("ext_decision", idx, kind, "", messages, expected)


def ext_companion(rng, idx):
    emotion = rng.choice(EMOTIONS)
    stressor = rng.choice(STRESSORS)
    soothing = rng.choice(SOOTHING)
    boundary = rng.choice(SUPPORT_BOUNDARY)
    value = rng.choice(VALUES)
    kind = rng.choice(["companion_leak", "diagnostic_reject", "single_explicit", "multi_fact_one_turn"])
    expected, messages = [], []
    if kind == "companion_leak":
        # 非苏念模式出现情绪 → 零 companion 提取
        c = f"最近因为{stressor}有点{emotion}。"
        messages.append({"id": 1, "role": "user", "content": c})
        return _ext_case("ext_companion", idx, kind, "", messages, [],
                         note="companion_leak: mode='' 预期零 companion 提取")
    if kind == "diagnostic_reject":
        c = rng.choice(DIAGNOSTIC_SENTENCES)
        messages.append({"id": 1, "role": "user", "content": c})
        return _ext_case("ext_companion", idx, kind, "companion", messages, [],
                         note="diagnostic_reject: 诊断词必须被拒")
    if kind == "single_explicit":
        c = f"这次我有点{emotion}，因为{stressor}。{soothing}。"
        messages.append({"id": 1, "role": "user", "content": c})
        expected.append(_companion_expected("companion.current_emotion", f"用户当前情绪{emotion}", "explicit", _q(emotion), 1))
        expected.append(_companion_expected("companion.current_stressor", f"压力源：{stressor}", "explicit", _q(stressor), 1))
        expected.append(_companion_expected("companion.soothing_preference", f"支持偏好：{soothing}", "explicit", _q(soothing), 1))
    else:
        c = f"我有点{emotion}，{stressor}让我压力很大。{soothing}。另外{boundary}。{value}。"
        messages.append({"id": 1, "role": "user", "content": c})
        expected += [
            _companion_expected("companion.current_emotion", f"用户当前情绪{emotion}", "explicit", _q(emotion), 1),
            _companion_expected("companion.current_stressor", f"压力源：{stressor}", "explicit", _q(stressor), 1),
            _companion_expected("companion.soothing_preference", f"支持偏好：{soothing}", "explicit", _q(soothing), 1),
            _companion_expected("companion.support_boundary", f"边界：{boundary}", "explicit", _q(boundary), 1),
            _companion_expected("companion.explicit_value", f"价值：{value}", "explicit", _q(value), 1),
        ]
    return _ext_case("ext_companion", idx, kind, "companion", messages, expected)


# ── expected 构造 ─────────────────────────────────────────────────────────
def _personal_expected(dim, content, level, quote, mid, gap=False):
    return _exp("personal_information", dim, content, level, quote, mid, gap=gap)

def _pref_expected(dim, content, level, quote, mid):
    return _exp("preference", dim, content, level, quote, mid)

def _method_expected(dim, content, level, trigger, steps, quote, mid, note=""):
    e = _exp("methodology", dim, content, level, quote, mid)
    e["structured"] = {"scenario": "technical", "trigger": trigger, "steps": steps,
                       "heuristics": [], "preferred_tools": [], "evaluation_criteria": [],
                       "anti_patterns": [], "exceptions": []}
    e["note"] = note
    return e

def _activity_expected(dim, content, level, quote, mid, note=""):
    return _exp("activity", dim, content, level, quote, mid, note=note)

def _decision_expected(dim, content, level, quote, mid, note=""):
    return _exp("decision", dim, content, level, quote, mid, note=note)

def _companion_expected(dim, content, level, quote, mid):
    return _exp("companion", dim, content, level, quote, mid)

def _exp(mtype, dim, content, level, quote, mid, gap=False, note=""):
    return {
        "memory_type": mtype, "dimension": dim, "memory_key": dim,
        "content": content, "evidence_level": level,
        "scope_type": "mode" if mtype == "companion" else "user",
        "scope_id": "companion" if mtype == "companion" else "self",
        "quote": quote, "message_id": mid, "gap_dimension": gap, "note": note,
    }

def _ext_case(prefix, idx, scenario, mode, messages, expected, note=""):
    return {
        "id": f"{prefix}_{idx:04d}",
        "domain": prefix.replace("ext_", ""),
        "kind": "extraction",
        "scenario": scenario,
        "mode": mode,
        "messages": messages,
        "expected": expected,
        "forbidden_domains": [] if mode == "companion" else ["companion"],
        "note": note,
    }


# ── recall 样本 ───────────────────────────────────────────────────────────
def rec_personal(rng, idx):
    name = rng.choice(NAMES); occ = rng.choice(OCCUPATIONS); research = rng.choice(RESEARCH)
    seed = [
        {"memory_type": "personal_information", "dimension": "identity.preferred_name",
         "memory_key": "identity.preferred_name", "content": f"用户叫{name}",
         "status": "active", "memory_domain": "general", "sensitivity": "normal"},
        {"memory_type": "personal_information", "dimension": "identity.occupation",
         "memory_key": "identity.occupation", "content": f"用户是{occ}",
         "status": "active", "memory_domain": "general", "sensitivity": "normal"},
        {"memory_type": "personal_information", "dimension": "identity.expertise",
         "memory_key": "identity.expertise", "content": f"研究方向{research}",
         "status": "active", "memory_domain": "general", "sensitivity": "normal"},
    ]
    return _rec_case("rec_personal", idx, "", seed, "你还记得我是谁吗，做什么的？",
                     ["identity.preferred_name", "identity.occupation", "identity.expertise"],
                     ["焦虑", "抑郁"])

def rec_preference(rng, idx):
    comm = rng.choice(COMMS); neg = rng.choice(NEGATIVES)
    seed = [
        {"memory_type": "preference", "dimension": "preference.communication",
         "memory_key": "preference.communication", "content": f"偏好{comm}",
         "status": "active", "memory_domain": "general", "sensitivity": "normal"},
        {"memory_type": "preference", "dimension": "preference.negative",
         "memory_key": "preference.negative", "content": f"不接受：{neg}",
         "status": "active", "memory_domain": "general", "sensitivity": "normal"},
    ]
    return _rec_case("rec_pref", idx, "", seed, "回答的时候要注意什么",
                     ["preference.communication", "preference.negative"], ["焦虑"])

def rec_methodology(rng, idx):
    dim, content = rng.choice(METHODOLOGY)
    seed = [
        {"memory_type": "methodology", "dimension": dim, "memory_key": dim,
         "content": content, "status": "active", "memory_domain": "general", "sensitivity": "normal"},
    ]
    return _rec_case("rec_method", idx, "", seed, "技术方案该怎么比较",
                     [dim], ["焦虑"])

def rec_activity(rng, idx):
    focus = rng.choice(FOCUSES); project = rng.choice(PROJECTS)
    seed = [
        {"memory_type": "activity", "dimension": "activity.current_focus",
         "memory_key": "activity.current_focus", "content": f"当前焦点{focus}",
         "status": "active", "memory_domain": "general", "sensitivity": "normal"},
        {"memory_type": "activity", "dimension": "activity.project",
         "memory_key": "activity.project", "content": f"在做{project}",
         "status": "active", "memory_domain": "general", "sensitivity": "normal"},
    ]
    return _rec_case("rec_activity", idx, "", seed, "我最近在忙什么",
                     ["activity.current_focus", "activity.project"], ["焦虑"])

def rec_decision(rng, idx):
    chosen = rng.choice(DECISIONS_CHOSEN)
    seed = [
        {"memory_type": "decision", "dimension": "decision.chosen",
         "memory_key": "decision.chosen", "content": f"决定{chosen}",
         "status": "active", "memory_domain": "general", "sensitivity": "normal"},
    ]
    return _rec_case("rec_decision", idx, "", seed, "之前那个技术决定是什么",
                     ["decision.chosen"], ["焦虑"])

def rec_companion(rng, idx):
    emotion = rng.choice(EMOTIONS); stressor = rng.choice(STRESSORS)
    seed_general = [
        {"memory_type": "personal_information", "dimension": "identity.preferred_name",
         "memory_key": "identity.preferred_name", "content": "用户叫小明",
         "status": "active", "memory_domain": "general", "sensitivity": "normal"},
    ]
    seed_companion = [
        {"memory_type": "companion", "dimension": "companion.current_emotion",
         "memory_key": "companion.current_emotion", "content": f"用户当前情绪{emotion}",
         "status": "active", "memory_domain": "companion", "sensitivity": "sensitive"},
        {"memory_type": "companion", "dimension": "companion.current_stressor",
         "memory_key": "companion.current_stressor", "content": f"压力源{stressor}",
         "status": "active", "memory_domain": "companion", "sensitivity": "sensitive"},
    ]
    # 普通模式：query 命中 general，但 companion 不得出现
    c1 = _rec_case("rec_companion", idx, "", seed_general + seed_companion, "你还记得我叫什么",
                   ["identity.preferred_name"], [emotion, stressor])
    c1["id"] = f"rec_companion_{idx:04d}"
    c1["note"] = "普通模式不得召回 companion"
    # 苏念模式：companion 应召回
    c2 = _rec_case("rec_companion", idx + 10000, "companion", seed_general + seed_companion,
                   "我上次跟你说我怎么了", ["companion.current_emotion", "companion.current_stressor"], [])
    c2["id"] = f"rec_companion_comp_{idx:04d}"
    c2["note"] = "苏念模式应召回 companion"
    return [c1, c2]

def _rec_case(prefix, idx, mode, seed, query, expected_keys, must_not):
    return {
        "id": f"{prefix}_{idx:04d}",
        "domain": prefix.replace("rec_", ""),
        "kind": "recall",
        "mode": mode,
        "seed_memories": seed,
        "query": query,
        "expected_keys": expected_keys,
        "must_not_contain": must_not,
    }


# ── 主流程 ────────────────────────────────────────────────────────────────
EXT_BUILDERS = {
    "personal_information": ext_personal,
    "preference": ext_preference,
    "methodology": ext_methodology,
    "activity": ext_activity,
    "decision": ext_decision,
    "companion": ext_companion,
}
REC_BUILDERS = {
    "personal_information": rec_personal,
    "preference": rec_preference,
    "methodology": rec_methodology,
    "activity": rec_activity,
    "decision": rec_decision,
    "companion": rec_companion,
}


def main() -> None:
    rng = random.Random(SEED)
    DATA.mkdir(exist_ok=True)
    ext_rows, rec_rows = [], []
    for domain in DOMAINS:
        for i in range(PER_DOMAIN):
            ext_rows.append(EXT_BUILDERS[domain](rng, i))
            out = REC_BUILDERS[domain](rng, i)
            rec_rows.extend(out if isinstance(out, list) else [out])
    # companion builder returns 2 per call → trim/补齐到 PER_DOMAIN
    rec_rows = _balance(rec_rows, PER_DOMAIN, DOMAINS, rng)

    with (DATA / "extraction.jsonl").open("w", encoding="utf-8") as f:
        for r in ext_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (DATA / "recall.jsonl").open("w", encoding="utf-8") as f:
        for r in rec_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_domain = {}
    for r in ext_rows:
        by_domain[r["domain"]] = by_domain.get(r["domain"], 0) + 1
    print(f"extraction: {len(ext_rows)} cases")
    for d, n in sorted(by_domain.items()):
        print(f"  {d}: {n}")
    by_domain = {}
    for r in rec_rows:
        by_domain[r["domain"]] = by_domain.get(r["domain"], 0) + 1
    print(f"recall:     {len(rec_rows)} cases")
    for d, n in sorted(by_domain.items()):
        print(f"  {d}: {n}")


def _balance(rows, per_domain, domains, rng):
    """每领域凑齐 per_domain 条 recall（companion 2:1 产出，截断补齐）。"""
    out = []
    for d in domains:
        sub = [r for r in rows if r["domain"] == d]
        if len(sub) >= per_domain:
            out.extend(sub[:per_domain])
        elif sub:
            out.extend(sub)
            # 不足则复制改 id（保持规模，标注 duplicate）
            for k in range(per_domain - len(sub)):
                base = json.loads(json.dumps(sub[k % len(sub)], ensure_ascii=False))
                base["id"] = f"rec_{d}_{per_domain + k:04d}"
                base["duplicate"] = True
                out.append(base)
        # sub 为空则跳过（该领域无样本，不应发生）
    return out


if __name__ == "__main__":
    main()
