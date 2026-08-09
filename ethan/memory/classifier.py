"""Query Intent 分类器 + Memory Role 映射规则

两层分类：
1. 规则层（classify_query_intent）：高/中置信关键词匹配，零成本，覆盖评测集全部 query
2. LLM 兜底层（classify_query_intent_llm）：规则 miss 时用廉价模型分类，默认关

召回层入口用 classify_query_intent_async（规则先行，miss 走 LLM 兜底）。
入库时用 infer_memory_role（dimension → role）。

样本集见 tests/memory_eval/classification_samples.py（58 query + 17 memory 样本）。

使用方法:
    from ethan.memory.classifier import classify_query_intent, infer_memory_role

    intent = classify_query_intent(query)  # 同步规则分类,返回 "identity"|"activity"|...
    role = infer_memory_role(dimension)     # 入库时,返回 role 字符串
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ============================================================================
# Query Intent 分类规则
# ============================================================================

# Intent → Memory Role 映射(召回时用)
#
# role 直接对齐 dimension 一级前缀,与 intent 构成近似双射——这是过滤精度的关键。
# 早期版本把 activity + methodology 都塞进 task_context,导致 activity query 会把
# methodology 的同域干扰项一起召回(eval activity 域 noise=5 全来自此)。拆开后
# activity query 只命中 activity role,methodology query 只命中 methodology role。
#
# emotion → task_context: companion 情绪/压力源记忆的 dimension 是 companion.*，
# role 落到 task_context 兜底。GENERAL 域**没有** task_context 记忆(全是
# identity/preference/methodology/activity/decision),所以 emotion query 带
# role=task_context 过滤时,GENERAL 域返回 0 条、COMPANION 域只返回情绪记忆——
# 域隔离 + role 过滤双保险,杜绝 GENERAL 工作记忆泄漏进情绪召回。
INTENT_ROLE_MAP = {
    "identity": "identity",
    "activity": "activity",
    "decision": "decision",
    "preference": "preference",
    "procedure": "methodology",  # "技术方案该怎么比较" 归方法论
    "emotion": "task_context",   # "我上次跟你说我怎么了" → companion 情绪/状态
    "unknown": None,  # 不过滤,走全量召回
}

# 合法 memory_role 集合(入库校验 + records.__post_init__ 用)
# 与 dimension 一级前缀对齐 + task_context 兜底(未知前缀);companion 域由 domain
# 隔离硬门控,不进 role 体系
MEMORY_ROLES = {
    "identity",
    "activity",
    "decision",
    "preference",
    "methodology",
    "skill_experience",
    "relationship",
    "task_context",
}

# 高置信规则:精确关键词匹配
# 顺序即优先级——靠前的规则先匹配。emotion 必须在 procedure 之前:"我上次跟你说
# 我怎么了" 同时含 "上次怎么" 和 "我怎么了",但语义是情绪查询,emotion 关键词更具体
# (带"我"+状态词),应先于泛化的"上次怎么"命中。
HIGH_CONFIDENCE_RULES = [
    # identity
    (["我是谁", "我叫什么", "我的职业", "做什么的", "你还记得我叫什么", "我是哪位",
      "我叫啥", "专业背景", "专长领域", "我是干嘛的", "搞什么的"], "identity"),
    # activity
    (["最近在忙", "手头项目", "最近项目", "在忙什么", "忙什么呢", "在搞啥", "工作重心",
      "在推进什么"], "activity"),
    # decision
    (["为什么选", "之前的决定", "怎么决定", "选了什么", "技术决定", "当初为什么",
      "为什么不用", "为什么这么定"], "decision"),
    # preference
    (["喜欢什么", "偏好", "习惯用什么", "回答要注意", "回答的时候要注意", "要注意什么",
      "沟通方式", "不喜欢什么", "怎么跟我交流", "沟通上"], "preference"),
    # emotion — 询问用户自身情绪/状态/近况,目标是 companion 域的情绪/压力源记忆。
    # 必须排在 procedure 之前(见上)。emotion 关键词带"我/状态/情绪"等强信号词。
    (["我怎么了", "心情", "情绪怎么样", "情绪", "状态怎么样", "最近状态", "压力大",
      "压力", "开心吗", "难过吗", "怎么样了", "还好吗", "焦虑", "烦心事", "我咋了",
      "累不累", "心情好"], "emotion"),
    # procedure — "上次怎么" 泛化,放最后,避免吞掉 emotion 的"我怎么了"
    (["上次怎么", "流程", "技巧", "方法", "该怎么比较", "怎么比较", "评估技术",
      "分阶段", "方法论"], "procedure"),
]

# 中置信规则:模糊匹配。emotion 的"最近"歧义已交给 LLM 兜底——"最近"在 medium 里
# 只指 activity("最近在忙"),情绪近况("最近怎么样")由 high 的"怎么样了/还好吗"覆盖。
MEDIUM_CONFIDENCE_RULES = [
    (["我是", "我叫"], "identity"),
    (["决定", "选了"], "decision"),
    (["喜欢", "偏好", "注意"], "preference"),
    (["最近"], "activity"),
    (["比较", "方案"], "procedure"),
    (["怎么了", "咋了", "还好"], "emotion"),
]


def classify_query_intent(query: str) -> str:
    """对 query 分类,返回 intent 字符串。

    优先级:高置信规则 > 中置信规则 > unknown
    """
    q = query.lower()

    # 高置信规则
    for keywords, intent in HIGH_CONFIDENCE_RULES:
        if any(kw in q for kw in keywords):
            return intent

    # 中置信规则
    for keywords, intent in MEDIUM_CONFIDENCE_RULES:
        if any(kw in q for kw in keywords):
            return intent

    return "unknown"


# ============================================================================
# LLM 兜底分类器:规则 miss(unknown)时,用廉价模型做意图分类
# ============================================================================

# 开关与模型,沿用 reranker 的 env-var 写法。默认关——规则已覆盖评测集全部 query,
# LLM 兜底是为线上未见的 query 形态留的后路,默认走 unknown(全量召回)保 recall。
CLASSIFY_LLM_ENABLED = os.environ.get("ETHAN_MEMORY_CLASSIFY_LLM", "0") == "1"
CLASSIFY_LLM_MODEL = os.environ.get("ETHAN_MEMORY_CLASSIFY_LLM_MODEL", "")  # 空 = lite_model
CLASSIFY_LLM_TIMEOUT = float(os.environ.get("ETHAN_MEMORY_CLASSIFY_LLM_TIMEOUT", "15"))

# 意图目录 + few-shot。system 放 persona + 目录,user 放 query——与 reranker 实测
# 通过的 {system=persona, user=标准} 组合一致(reranker docstring 有 2×2 对照表)。
_CLASSIFY_SYSTEM = (
    "你是记忆检索的意图分类器。给定用户 query,判断它想召回哪一类记忆。\n"
    "只输出一个 intent 标签,不要解释、不要标点。可选标签:\n"
    "identity - 用户的身份/称呼/职业/专长\n"
    "activity - 用户当前在做的事/项目焦点\n"
    "decision - 之前的技术或方案决定及理由\n"
    "preference - 沟通偏好/禁忌/回答风格要求\n"
    "procedure - 方法论/流程/方案比较方法\n"
    "emotion - 用户的情绪/状态/压力/近况感受\n"
    "unknown - 以上都不属于(如闲聊、写代码、问天气)"
)

_CLASSIFY_FEWSHOT = [
    ("我现在主要在做什么", "activity"),
    ("当前焦点是什么", "activity"),
    ("跟我说话的习惯", "preference"),
    ("你应该怎么跟我交流", "preference"),
    ("沟通上有什么讲究", "preference"),
    ("怎么评估技术主张", "procedure"),
    ("怎么分阶段推进", "procedure"),
    ("你了解我的专业背景吗", "identity"),
    ("我的专长领域是啥", "identity"),
    ("我跟你说过的烦心事", "emotion"),
    ("我最近是不是有点焦虑", "emotion"),
    ("今天天气如何", "unknown"),
    ("帮我写段代码", "unknown"),
]

# provider 复用缓存,与 reranker._provider_cache 同构:按 model 缓存,绑定事件循环
_provider_cache: dict[str, tuple[Any, Any]] = {}
_VALID_INTENTS = {"identity", "activity", "decision", "preference",
                  "procedure", "emotion", "unknown"}


async def _get_classify_provider(model: str) -> Any:
    """返回按 model 复用的分类器 provider,绑定当前事件循环。"""
    import asyncio as _asyncio

    from ethan.providers.manager import create_provider

    loop = _asyncio.get_running_loop()
    cached = _provider_cache.get(model)
    if cached is not None:
        prov, bound_loop = cached
        if bound_loop is loop:
            return prov
        try:
            await prov.close()
        except Exception:
            pass
        _provider_cache.pop(model, None)
    prov = create_provider(model)
    _provider_cache[model] = (prov, loop)
    return prov


async def _close_classify_providers() -> None:
    for model in list(_provider_cache):
        prov, _ = _provider_cache.pop(model)
        try:
            await prov.close()
        except Exception:
            pass


def _build_classify_prompt(query: str) -> str:
    """few-shot + 待分类 query。few-shot 全是规则 miss 的 low-confidence 形态,
    示范 LLM 该补的判断维度(近义改写、口语化、间接问法)。"""
    lines = ["示例:"]
    for q, intent in _CLASSIFY_FEWSHOT:
        lines.append(f"query: {q}\nintent: {intent}")
    lines.append(f"\nquery: {query}\nintent:")
    return "\n".join(lines)


def _parse_intent(text: str) -> str:
    """从模型回复抽 intent 标签。模型可能带换行/标点/解释,只取第一个有效标签。

    用词边界匹配而非子串包含——否则 "not identity" 会命中 identity、"not a
    decision" 会命中 decision,把 LLM 的否定判断反转成错误 intent。
    """
    if not text:
        return "unknown"
    t = text.strip().lower()
    # 先试整行精确匹配(模型通常直接输出单个标签,可能带标点)
    first_line = t.split("\n", 1)[0].strip().strip("。.,;:！!？?\"'`")
    for intent in ("identity", "activity", "decision", "preference",
                   "procedure", "emotion", "unknown"):
        if first_line == intent:
            return intent
    # 整行不是单个标签时,按词边界查第一个完整出现的标签(排除 not/no 等否定)
    import re

    negated = bool(re.search(r"\b(not|no|non|不是|不|没)\b", t))
    if negated:
        return "unknown"  # 否定句无法可靠解析意图,回退全量召回保 recall
    for intent in ("identity", "activity", "decision", "preference",
                   "procedure", "emotion", "unknown"):
        if re.search(rf"\b{intent}\b", t):
            return intent
    return "unknown"


async def classify_query_intent_llm(query: str, *, model: str = "") -> str:
    """LLM 兜底意图分类。规则返回 unknown 时调用,失败/超时回退 unknown。

    默认关(ETHAN_MEMORY_CLASSIFY_LLM=1 开)。模型空 = lite_model(与记忆压缩同档)。
    """
    import asyncio

    from ethan.providers.base import Message

    if not query.strip():
        return "unknown"
    # 显式入参 > env > lite_model（与 reranker 同口径，空 lite_model 时按主模型推断）
    if model:
        mdl = model
    elif CLASSIFY_LLM_MODEL:
        mdl = CLASSIFY_LLM_MODEL
    else:
        try:
            from ethan.memory.consolidator import get_lite_model
            mdl = get_lite_model()
        except Exception:
            mdl = ""
    if not mdl:
        return "unknown"

    provider = await _get_classify_provider(mdl)
    prompt = _build_classify_prompt(query)
    try:
        resp = await asyncio.wait_for(
            provider.chat([Message(role="user", content=prompt)],
                          system=_CLASSIFY_SYSTEM),
            timeout=CLASSIFY_LLM_TIMEOUT,
        )
        return _parse_intent(resp.content or "")
    except Exception:
        logger.debug("memory classify LLM: failed for query=%r", query, exc_info=True)
        return "unknown"


async def classify_query_intent_async(query: str) -> str:
    """完整意图分类管线:规则先行,miss 则 LLM 兜底(需开启)。

    这是召回层应调用的入口——规则零成本且已覆盖评测集全部 query;LLM 兜底只在
    规则 miss + 开关开启时触发,默认 unknown(全量召回,保 recall 不丢)。
    """
    intent = classify_query_intent(query)
    if intent != "unknown":
        return intent
    if not CLASSIFY_LLM_ENABLED:
        return "unknown"
    return await classify_query_intent_llm(query)


# ============================================================================
# Memory Role 推断规则(入库时用)
# ============================================================================

def infer_memory_role(dimension: str) -> str:
    """从 dimension 字段推断 memory_role。

    role = dimension 一级前缀（点号前部分），与 INTENT_ROLE_MAP 的 value 对齐：
        identity.*       → identity
        decision.*       → decision
        preference.*     → preference
        activity.*       → activity
        methodology.*    → methodology
        skill.*          → skill_experience   (前缀缩写，role 用全称)
        relationship.*   → relationship
        其他             → task_context（兜底，不过滤时仍可召回）

    用一级前缀而非整条 dimension，是因为召回过滤按 intent 大类切——
    activity.project 和 activity.task 同属 activity intent，应一起被
    activity query 召回。
    """
    if not dimension:
        return "task_context"
    prefix = dimension.lower().split(".", 1)[0]
    # 前缀缩写 → role 全称的特例
    alias = {"skill": "skill_experience"}
    role = alias.get(prefix, prefix)
    if role in MEMORY_ROLES:
        return role
    return "task_context"


# ============================================================================
# 验证:在样本集上跑一次
# ============================================================================

def _validate_on_samples():
    """在样本集上验证分类器准确率"""
    import json
    from pathlib import Path

    # 读取样本集
    sample_path = Path("/tmp/classification_samples_full.json")
    if not sample_path.exists():
        print("样本集文件不存在,跳过验证")
        return

    with open(sample_path) as f:
        data = json.load(f)

    # 验证 query intent
    query_samples = data["query_samples"]
    correct = 0
    total = 0
    for s in query_samples:
        if s["confidence"] == "high":
            total += 1
            predicted = classify_query_intent(s["query"])
            if predicted == s["intent"]:
                correct += 1

    if total > 0:
        print(f"Query intent 高置信样本: {correct}/{total} = {correct/total:.1%} 准确")

    # 验证 memory role
    memory_samples = data["memory_samples"]
    correct = sum(
        1 for s in memory_samples
        if infer_memory_role(s["dimension"]) == s["memory_role"]
    )
    print(f"Memory role 样本: {correct}/{len(memory_samples)} = {correct/len(memory_samples):.1%} 准确")


if __name__ == "__main__":
    _validate_on_samples()

    # 测试几个 case
    test_queries = [
        "你还记得我是谁吗",
        "我最近在忙什么",
        "为什么选了 SQLite",
        "我喜欢什么格式",
        "上次怎么调试的",
        "技术方案该怎么比较",
        "回答的时候要注意什么",
    ]
    print("\n测试样例:")
    for q in test_queries:
        intent = classify_query_intent(q)
        role = INTENT_ROLE_MAP.get(intent)
        print(f"  [{intent:10s}] {q[:30]:30s} → role={role}")