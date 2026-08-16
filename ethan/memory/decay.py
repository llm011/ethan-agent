"""记忆遗忘/衰减与强化晋升（确定性规则，零 LLM）。

设计哲学对齐 docs/memory.md：记忆的生命周期决策由系统规则确定性保证。本模块
负责两条对称的链路：

- 负衰减（遗忘）：召回排序按 tier 半衰期软降权（只影响排序，默认开）+
  夜间归档任务（ETHAN_MEMORY_DECAY，默认关）——项目 scope 休眠批量转
  dormant、tentative 决定快速过期、dormant 超 180 天转 forgotten（脱敏）。
- 正强化（晋升）：evidence 独立 session 数阶梯抬升 confidence（默认开），
  修复"多次发生的偏好卡在首次准入置信度"的问题。

Tier 规则表（判定优先级 A > C > B）：

===== ======== =============================== ==========================
Tier  归档     召回半衰期                        判定
===== ======== =============================== ==========================
A     豁免     不衰减                           companion 域；scope ∈
                                                 {user,user_domain,
                                                 user_skill}；dimension
                                                 前缀 ∈ {identity,
                                                 preference,relationship}
B     21 天    30 天                            其余（project scope 的
      休眠                                      decision/methodology 等）
C     14 天    3 天                             decision/activity 且
      无强化                                    structured_data.tentative
                                                is True（"先试试"）
===== ======== =============================== ==========================

核心不变量：
1. 一切状态迁移纯确定性、零 LLM、阈值全部 env 可调；
2. 晋升只做 max(conf, 阶梯值) 单调抬升，且不碰 updated_at（走
   bulk_set_confidence_quiet）——批量晋升若刷新 updated_at 会永久重置 Tier B
   scope 休眠计时（scope 活跃信号含 MAX(updated_at)），休眠检测失效；
3. dry_run 只读不改状态，返回计数与日志真实，供真实库验证；
4. 强化信号统一为：add_evidence（bump updated_at）、touch_recalled
   （写 last_recalled_at）、tentative 清标（bump updated_at）——衰减锚点
   max(updated_at, last_recalled_at) 自动被三者重置。
"""
from __future__ import annotations

import logging
import os
from typing import Any

from ethan.memory.records import MemoryDomain, MemoryStatus
from ethan.memory.store import MemoryStore

logger = logging.getLogger(__name__)

# —— 归档任务（夜间，写状态；默认关，先 dry-run 真实库再开）——
DECAY_ENABLED = os.environ.get("ETHAN_MEMORY_DECAY", "0") == "1"
DECAY_DRY_RUN = os.environ.get("ETHAN_MEMORY_DECAY_DRY_RUN", "0") == "1"
PROJECT_IDLE_DAYS = float(os.environ.get("ETHAN_MEMORY_DECAY_PROJECT_IDLE_DAYS", "21"))
TENTATIVE_GRACE_DAYS = float(os.environ.get("ETHAN_MEMORY_DECAY_TENTATIVE_GRACE_DAYS", "14"))
DORMANT_FORGET_DAYS = float(os.environ.get("ETHAN_MEMORY_DECAY_FORGET_DAYS", "180"))

# —— 召回软降权（只影响排序，默认开；RANK_DECAY=0 时因子恒 1.0，
#    排序与旧实现逐位一致——这是回归测试的硬断言）——
RANK_DECAY_ENABLED = os.environ.get("ETHAN_MEMORY_RANK_DECAY", "1") == "1"
HALF_LIFE_B_DAYS = float(os.environ.get("ETHAN_MEMORY_RANK_HALF_LIFE_PROJECT", "30"))
HALF_LIFE_C_DAYS = float(os.environ.get("ETHAN_MEMORY_RANK_HALF_LIFE_TENTATIVE", "3"))

# —— 强化晋升（默认开；companion 有自己的晋升状态机，默认豁免）——
PROMOTE_ENABLED = os.environ.get("ETHAN_MEMORY_PROMOTE", "1") == "1"
PROMOTE_LADDER_RAW = os.environ.get("ETHAN_MEMORY_PROMOTE_LADDER", "2:0.8,3:0.9,5:0.95")
_raw_domains = os.environ.get("ETHAN_MEMORY_PROMOTE_DOMAINS", "general")
PROMOTE_DOMAINS = {d.strip() for d in _raw_domains.split(",") if d.strip()}

