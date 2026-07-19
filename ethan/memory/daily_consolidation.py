"""每日记忆沉淀 — 从当日结构化记忆挖掘 insight、LLM 精炼、embedding 去重后写入 memory.db。

每晚 0 点由 heartbeat 触发。流程：
1. 从 memory.db 读取当日准入的结构化记忆（最多 15 条），替代旧的 daily/*.jsonl 信号
2. LLM 模式挖掘（从多条记忆归纳行为模式/成功路径，限 ≤10 条）
3. 对精炼结果做 embedding → 在 memory.db 里查 L2 < 阈值的 → skip 已存在
4. 通过去重的条目写入 memory.db（insight_* 向量条目），并按 type 反写：
   - success_path → playbook.json 的 success_patterns（其它类型不反写）
5. memory.db 的 metadata 标记 reflected=True，避免重复反写
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

DEDUP_THRESHOLD = 0.85  # cosine similarity 阈值（供参考）
# sqlite-vec 返回 L2 距离；对 BGE-small-zh INT8 归一化 512-dim 向量：
#   同义改写 L2 通常 0.56~0.81（均值 0.69）
#   相似但不同主题 L2 通常 0.65~0.95（均值 0.78）
#   完全无关 L2 通常 > 1.1
# 取 0.7 作为去重门槛（cos ≈ 0.755）：能去掉明显的同义重复，同时保留大部分独特内容。
# 漏判代价低（多存几条），误判代价高（丢独特 insight 不可恢复），偏保守。
L2_DEDUP_THRESHOLD = 0.7

# 反写为结构化候选的 confidence：低于主动写入(0.95)
# 因为是跨 session 统计推断，不是确定性事实
INSIGHT_CONFIDENCE = 0.75

def _memory_db_path() -> Path:
    """每次调用时按当前 user contextvar 求值，避免模块级缓存击穿 per-user 隔离。"""
    # 必须用 user_vectors_db_path()，与 MemoryStore/memory_vectors 同库（db/memory.db）
    from ethan.core.paths import user_vectors_db_path
    return user_vectors_db_path()

_CONSOLIDATION_PROMPT = """\
以下是今天提取并准入的结构化记忆（已通过 5 轮实时抽取 + 准入策略筛选）。请从中挖掘跨记忆的行为模式和成功路径，生成可复用的 playbook 经验。

要求：
- 从多条记忆中归纳出反复出现的成功模式（场景 + 方法）
- 合并语义相似的条目
- 排除噪音（过于泛泛的、一次性的、不值得固化为 playbook 的）
- 最终输出不超过 10 条
- 每条是一句完整的、自包含的描述（未来召回时能独立理解）
- 宁缺勿滥，如果今天的记忆没有值得提炼的成功路径，输出空数组 []

输出格式（严格 JSON 数组）：
```json
[
  {{"type": "success_path", "text": "成功场景描述", "metadata": {{...原始关键信息...}}}}
]
```

