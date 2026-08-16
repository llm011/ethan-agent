"""Recall structured memories into the agent's system prompt.

这是对话时长期记忆的唯一召回入口（flat-facts 系统已退役）。Companion-domain
memories are recalled only in companion mode so emotional data never leaks into
other sessions. Restricted memories are never injected.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from ethan.memory.records import MemoryDomain, MemoryStatus
from ethan.memory.store import MemoryStore

logger = logging.getLogger(__name__)

# 注入上限：候选池按 RRF 排序后**每域**取前多少条进 prompt。与候选预算解耦——
# 池子照旧宽（保 recall），只收窄进 prompt 的那一屏（降噪）。
#
# 默认 6 是实测拐点（tests/memory_eval/probe_inject_depth.py，120 case/6 域，
# 真实 `_collect` 链路，候选预算固定 20）：
#
#     深度   P@注入   recall   真值条数  噪声条数
#       6    21.4%   83.2%     1.32     4.85   ← 默认
#       8    16.5%   85.3%     1.35     6.82
#      15    14.2%  100.0%     1.58     9.58   ← 改造前
#
# 8→6 是曲线上唯一划算的一段：掉 2.1pt recall 换掉近 2 条噪声。再浅收益就反转
# （6→5 掉 3.2pt 只换 0.95 条）。
#
# 逐域耐受度差异很大，全局平均会掩盖单域崩溃：深度 6 时 methodology / companion
# 已满额 100%，但 personal_information 只有 71.7%。身份类事实缺一条比多几条噪声
# 更贵，所以这个值留成 env 可调——把 recall 在浅切下买回来是判官（或修活 FTS
# 词法通道）的活，不是调这个常量能解决的。
INJECT_MAX = int(os.environ.get("ETHAN_MEMORY_INJECT_MAX", "6"))

# Layer 2 确定性截断：RRF 融合后，对「单向量独占命中」施加相对距离断层截断。
#
# 背景：`recall_neighbors` 返回每条候选的 L2 距离，但原来解到 `_distance` 就丢了，
# 只拿 rank 喂 RRF——距离 0.6 的命中和 1.28 的命中权重完全相同。距离是全链路唯一
# 的连续相关性信号，丢掉它等于把判别全压在离散 rank 上。
#
# 机制（逐 query+domain 自适应，复用判官 maxgap 的相对断层思路，但零 LLM 成本）：
#   rel_dist = dist - min(dist in this query+domain)
# 双通道一致命中（FTS∩向量）无条件保留——一致性本身是强信号，RRF 已隐式奖励它
# （两份倒数相加），Layer 2 不再砍；FTS 独占命中无距离信号，也不参与截断，避免误
# 杀精确命中；只有「向量独占」命中受 rel_dist <= REL_GAP 约束。
#
# probe_distance.py 的 REL_GAP 扫（120 case）给出 go/no-go 判据：
#   REL_GAP=0.15 → recall 100%、precision 19.3%（vs 当前 17.4%）
#   REL_GAP=0.10 → recall 95.7%（掉 recall，不能开）
# ∞ = 关闭（等价改造前行为）。默认 ∞，等 1200-case 扫参确认 recall 仍 100% 后再开。
REL_GAP = float(os.environ.get("ETHAN_MEMORY_RECALL_REL_GAP", "inf"))

_TYPE_LABELS = {
    "personal_information": "个人信息",
    "preference": "偏好",
    "methodology": "方法论",
    "activity": "正在做的事",
    "decision": "决定",
    "relationship": "约定",
    "skill_experience": "技能经验",
}


def _is_companion_mode(mode: str) -> bool:
    try:
        from ethan.core.modes import resolve_mode

        return resolve_mode(mode).key == "companion"
    except Exception:
        return mode in {"companion", "苏念", "陪伴"}


def _format_block(memory: Any) -> str:
    label = _TYPE_LABELS.get(memory.memory_type, memory.memory_type)
    quote = f" (来源: session={memory.source_session_id or '?'} msg={memory.source_message_id or '?'})" if memory.source_session_id else ""
    return f"[{label}] {memory.content}{quote}"


def _collect(
    store: MemoryStore,
    query: str,
    *,
    domain: str,
    max_items: int,
    intent: str = "unknown",
) -> list[Any]:
    """召回候选集：FTS/LIKE 精确通道 + 向量语义通道，RRF 融合排序。

    向量通道补齐 FTS 的 CJK 分词短板与语义泛化（"住哪" 命中 "家在深圳"）；
    两通道都空时回退 importance top-N，保证身份类事实始终可用。

    intent: query intent,用于召回层 role 过滤。intent → role 映射见 INTENT_ROLE_MAP。
    """
    from ethan.memory.classifier import INTENT_ROLE_MAP

    role_filter = INTENT_ROLE_MAP.get(intent)
    # 时间衰减软降权（ETHAN_MEMORY_RANK_DECAY，默认开）：factor 只影响排序，
    # 不改状态。Tier A 恒 1.0；RANK_DECAY=0 时恒 1.0——乘以 1.0 不改变任何
    # 比较结果，排序与旧实现逐位一致（回归测试的硬断言）。
    from ethan.memory.decay import RANK_DECAY_ENABLED, rank_decay_factor

    import time as _time

    statuses = [MemoryStatus.ACTIVE.value]
    fts_hits: list[Any] = []
    vec_hits: list[tuple[str, float]] = []
    if query.strip():
        fts_hits = [
            memory
            for memory in store.search_memories(
                query, memory_domain=domain, memory_role=role_filter, statuses=statuses, limit=max_items
            )
            if memory.sensitivity != "restricted"
        ]
        from ethan.memory.memory_vectors import recall_neighbors
        vec_hits = recall_neighbors(
            query=query, memory_domain=domain, db_path=store.db_path, limit=max_items * 2,
            memory_role=role_filter,
        )

    if not fts_hits and not vec_hits:
        # 双通道皆空时按 importance 兜底。role_filter 与搜索层一致——已知 intent
        # (role_filter 非 None) 时仍按该 role 取 top-N：该 role 有记忆但语义没命中，
        # 按 importance 注入同 role 记忆比跨 role 注入噪声合理；该 role 无记忆(如
        # emotion→task_context 在 GENERAL 域)则返回空,由其他域(COMPANION)提供相关记忆。
        # role_filter=None(unknown intent)时跨全 role 取 top-N,等价改造前安全网。
        pool = [
            memory
            for memory in store.list_memories(
                memory_domain=domain, status=MemoryStatus.ACTIVE.value,
                memory_role=role_filter, limit=max_items * 3,
            )
            if memory.sensitivity != "restricted"
        ]
        if RANK_DECAY_ENABLED:
            # 兜底路径同样软降权：主键 importance×factor（同时修正了本函数
            # docstring 里 "importance top-N" 与实际 updated_at DESC 切片的
            # 历史不一致）。开关关闭时保持 list_memories 的 updated_at DESC
            # 原行为，与旧实现逐位一致。
            now = _time.time()
            pool.sort(
                key=lambda m: (-m.importance * rank_decay_factor(m, now), -m.confidence)
            )
        return pool[:max_items]

    # Reciprocal Rank Fusion(k=60):对两通道的排名取倒数求和,无需标定分数量纲
    now = _time.time()
    scores: dict[str, float] = {}
    by_id: dict[str, Any] = {}
    # dist / fts_ids 仅 Layer 2（REL_GAP<inf）截断时需要；默认 inf 时跳过构造，
    # 省掉热路径上每个 hit 的 dict 写入。REL_GAP 开关在模块加载时定，这里分支稳定。
    use_gap = REL_GAP < float("inf")
    dist: dict[str, float] | None = {} if use_gap else None
    fts_ids: set[str] | None = set() if use_gap else None
    for rank, memory in enumerate(fts_hits):
        scores[memory.id] = scores.get(memory.id, 0.0) + 1.0 / (61 + rank)
        by_id[memory.id] = memory
        if fts_ids is not None:
            fts_ids.add(memory.id)
    for rank, (memory_id, _distance) in enumerate(vec_hits):
        memory = by_id.get(memory_id)
        if memory is None:
            memory = store.get_memory(memory_id)
            if memory is None or memory.status != MemoryStatus.ACTIVE.value:
                continue
            if memory.sensitivity == "restricted":
                continue
            if memory.valid_from is not None and memory.valid_from > now:
                continue
            if memory.valid_until is not None and memory.valid_until < now:
                continue
            by_id[memory_id] = memory
        scores[memory_id] = scores.get(memory_id, 0.0) + 1.0 / (61 + rank)
        if dist is not None and (memory_id not in dist or _distance < dist[memory_id]):
            dist[memory_id] = _distance

    # Layer 2 确定性截断：相对距离断层。只切「向量独占」命中——双通道一致
    # （FTS∩向量）无条件保留，FTS 独占无距离不参与。min_dist 逐 query+domain
    # 自适应标定，不假设悬崖在同一绝对位置。REL_GAP=inf 时 use_gap=False 整段
    # 跳过，逐条等于改造前。
    if dist is not None and fts_ids is not None and dist:
        min_dist = min(dist.values())
        keep_ids = {
            mid for mid, d in dist.items()
            if d - min_dist <= REL_GAP or mid in fts_ids
        }
        # 只在向量独占命中里砍；FTS 独占（无 dist）和双通道一致自然保留
        by_id = {mid: m for mid, m in by_id.items() if mid in keep_ids or mid not in dist}
        scores = {mid: s for mid, s in scores.items() if mid in keep_ids or mid not in dist}

    # 软降权乘在 RRF 分数上（Layer 2 截断之后——截断基于向量相对距离，与分
    # 数量纲无关，两者正交）。tie-break 链原样保留，因子=1.0 时乘法不改变
    # 比较结果，RANK_DECAY=0 与旧序严格一致。
    merged = sorted(
        by_id.values(),
        key=lambda m: (
            -scores[m.id] * rank_decay_factor(m, now),
            -m.importance,
            -m.confidence,
        ),
    )
    return merged[:max_items]


def _collect_split(
    store: MemoryStore, query: str, mode: str, max_items: int, intent: str = "unknown"
) -> tuple[list[Any], list[Any]]:
    """分域收候选，**不合并**。domain 隔离是硬门控——companion 只在 companion 模式取。

    保持分域返回是为了 fallback 能逐域截断：同步版从不对并集做最终截断，
    companion 模式下 general 和 companion 各拿满 max_items。若在并集上截断，
    general 满额时 companion 会被整段砍掉。
    """
    general = _collect(store, query, domain=MemoryDomain.GENERAL.value, max_items=max_items, intent=intent)
    companion: list[Any] = []
    if _is_companion_mode(mode):
        companion = _collect(
            store, query, domain=MemoryDomain.COMPANION.value, max_items=max_items, intent=intent
        )
    return general, companion


def _finalize(store: MemoryStore, hits: list[Any]) -> "RecallResult":
    """标记已召回 + 格式化。

    touch_recalled 必须在切点之后：被重排砍掉的候选**从未进入 prompt**，若把它们
    也记上 last_recalled_at/recall_count，召回统计就失真，而这套统计会反过来喂
    importance 排序，形成自我强化。
    """
    try:
        store.touch_recalled([memory.id for memory in hits])
    except Exception:
        logger.debug("structured recall: touch_recalled failed", exc_info=True)
    lines = [_format_block(memory) for memory in hits]
    return RecallResult(text="\n".join(lines), count=len(lines), items=lines)


@dataclass
class RecallResult:
    """Structured recall result with metadata for tool-timeline visibility."""
    text: str  # 格式化后注入 system prompt 的多行文本
    count: int  # 召回条数
    items: list[str]  # 每条召回内容的格式化行（前端展开可见）

    def __bool__(self) -> bool:
        return self.count > 0


def build_structured_recall(query: str, *, mode: str = "", max_items: int = 8) -> RecallResult:
    """Build a system-prompt memory block from structured memories.

    Returns a RecallResult (falsy when nothing recalled). Any storage failure
    is swallowed — recall must never break the main conversation.
    """
    empty = RecallResult(text="", count=0, items=[])
    try:
        store = MemoryStore()
    except Exception:
        logger.debug("structured recall: store unavailable", exc_info=True)
        return empty

    try:
        from ethan.memory.classifier import classify_query_intent

        intent = classify_query_intent(query)
        general, companion = _collect_split(store, query, mode, max_items, intent=intent)
        all_hits = general + companion
        if not all_hits:
            return empty
        return _finalize(store, all_hits)
    except Exception:
        logger.debug("structured recall failed", exc_info=True)
        return empty
    finally:
        try:
            store.close()
        except Exception:
            pass


async def build_structured_recall_async(
    query: str, *, mode: str = "", max_items: int = 8,
    fallback_keep: int | None = None, rerank: bool = True,
) -> RecallResult:
    """宽候选池 + 浅注入的召回。异步调用方应优先用这个。

    两个参数管两件独立的事——这是本函数存在的理由：

    - `max_items` = **候选预算**。控 `_collect` 里的 FTS limit / 向量 limit(*2) /
      RRF 池大小。它只决定 recall，宽一点没坏处。
    - `INJECT_MAX`（可用 `fallback_keep` 覆盖）= **注入上限，逐域**。控进 prompt
      的条数，也就是噪声量。

    改造前这两件事是同一个参数，所以调它只能在 recall 和 precision 之间平移——
    收紧则真值被砍（阈值 1.1 时代 recall 58.3%），放宽则噪声灌进来（1.3 之后平均
    9.58 条噪声、P@注入 14%）。拆开之后才能同时保住 recall 和降噪。

    判官（`rerank_and_cut`）跑的时候注入条数由它的切点 + `MAX_KEEP` 决定；不跑或
    跑失败时退回 RRF 序的逐域 top-`keep`。

    **这与改造前不再逐条一致，是有意的行为变更。** #189 曾刻意保住「默认关 = 逐条
    等于改造前」，代价是默认关时候选预算也被收回注入上限、降噪为零。实测拐点数据
    （见 `INJECT_MAX` 的注释）说明那个保真度不值得——8→6 掉 2.1pt recall 换掉近
    2 条噪声。同步版 `build_structured_recall` 保持原样，仍可当 A/B 的对照臂。

    截断**逐域**做，不在并集上截。companion 模式下 general 通常就能占满额度，在
    并集上截会把 companion 整段砍掉。实测确认过这个坑：并集截断下 companion 域
    recall 从深度 1 到 10 恒为 33.3%、到 15 才突变 100%。

    重排本身仍在两域候选的**并集**上只做一次，不能下推到 `_collect` 里分域各做
    一次——否则 general 和 companion 会各自算出一个分数分布、各切一个断层，两边按
    不同标准砍，合起来条数还可能翻倍。domain 隔离由 `_collect_split` 硬门控保证。
    """
    from ethan.memory.reranker import RERANK_ENABLED, rerank_and_cut

    empty = RecallResult(text="", count=0, items=[])
    # 注入上限默认走实测拐点；`fallback_keep` 留给评测 harness 扫深度用。
    keep = INJECT_MAX if fallback_keep is None else fallback_keep
    do_rerank = rerank and RERANK_ENABLED

    try:
        store = MemoryStore()
    except Exception:
        logger.debug("structured recall: store unavailable", exc_info=True)
        return empty

    try:
        # 候选预算始终取满。池子宽只影响 recall，收窄它等于又一次调阈值。
        # 异步路径用 classify_query_intent_async：规则先行，miss 走 LLM 兜底
        # （需 ETHAN_MEMORY_CLASSIFY_LLM=1，默认关 = 等价同步规则分类）。
        from ethan.memory.classifier import classify_query_intent_async

        intent = await classify_query_intent_async(query)
        general, companion = _collect_split(store, query, mode, max_items, intent=intent)
        if not general and not companion:
            return empty
        shallow = general[:keep] + companion[:keep]
        if do_rerank:
            # 判官看并集（见 docstring），失败时退回逐域浅注入
            all_hits = await rerank_and_cut(
                query, general + companion, fallback=shallow
            )
        else:
            all_hits = shallow
        if not all_hits:
            return empty
        return _finalize(store, all_hits)
    except Exception:
        logger.debug("structured recall (async) failed", exc_info=True)
        return empty
    finally:
        try:
            store.close()
        except Exception:
            pass