TIER_A = "A"  # 豁免：永不自动归档、召回不衰减
TIER_B = "B"  # 项目休眠归档 / 30 天半衰期
TIER_C = "C"  # tentative 快速过期 / 3 天半衰期

EXEMPT_SCOPE_TYPES = frozenset({"user", "user_domain", "user_skill"})
EXEMPT_DIMENSION_PREFIXES = frozenset({"identity", "preference", "relationship"})
TENTATIVE_MEMORY_TYPES = frozenset({"decision", "activity"})

_SECONDS_PER_DAY = 86400.0


def memory_tier(record: Any) -> str:
    """判定记忆的衰减 tier。A 优先于 C 优先于 B。

    Tier A "全部豁免" 按字面语义压过 tentative 标记：user scope 下的临时
    决定既不归档也不衰减（user 级内容统一走豁免档，避免同一条规则两个口径）。
    dimension 一级前缀取法与 classifier.infer_memory_role 同口径（小写）。
    tentative 判定用 ``is True``：旧记忆/旧提取输出无此键自然落 B/A。
    """
    if record.memory_domain == MemoryDomain.COMPANION.value:
        return TIER_A
    if record.scope_type in EXEMPT_SCOPE_TYPES:
        return TIER_A
    if (record.dimension or "").lower().split(".", 1)[0] in EXEMPT_DIMENSION_PREFIXES:
        return TIER_A
    if (
        record.memory_type in TENTATIVE_MEMORY_TYPES
        and record.structured_data.get("tentative") is True
    ):
        return TIER_C
    return TIER_B


def rank_decay_factor(record: Any, now: float) -> float:
    """RRF 分数 / importance 的乘性衰减因子。Tier A 与开关关恒 1.0。

    锚点取 max(updated_at, last_recalled_at)：补证据（bump updated_at）与
    召回 touch（写 last_recalled_at）都重置衰减计时——被用过的记忆不该沉底。
    """
    if not RANK_DECAY_ENABLED:
        return 1.0
    half_life = {TIER_B: HALF_LIFE_B_DAYS, TIER_C: HALF_LIFE_C_DAYS}.get(memory_tier(record))
    if half_life is None or half_life <= 0:
        return 1.0
    anchor = max(record.updated_at or 0.0, record.last_recalled_at or 0.0)
    delta_days = max(0.0, (now - anchor) / _SECONDS_PER_DAY)
    return 0.5 ** (delta_days / half_life)


def _forget_long_dormant(store: MemoryStore, now: float, *, dry_run: bool) -> int:
    """dormant 超过 DORMANT_FORGET_DAYS（默认 180 天）→ forgotten（脱敏硬删）。

    复用 forget_memory 的既有脱敏语义：正文/证据 quote 改写 [forgotten]、
    FTS 行与向量索引删除。沿用 _expire_memories 的 list(limit=5000) 遍历
    模式——个人库规模下足够，forget 改 updated_at 导致的分页漂移也不敏感
    （一次性快照后逐条处理）。
    """
    cutoff = now - DORMANT_FORGET_DAYS * _SECONDS_PER_DAY
    count = 0
    for memory in store.list_memories(status=MemoryStatus.DORMANT.value, limit=5000):
        if memory.dormant_at is None or memory.dormant_at >= cutoff:
            continue
        if dry_run:
            count += 1
            continue
        try:
            store.forget_memory(memory.id)
            count += 1
        except Exception:
            logger.warning("[MemoryDecay] forget failed for %s", memory.id, exc_info=True)
    if count:
        logger.info(
            "[MemoryDecay] forgot %d long-dormant memories (>%.0f days)%s",
            count, DORMANT_FORGET_DAYS, " (dry-run)" if dry_run else "",
        )
    return count


