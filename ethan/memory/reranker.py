"""召回后重排 + 切点：宽召回的候选交 LLM 判官打分，按分数断层截断。

为什么需要这一层
--------------
第一阶段（`_collect`）是 BGE/RRF 宽召回，只保覆盖率不保精度。实测 1200 case：
recall 100%，但 P@k 42.6%、注入 prompt 的那一屏只有 14% 相关，平均掺 9.6 条噪声。
RRF 的分数是排名倒数（`1/(61+rank)`），与 query 相关性无关，**没有可切的断层**——
所以宽召回自己切不出好切点，只能靠 max_items 固定截断。

60-case A/B（tests/memory_eval/ab_rerank.py）实测：

    方法                 nDCG     P@k    P@all
    BGE/RRF 基线        0.680   38.9%   14.0%
    + LLM 判官重排      0.978   93.3%   14.0%

P@all 三行相同不是巧合：重排只改顺序不改集合，集合级 precision 对重排天然不变。
**prompt 噪声的下降全部来自切点，重排只是让切点有得可切。** 所以本模块的重点在
`pick_cut`，不在排序。

切点为什么是「最大断层」而不是固定阈值
----------------------------------
同一批候选上三种切点（opus-5 判官，60 case）：

    thr>=6    P=65.5%  R=100.0%  保留 3.0 条
    thr>=7    P=74.8%  R= 95.0%  保留 2.3 条
    maxgap    P=84.8%  R= 99.2%  保留 2.3 条   ← 同样条数，P 高 10 点、R 高 4 点

固定阈值假设「分数悬崖永远在 7 分」，但绝对分标定逐 query 漂移：库里没有强相关项
时 thr7 要么全砍要么放噪声进来。maxgap 找的是分数分布里的自然断层，不依赖标定。

但 maxgap 单用有两个洞，本模块都补了：
1. **永不返回空集**——全部同分时所有 gap 都是 0，取最早切点 → 保留 1 条。
   所以先用 `MIN_SCORE` 绝对下限滤掉「一条都不相关」的情况。
2. **全部相关时切得过狠**——survivors 全是 9 分，gap 全 0 仍会砍到 1 条。
   所以要求断层大于 `MIN_GAP` 才切，否则保留全部（受硬上限约束）。

判官 persona 必须显式放 system
--------------------------
2×2 实测（{haiku, opus-5} × {system, user-turn}，每格 N=8）：

    model              placement    ok  拒答  空  其他
    claude-haiku-4.5   system        8    0   0    0
    claude-haiku-4.5   user-turn     5    3   0    0
    new-api/opus-5     system        7    0   1    0
    new-api/opus-5     user-turn     7    0   0    1

**不传 system 才是触发拒答的那一侧。** 机制：某些网关在你不传 system 时会注入自己
的底座 persona，此时用户轮里突然出现「你是记忆相关性判官，只输出 JSON」相对那个底座
就是可疑的注入，模型会拒答（原文自称 Kiro 并指控 prompt injection）；显式传 system
时网关用你的，模型收到的是一致框架。

所以配置严格锁死成实测通过的那一种：**persona 放 `system=`，评分标准放 user 轮**。
两者不要合并、不要挪动——任何第三种组合都是未测配置。

但 system 放对不等于安全：同样配置这次 8/8 通过，60-case A/B 里 haiku 却拒答 14/60。
差别是候选内容（真实六域含 companion 情绪 vs 固定 5 条），**拒答率与内容相关**。
因此拒答必须当常态处理——解析失败重试一次，仍失败退回 RRF 原序。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# 开关与工作点。沿用 memory_vectors.py 的 env-var 常量写法。
# 默认关：判官在真实语料上的拒答率还没在干净通道上测过（见 docstring），
# 且切点常量 MIN_SCORE/MIN_GAP 尚未用生产代码本身做过 A/B 校准。
# 开启：ETHAN_MEMORY_RERANK=1
RERANK_ENABLED = os.environ.get("ETHAN_MEMORY_RERANK", "0") == "1"
# 空 = 用 lite_model（记忆压缩/标题生成同一档廉价模型）
RERANK_MODEL = os.environ.get("ETHAN_MEMORY_RERANK_MODEL", "")
# 解析失败后的重试次数。拒答/散文式输出是常态而非异常，见 docstring 末段。
RERANK_RETRIES = int(os.environ.get("ETHAN_MEMORY_RERANK_RETRIES", "1"))
# 绝对分下限：低于此分一律不注入，也是 maxgap 能返回空集的唯一途径
MIN_SCORE = float(os.environ.get("ETHAN_MEMORY_RERANK_MIN_SCORE", "4"))
# 断层阈值：最大相邻分差小于此值 = 分布里没有悬崖，不切
MIN_GAP = float(os.environ.get("ETHAN_MEMORY_RERANK_MIN_GAP", "2"))
# 硬上限：切点再宽也不超过这么多条
MAX_KEEP = int(os.environ.get("ETHAN_MEMORY_RERANK_MAX_KEEP", "5"))
# 候选少于此数不值得花一次 LLM 调用；且 pointwise 打分在候选过少时会退化
# （2 条候选时模型没有集合内比较基准，实测会给两条都打 10 分）
MIN_CANDIDATES = int(os.environ.get("ETHAN_MEMORY_RERANK_MIN_CAND", "4"))
# 判官总预算，**含重试**（wait_for 包住整个重试循环，不是每次调用各给一份）。
# 实测单次延迟 haiku 7.4s / opus-5 9.9s，30s 才装得下「一次 + 一次重试」；
# 给 20s 的话重试基本必被掐死，等于白加。
RERANK_TIMEOUT_S = float(os.environ.get("ETHAN_MEMORY_RERANK_TIMEOUT", "30"))

# persona 走 system，评分标准走 user 轮。这两条的**分工**是实测过的配置，
# 合并或对调都属于未测组合，见模块 docstring 的 2×2 表。
_JUDGE_SYSTEM = "你是记忆相关性判官，只输出 JSON 数组，不要解释。"

# 判官 provider 复用缓存：每次召回都 create_provider 会建新的 httpx client +
# curl_cffi session，调完不关就泄漏连接池（长跑进程 fd 缓涨）。按 model 缓存
# provider，跨召回复用同一连接池。绑定创建时的事件循环——换循环（测试/重连）
# 时丢弃重建，避免 "attached to a different loop"。
_provider_cache: dict[str, tuple[Any, Any]] = {}


async def _get_judge_provider(model: str) -> Any:
    """返回按 model 复用的判官 provider，绑定当前事件循环。"""
    import asyncio as _asyncio

    from ethan.providers.manager import create_provider

    loop = _asyncio.get_running_loop()
    cached = _provider_cache.get(model)
    if cached is not None:
        prov, bound_loop = cached
        if bound_loop is loop:
            return prov
        # 循环变了，旧 provider 绑死在旧循环上，关掉重建
        try:
            await prov.close()
        except Exception:
            pass
        _provider_cache.pop(model, None)
    prov = create_provider(model)
    _provider_cache[model] = (prov, loop)
    return prov


async def _close_judge_providers() -> None:
    """进程退出 / 测试 teardown 时调，关掉所有缓存的连接池。"""
    for model in list(_provider_cache):
        prov, _ = _provider_cache.pop(model)
        try:
            await prov.close()
        except Exception:
            pass


_INSTRUCTION = (
    "下面是一次记忆检索的结果。请判断每条记忆与用户 query 的相关性。\n"
    "打分标准：10=直接回答 query，5=相关但不直接回答，0=完全无关。\n"
    '只输出 JSON 数组，格式 [{"i":0,"score":9}]，每条候选都要给分，不要解释。'
)

_SCORE_RE = re.compile(r'"i"\s*:\s*(\d+)\s*,\s*"score"\s*:\s*(-?\d+(?:\.\d+)?)')
_SCORE_RE_REV = re.compile(r'"score"\s*:\s*(-?\d+(?:\.\d+)?)\s*,\s*"i"\s*:\s*(\d+)')


def build_prompt(query: str, memories: list[Any]) -> str:
    lines = "".join(
        f"{i}. [{getattr(m, 'dimension', '?')}] {m.content}\n" for i, m in enumerate(memories)
    )
    return f"{_INSTRUCTION}\n\n用户 query: {query}\n\n候选记忆：\n{lines}"


def parse_scores(text: str) -> dict[int, float]:
    """从判官返回里抽 {候选下标: 分数}，三层容错，全失败返回空 dict。

    实测的失败形态：包 ```json fence、JSON 前后带解释、尾随逗号、字段顺序反转、
    响应截断。第 3 层正则不要求整段是合法 JSON——逐对抽 i/score，单个语法错不会
    让整次重排作废（作废 = 退回 RRF 原序，白花一次调用）。
    """
    out: dict[int, float] = {}

    def _absorb(arr: Any) -> None:
        for item in arr or []:
            try:
                out[int(item["i"])] = float(item["score"])
            except Exception:
                continue

    # 1) 首尾方括号之间当数组——同时吃掉 code fence 和前后解释文本
    try:
        _absorb(json.loads(text[text.index("[") : text.rindex("]") + 1]))
    except Exception:
        pass
    if out:
        return out
    # 2) 整段当 JSON，兼容 {"scores": [...]} 这种包一层的
    try:
        payload = json.loads(text.strip().strip("`"))
        _absorb(payload.get("scores") if isinstance(payload, dict) else payload)
    except Exception:
        pass
    if out:
        return out
    # 3) 正则逐对抽，容忍尾随逗号 / 截断 / 字段顺序反转
    for m in _SCORE_RE.finditer(text):
        out[int(m.group(1))] = float(m.group(2))
    for m in _SCORE_RE_REV.finditer(text):
        out.setdefault(int(m.group(2)), float(m.group(1)))
    return out


