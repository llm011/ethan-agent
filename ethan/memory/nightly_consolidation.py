"""夜间统一沉淀（做梦）— run_nightly_consolidation。

做梦（daily_consolidation 的 insight 挖掘）与结构化每日沉淀
（structured_consolidation）本是同一职责的两个 job：都在午夜跑、都扫当日
session、都调 LLM、都写 memory.db。合并为单一编排入口：

1. **结构化每日沉淀**：当日 session 重提取 → 准入 → pending 跨 session 复评 →
   TTL 过期 → 按域日摘要
2. **做梦（insight 挖掘）**：同步最新 memories 为向量去重底库 → 当日信号
   LLM 精炼 → embedding 去重 → insight 入向量库 → 反写（结构化候选走准入 /
   success_path 走 playbook）

顺序有意为之：结构化先跑，当日新准入的记忆会进入第 2 步的去重底库，
insight 不会与刚提取的长期记忆重复反写。

两步各自保留独立的 consolidation_jobs 记录（幂等粒度不变），本入口只做编排；
单步失败不影响另一步，失败 job 下一夜自动重试。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


async def run_nightly_consolidation(target_date: date | None = None) -> dict[str, Any]:
    """对当前用户（ETHAN_USER_ID）执行一次完整的夜间沉淀。

    target_date 默认昨天（0 点触发时信号都是昨天白天产生的）。
    返回 {"date", "structured": {...}, "insights_added": int}。
    """
    from ethan.memory.daily_consolidation import run_daily_consolidation
    from ethan.memory.structured_consolidation import run_structured_consolidation

    d = target_date or (date.today() - timedelta(days=1))
    result: dict[str, Any] = {"date": d.isoformat(), "structured": {}, "insights_added": 0}

    # ① 结构化每日沉淀（重提取/复评/过期/日摘要）
    try:
        result["structured"] = await run_structured_consolidation(d)
    except Exception:
        logger.exception("[Nightly] structured consolidation failed for %s", d)
        result["structured"] = {"error": True}

    # ② 做梦：insight 挖掘（去重底库含 ① 刚准入的记忆）
    #     先全量重建 memory 向量索引（自愈迁移/手工编辑/forget 漂移），
    #     保证准入语义配对与混合召回的索引新鲜
    try:
        from ethan.memory.memory_vectors import reindex_all
        reindex_all()
    except Exception:
        logger.exception("[Nightly] memory vector reindex failed for %s", d)
    try:
        result["insights_added"] = await run_daily_consolidation(d)
    except Exception:
        logger.exception("[Nightly] dream/insight consolidation failed for %s", d)

    logger.info(
        "[Nightly] %s done: structured=%s insights_added=%d",
        d,
        {k: v for k, v in result["structured"].items() if k in ("candidates", "admitted", "skipped", "error")},
        result["insights_added"],
    )
    return result