def _dormant_idle_projects(store: MemoryStore, now: float, *, dry_run: bool,
                           idle_project_info: dict[str, float] | None = None) -> int:
    """Tier B：project scope 连续 PROJECT_IDLE_DAYS 无信号 → 非 Tier A 记忆批量 dormant。

    休眠信号是 scope 级四路 MAX（见 store.project_scope_last_activity）：
    updated_at / created_at / last_recalled_at / evidence.created_at。Tier A
    维度（项目内沉淀出的偏好等）留在原地不归档——它们的价值独立于项目窗口。

    idle_project_info: {scope_id: last_activity_timestamp} 由调用方预计算传入，
    既用于成员判定也用于日志输出，避免重复查询 project_scope_last_activity()。
    """
    if idle_project_info is None:
        idle_project_info = {}
    count = 0
    for scope_id, last_signal in idle_project_info.items():
        targets = [
            m for m in store.list_memories(
                scope_type="project", scope_id=scope_id,
                status=MemoryStatus.ACTIVE.value, limit=500,
            )
            if memory_tier(m) != TIER_A
        ]
        if not targets:
            continue
        if dry_run:
            logger.info(
                "[MemoryDecay][dry] would dormant %d memories in idle project scope %s",
                len(targets), scope_id,
            )
            count += len(targets)
            continue
        changed = store.bulk_set_dormant([m.id for m in targets])
        count += changed
        logger.info(
            "[MemoryDecay] dormant %d memories in idle project scope %s (idle since %.0f)",
            changed, scope_id, last_signal,
        )
    return count


def _dormant_stale_tentative(store: MemoryStore, now: float, *, dry_run: bool,
                             idle_project_scopes: frozenset[str] = frozenset()) -> int:
    """Tier C：tentative 决定 TENTATIVE_GRACE_DAYS 无强化 → dormant。

    强化清标在 admission 侧（_maybe_clear_tentative）：用户后续表达定稿意图
    时候选 merge 会清掉 tentative，这条记忆即退出 Tier C 轨道。

    跳过 idle project scope 内的 tentative：_dormant_idle_projects 已在前面
    捕获（tier != A 一律归档），避免 dry_run 下双重计数违反不变量 #3。
    idle_project_scopes 由调用方预计算传入，避免重复查询。
    """
    cutoff = now - TENTATIVE_GRACE_DAYS * _SECONDS_PER_DAY
    # 先收集所有候选，一次性批量查询 last_evidence_at，消除 N+1
    candidates = []
    for memory in store.list_active_tentative():
        if memory_tier(memory) != TIER_C:
            continue  # user scope 下的 tentative 是 Tier A，跳过
        if memory.scope_type == "project" and memory.scope_id in idle_project_scopes:
            continue  # project scope 已被 _dormant_idle_projects 捕获
        candidates.append(memory)
    # 批量查询 evidence 时间（一次 GROUP BY，替代逐条 SELECT MAX）
    evidence_ts = store.batch_last_evidence_at([m.id for m in candidates])
    count = 0
    for memory in candidates:
        last_signal = max(
            memory.updated_at or 0.0,
            memory.created_at or 0.0,
            memory.last_recalled_at or 0.0,
            evidence_ts.get(memory.id, 0.0),
        )
        if last_signal >= cutoff:
            continue
        if dry_run:
            count += 1
            continue
        store.set_status(memory.id, MemoryStatus.DORMANT.value)
        count += 1
    if count:
        logger.info(
            "[MemoryDecay] dormant %d stale tentative decisions%s",
            count, " (dry-run)" if dry_run else "",
        )
    return count


def _parse_ladder(raw: str) -> list[tuple[int, float]]:
    """解析 "2:0.8,3:0.9,5:0.95" → [(2,0.8),(3,0.9),(5,0.95)]（阈值升序）。

    非法条目静默跳过——env 配错不该让夜间任务崩，只让晋升退化为空。
    但若全部非法（输入非空却返回空列表），打 warning 帮助定位配置问题。
    """
    ladder: list[tuple[int, float]] = []
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece or ":" not in piece:
            continue
        threshold_raw, value_raw = piece.split(":", 1)
        try:
            threshold = int(threshold_raw)
            value = float(value_raw)
        except ValueError:
            continue
        if threshold > 0 and 0.0 <= value <= 1.0:
            ladder.append((threshold, value))
    ladder.sort()
    if not ladder and raw.strip():
        logger.warning(
            "[MemoryDecay] PROMOTE_LADDER parsed to empty from %r — "
            "confidence promotion will be a no-op", raw,
        )
    return ladder


def ladder_target(session_count: int, ladder: list[tuple[int, float]] | None = None) -> float | None:
    """独立 evidence session 数对应的阶梯置信度；不满足任何阈值返回 None。

    取"满足的最高阶梯值"：count=3 在 [(2,0.8),(3,0.9),(5,0.95)] 上得 0.9。
    """
    if ladder is None:
        ladder = _parse_ladder(PROMOTE_LADDER_RAW)
    target: float | None = None
    for threshold, value in ladder:
        if session_count >= threshold:
            target = value if target is None else max(target, value)
    return target