def pick_cut(scores: list[float]) -> int:
    """给降序分数列表选切点，返回保留条数（0 = 一条都不留）。

    顺序固定：绝对下限 → 最大断层 → 硬上限。三步各自防一种失效模式，见模块 docstring。
    """
    survivors = [s for s in scores if s >= MIN_SCORE]
    if not survivors:
        return 0
    keep = len(survivors)
    if keep >= 2:
        gaps = [(survivors[i] - survivors[i + 1], i + 1) for i in range(keep - 1)]
        # 同分差时取更靠前的切点（更保守）；断层不够大就不切
        gap, cut = max(gaps, key=lambda g: (g[0], -g[1]))
        if gap >= MIN_GAP:
            keep = cut
    return min(keep, MAX_KEEP)


async def _score_candidates(query: str, memories: list[Any], model: str,
                            retries: int = RERANK_RETRIES) -> dict[int, float]:
    """打分并解析，失败重试。空 dict = 重试后仍解析不出。

    persona 走 `system=`、评分标准走 user 轮——这个组合是 2×2 实测通过的那一种，
    不要改动（见模块 docstring）。
    """
    from ethan.providers.base import Message

    provider = await _get_judge_provider(model)
    prompt = build_prompt(query, memories)
    last_bad = ""

    for attempt in range(retries + 1):
        msgs = [Message(role="user", content=prompt)]
        if attempt:
            # 把上一次的坏输出回灌再纠格式，比原样重发更容易拉回来
            msgs.append(Message(role="assistant", content=last_bad[:500]))
            msgs.append(Message(role="user", content=(
                f"格式不对，没解析出分数。只输出 JSON 数组，{len(memories)} 条候选每条一项，"
                '形如 [{"i":0,"score":9}]，不要 code fence、不要解释。')))
        resp = await provider.chat(msgs, system=_JUDGE_SYSTEM)
        text = resp.content or ""
        scores = parse_scores(text)
        if scores:
            return scores
        last_bad = text
        logger.debug("memory rerank: 第 %d 次解析失败 raw=%r", attempt + 1, text[:200])
    return {}