今日结构化记忆：
{signals_text}
"""


async def _read_day_memories(d: date) -> list[dict]:
    """从 memory.db 读取当日准入的结构化记忆（最多 15 条），作为做梦的输入。

    替代旧的 read_signals_by_date（读 daily/*.jsonl）。输入源从文件改为 DB，
    消除存储分裂：5 轮实时抽取写 memory.db → 12 点做梦直接读 memory.db。
    """
    from datetime import datetime, timedelta

    from ethan.core.timezone import get_local_timezone
    from ethan.memory.records import MemoryStatus
    from ethan.memory.store import MemoryStore

    tz = get_local_timezone()
    start = datetime(d.year, d.month, d.day, tzinfo=tz)
    end = start + timedelta(days=1)
    start_ts, end_ts = start.timestamp(), end.timestamp()

    store = MemoryStore(db_path=_memory_db_path())
    try:
        # MemoryStore.list_memories() 暂不支持按 created_at 时间范围过滤，故走底层 SQL；
        # 待 MemoryStore 扩展时间范围参数后可改回封装接口。
        rows = store._get_conn().execute(
            "SELECT * FROM memories WHERE status=? AND created_at >= ? AND created_at < ? "
            "ORDER BY created_at DESC LIMIT 15",
            (MemoryStatus.ACTIVE.value, start_ts, end_ts),
        ).fetchall()
        memories = [store._record_from_row(r) for r in rows]
        return [
            {
                "type": "memory",
                "text": m.content,
                "metadata": {
                    "memory_type": m.memory_type,
                    "dimension": m.dimension,
                    "source_session_id": m.source_session_id,
                },
            }
            for m in memories
        ]
    finally:
        store.close()


async def run_daily_consolidation(target_date: date | None = None) -> int:
    """执行每日记忆沉淀。返回新写入 memory.db 的条目数。

    target_date: 指定处理哪天。不传时默认处理"昨天"——因为 0 点触发时
    date.today() 已是今天，而记忆是在"昨天"白天产生的。
    """
    from datetime import timedelta

    d = target_date or (date.today() - timedelta(days=1))
    signals = await _read_day_memories(d)

    if not signals:
        logger.info("[DailyConsolidation] No memories for %s, skipping", d)
        return 0

    # Step 0: 同步 memories 表/playbook.json 内容到向量库（让 insight 去重覆盖已有记忆）
    await _sync_corpus_to_memory_db()

    # Step 1: LLM 整理去重
    refined = await _llm_refine(signals)
    if not refined:
        logger.info("[DailyConsolidation] LLM refined to 0 items, skipping")
        return 0

    # Step 2: Embedding 去重 + 写入 + 反写
    added = await _embed_and_store(refined, d)
    logger.info("[DailyConsolidation] Date=%s, raw=%d, refined=%d, stored=%d",
                d, len(signals), len(refined), added)
    return added


async def _llm_refine(signals: list[dict]) -> list[dict]:
    """用 lite 模型精炼信号。"""
    try:
        from ethan.memory.consolidator import get_lite_model
        from ethan.providers.base import Message
        from ethan.providers.manager import create_provider

        signals_text = json.dumps(signals, ensure_ascii=False, indent=2)
        prompt = _CONSOLIDATION_PROMPT.format(signals_text=signals_text)

        model = get_lite_model()
        provider = create_provider(model)
        resp = await provider.chat(
            [Message(role="user", content=prompt)],
            system="你是记忆整理工具。严格按 JSON 格式输出，不要输出解释文字。",
        )

        raw = (resp.content or "").strip()
        if "```" in raw:
            import re
            match = re.search(r"```(?:json)?\s*\n?(.*?)```", raw, re.DOTALL)
            if match:
                raw = match.group(1).strip()

        items = json.loads(raw)
        if not isinstance(items, list):
            return []

        # 验证格式
        valid = []
        for item in items:
            if isinstance(item, dict) and "text" in item and "type" in item:
                valid.append(item)
        return valid[:10]

    except Exception:
        logger.warning("[DailyConsolidation] LLM refinement failed", exc_info=True)
        return []


async def _embed_and_store(items: list[dict], d: date) -> int:
    """对每条做 embedding，去重后写入 memory.db，并按 type 反写。

    success_path → playbook.json 的 success_patterns；其它类型仅入库不反写。
    """
    from ethan.memory.embeddings import embed
    from ethan.memory.vector_store import VectorStore

    store = VectorStore(db_path=_memory_db_path())
    added = 0
    reflected = 0

    try:
        for item in items:
            text = item["text"]
            emb = await embed(text)

            # 检查是否已存在相似记忆（去重时不算访问，不更新 last_accessed）
            existing = store.search(query_embedding=emb, limit=1, update_access=False)
            # sqlite-vec 返回 L2 距离；L2 < L2_DEDUP_THRESHOLD 视为重复
            if existing and existing[0]["distance"] < L2_DEDUP_THRESHOLD:
                logger.debug("[DailyConsolidation] Skipping duplicate: %s (L2=%.3f)",
                             text[:50], existing[0]["distance"])
                continue

            # 写入 memory.db
            item_id = f"insight_{d.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
            insight_type = item.get("type", "unknown")
            metadata = {
                "type": insight_type,
                "date": d.isoformat(),
                "created_at": time.time(),
                "reflected": False,  # 标记是否已反写到 memories 表/playbook.json
            }
            # 保留原始 metadata
            if "metadata" in item and isinstance(item["metadata"], dict):
                extra = {k: v for k, v in item["metadata"].items() if k not in metadata}
                metadata.update(extra)

            store.add(id=item_id, text=text, embedding=emb, metadata=metadata)
            added += 1

            # 反写（结构化候选 / playbook）
            # 去重已由 _sync_corpus_to_memory_db 保证：memories 的 active 记忆
            # 已同步进向量库（type=fact_sync），insight 的 L2 去重天然覆盖
            try:
                if _reflect_insight(text, insight_type, d, item.get("metadata", {})):
                    # 更新 memory.db 标记（用 update_metadata 避免 vec_index REPLACE 冲突）
                    metadata["reflected"] = True
                    store.update_metadata(id=item_id, metadata=metadata)
                    reflected += 1
            except Exception:
                logger.warning("[DailyConsolidation] Reflect failed for: %s", text[:50], exc_info=True)

    finally:
        store.close()

    logger.info("[DailyConsolidation] Reflected %d/%d insights to memories/playbook", reflected, added)
    return added


async def _sync_corpus_to_memory_db() -> int:
    """把 memories 表 active 记忆 / playbook.json 的内容同步到向量库（type=fact_sync）。

    同步后，insight 的 L2 去重天然覆盖已有记忆——不需要手动遍历算 embedding。

    策略：先删旧的 fact_sync 条目，再全量重建。保证向量库跟源数据一致。
    fact_sync 条目不参与 LRU 过期（由本函数全量重建）。
    """
    from ethan.core.paths import user_procedures_path
    from ethan.memory.embeddings import embed
    from ethan.memory.procedures import ProcedureStore
    from ethan.memory.records import MemoryDomain, MemoryStatus
    from ethan.memory.store import MemoryStore
    from ethan.memory.vector_store import VectorStore

    store = VectorStore(db_path=_memory_db_path())
    synced = 0

    try:
        # Step 1: 删旧的 fact_sync 条目（全量重建）—— 走公开 API，不触碰 _get_conn
        deleted = store.delete_by_type("fact_sync")
        if deleted:
            logger.debug("[DailyConsolidation] Cleared %d old fact_sync entries", deleted)

        # Step 2: 同步 memories 表的 active 记忆（general 域；companion 域不参与 insight 去重）
        mem_store = MemoryStore(db_path=_memory_db_path())
        try:
            active_memories = mem_store.list_memories(
                memory_domain=MemoryDomain.GENERAL.value,
                status=MemoryStatus.ACTIVE.value,
                limit=5000,
            )
        finally:
            mem_store.close()
        for mem in active_memories:
            try:
                emb = await embed(mem.content)
                item_id = f"fact_sync_{uuid.uuid4().hex[:12]}"
                metadata = {
                    "type": "fact_sync",
                    "source": mem.id,
                    "category": mem.memory_type,
                    "confidence": mem.confidence,
                    "synced_at": time.time(),
                }
                store.add(id=item_id, text=mem.content, embedding=emb, metadata=metadata)
                synced += 1
            except Exception:
                logger.warning("[DailyConsolidation] Sync memory failed: %s", mem.content[:50], exc_info=True)

        # Step 3: 同步 playbook.json 的 success_pattern
        proc_store = ProcedureStore(path=user_procedures_path())
        for sp in proc_store.all_success_patterns():
            try:
                emb = await embed(sp.scenario)
                item_id = f"playbook_sync_{uuid.uuid4().hex[:12]}"
                metadata = {
                    "type": "fact_sync",
                    "source": "playbook",
                    "scenario": sp.scenario,
                    "success_count": sp.success_count,
                    "synced_at": time.time(),
                }
                store.add(id=item_id, text=sp.scenario, embedding=emb, metadata=metadata)
                synced += 1
            except Exception:
                logger.warning("[DailyConsolidation] Sync playbook failed: %s", sp.scenario[:50], exc_info=True)

    finally:
        store.close()

    logger.info("[DailyConsolidation] Synced %d memory/playbook entries to vector store", synced)
    return synced


def _reflect_insight(
    text: str,
    insight_type: str,
    d: date,
    raw_meta: dict,
) -> bool:
    """将 insight 反写到结构化记忆管道或 playbook.json。返回是否成功写入。

    去重已由 _sync_corpus_to_memory_db 保证：memories 表的 active 记忆已同步进
    向量库（type=fact_sync），insight 的 L2 去重天然覆盖已有记忆。

    - success_path → playbook.json 的 success_patterns
    - 其它类型不反写
    """
    from ethan.core.paths import user_procedures_path
    from ethan.memory.procedures import ProcedureStore

    if insight_type == "success_path":
        # 反写到 playbook.json 的 success_patterns
        proc_store = ProcedureStore(path=user_procedures_path())
        # 从 raw_meta 提取 tool_sequence，没有则空列表
        tool_sequence = raw_meta.get("tool_sequence", []) if isinstance(raw_meta, dict) else []
        scenario = text  # insight text 本身作为 scenario 描述
        proc_store.add_success_pattern(scenario=scenario, tool_sequence=tool_sequence)
        logger.debug("[DailyConsolidation] Reflected to playbook.json: %s", text[:50])
        return True

    return False


async def get_all_memories(limit: int = 20, offset: int = 0) -> dict:
    """分页获取所有永久记忆（从 memory.db），过滤掉 fact_sync 同步条目。"""
    from ethan.memory.vector_store import VectorStore

    store = VectorStore(db_path=_memory_db_path())
    try:
        total = store.count_items(exclude_types=["fact_sync", "memory"])
        items = store.list_items(exclude_types=["fact_sync", "memory"], limit=limit, offset=offset)
        return {"total": total, "items": items, "limit": limit, "offset": offset}
    finally:
        store.close()


async def get_memories_by_date(d: date) -> list[dict]:
    """获取某日沉淀的记忆，过滤掉 fact_sync 同步条目。"""
    from ethan.memory.vector_store import VectorStore

    store = VectorStore(db_path=_memory_db_path())
    try:
        return store.list_items(
            exclude_types=["fact_sync", "memory"],
            date=d.isoformat(),
            limit=100,
            offset=0,
        )
    finally:
        store.close()