def apply_confidence_promotion(
    store: MemoryStore, now: float, *, dry_run: bool = False
) -> int:
    """强化晋升：active 记忆按 distinct evidence session 数单调抬升 confidence。

    只做 max(conf, 阶梯值)：explicit(>=0.95)/corrected(1.0) 不受影响，救的是
    observed 晋升、accrual、以及历史上只补证据从不更新置信度的记忆（如
    "论文做成 PPT"偏好发生多次仍卡 60% 的 case——存量数据首夜自动自愈）。
    写入走 bulk_set_confidence_quiet（不动 updated_at，见模块不变量 2）。
    PROMOTE_DOMAINS 默认 {"general"}：companion 有自己的晋升语义，默认豁免。
    """
    if not PROMOTE_ENABLED:
        return 0
    counts = store.evidence_session_counts(status=MemoryStatus.ACTIVE.value)
    if not counts:
        return 0
    records = {
        record.id: record
        for record in store.list_memories(status=MemoryStatus.ACTIVE.value, limit=5000)
    }
    # 预解析一次，避免每条记忆重解析
    ladder = _parse_ladder(PROMOTE_LADDER_RAW)
    promoted = 0
    # 收集后经 bulk_set_confidence_quiet 单事务提交（N 条记忆一次 fsync）。
    # 不能在 store.transaction() 里逐条调 set_confidence_quiet：其内部
    # commit 会提前打断外层事务，退化回逐条自动提交。
    pending: list[tuple[str, float]] = []
    for memory_id, sessions in counts.items():
        record = records.get(memory_id)
        if record is None:
            continue
        if PROMOTE_DOMAINS and record.memory_domain not in PROMOTE_DOMAINS:
            continue
        target = ladder_target(sessions, ladder=ladder)
        if target is None or target <= record.confidence:
            continue
        if not dry_run:
            pending.append((memory_id, target))
        promoted += 1
    store.bulk_set_confidence_quiet(pending)
    if promoted:
        logger.info(
            "[MemoryDecay] promoted confidence for %d memories%s",
            promoted, " (dry-run)" if dry_run else "",
        )
    return promoted


def apply_memory_decay(store: MemoryStore, now: float) -> dict[str, int]:
    """夜间衰减主入口。挂载于 structured_consolidation.run_structured_consolidation。

    DECAY_ENABLED=0 时直接返回全零 dict（不读库），默认零开销。顺序：先
    forget（180d）再 dormancy 扫描——当夜刚 dormant 的记录不可能进 180d
    窗口，顺序只影响日志可读性。晋升（promoted）不受 DECAY 开关控制，
    只受 PROMOTE_ENABLED 控制——它是修复置信度卡死的独立链路。
    """
    result: dict[str, int] = {"dormanted": 0, "decayed": 0, "forgotten": 0, "promoted": 0}
    if PROMOTE_ENABLED:
        result["promoted"] = apply_confidence_promotion(store, now, dry_run=DECAY_DRY_RUN)
    if not DECAY_ENABLED:
        return result
    dry = DECAY_DRY_RUN
    result["forgotten"] = _forget_long_dormant(store, now, dry_run=dry)
    # 预计算一次 idle project scopes + last_signal，供两个函数共用
    idle_cutoff = now - PROJECT_IDLE_DAYS * _SECONDS_PER_DAY
    idle_project_info: dict[str, float] = {
        scope_id: last
        for scope_id, last in store.project_scope_last_activity()
        if last < idle_cutoff
    }
    result["dormanted"] = _dormant_idle_projects(store, now, dry_run=dry,
                                                 idle_project_info=idle_project_info)
    result["decayed"] = _dormant_stale_tentative(store, now, dry_run=dry,
                                                  idle_project_scopes=frozenset(idle_project_info))
    logger.info("[MemoryDecay] %s%s", result, " (dry-run)" if dry else "")
    return result


def wake_scope_dormant(store: MemoryStore, scope_type: str, scope_id: str) -> int:
    """唤醒一个 scope 下全部 dormant 记忆（项目回归信号）。

    供 admission 唤醒钩子与 UI 批量恢复调用。任何异常吞掉打日志——唤醒失败
    只意味着该 scope 记忆晚一点（下次准入/手动）再醒，不能拖垮准入主链路。
    """
    try:
        return store.wake_scope(scope_type, scope_id)
    except Exception:
        logger.warning(
            "[MemoryDecay] wake scope %s:%s failed", scope_type, scope_id, exc_info=True
        )
        return 0