async def rerank_and_cut(
    query: str, memories: list[Any], *, model: str = "",
    fallback: list[Any] | None = None,
) -> list[Any]:
    """重排候选并截断。任何失败都返回 `fallback`（默认为原样候选）。

    `fallback` 由调用方给出、且应当与改造前的注入结果**逐条一致**——判官不可用
    （关闭、离线、无额度、网关拒答）时行为必须退回改造前，而不是把宽召回的候选
    预算原样灌进 prompt，那比改造前更糟。fallback 的语义是"不改善"，不是"变差"。

    截断逻辑留给调用方而非本函数：注入上限是逐 domain 算的（companion 模式下
    general 和 companion 各占一份额度），reranker 看到的是并集，没有域信息。
    """
    fb = memories if fallback is None else fallback
    # 三种跳过：关闭、无 query（此时 _collect 走的是 importance 兜底，没有可判的
    # 相关性）、候选太少不值得一次调用（pointwise 打分在候选过少时会退化——2 条
    # 候选时模型没有集合内比较基准，实测两条都给 10 分）。
    if not RERANK_ENABLED or not query.strip() or len(memories) < MIN_CANDIDATES:
        return fb

    # 显式入参 > ETHAN_MEMORY_RERANK_MODEL > lite_model。
    # 中间那档是 Phase 2 选型结束后填默认值的地方；在有干净通道的实测数据之前
    # 不硬编码模型名，先跟随 lite_model。
    model = model or RERANK_MODEL
    if not model:
        try:
            from ethan.memory.consolidator import get_lite_model

            model = get_lite_model()
        except Exception:
            logger.debug("memory rerank: lite model 解析失败", exc_info=True)
            return fb

    try:
        # wait_for 包住**整个重试循环**，总耗时受 RERANK_TIMEOUT_S 约束，
        # 不会退化成 retries+1 份超时预算。
        scored = await asyncio.wait_for(
            _score_candidates(query, memories, model), timeout=RERANK_TIMEOUT_S
        )
    except Exception:
        logger.debug("memory rerank: 判官调用失败，退回 RRF 原序", exc_info=True)
        return fb

    if not scored:
        logger.debug("memory rerank: 判官输出重试后仍无法解析，退回 RRF 原序")
        return fb

    # 判官漏打分的候选按 -1 排到末尾，等于"判官没表态就别注入"；
    # 同分时按原 RRF 次序稳定排列（sorted 是稳定的，原列表已是 RRF 序）
    order = sorted(range(len(memories)), key=lambda i: -scored.get(i, -1.0))
    ranked_scores = [scored.get(i, -1.0) for i in order]
    keep = pick_cut(ranked_scores)

    # 判官全砍（pick_cut 返回 0，所有候选 < MIN_SCORE）。身份类事实缺一条比多几条
    # 噪声更贵（PR 注释），且 docstring 约定"任何失败都返回 fallback"。全砍不算失败，
    # 但空召回的代价更高——调用方显式传了 fallback（shallow，逐域 6+6）时就回退它的
    # top-1，保住最该注入的一条；没传 fallback 才返回空（保留 MIN_SCORE 的语义）。
    if keep == 0:
        if fallback is not None:
            logger.info("[memory-rerank] model=%s 判官全砍 keep=0，回退 fallback top-1", model)
            return fb[:1]
        return []

    kept_idx = order[:keep]
    # 域配额：并集重排只在两域上做一次（保持单一分数分布、单一断层，见 recall.py
    # docstring），但并集一刀切会让低分域（companion 情绪类普遍低于 general 事实类）
    # 整段出局。这里补一个逐域硬保证：输入里出现的每个域至少保住其最高分那条
    # （score < MIN_SCORE 的域除外），避免 companion 被砍光。
    top_idx_by_domain: dict[str, int] = {}
    for i, score in zip(order, ranked_scores):
        domain = getattr(memories[i], "memory_domain", "general")
        if domain not in top_idx_by_domain and score >= MIN_SCORE:
            top_idx_by_domain[domain] = i
    kept_set = set(kept_idx)
    for i in top_idx_by_domain.values():
        if i not in kept_set:
            kept_idx.append(i)
            kept_set.add(i)
    kept = [memories[i] for i in kept_idx]
    logger.info(
        "[memory-rerank] model=%s 候选=%d 保留=%d 分数=%s",
        model, len(memories), len(kept), [round(s, 1) for s in ranked_scores[:8]],
    )
    return kept
