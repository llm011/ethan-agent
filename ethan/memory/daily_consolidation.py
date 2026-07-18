"""每日记忆沉淀 — 整理当日信号、LLM 去重、embedding 去重后写入 memory.db。

每晚 0 点由 heartbeat 触发。流程：
1. 读取当日 daily/<YYYYMMDD>.jsonl
2. LLM 整理去重（合并相似、排除噪音，限 ≤10 条）
3. 对精炼结果做 embedding → 在 memory.db 里查 L2 < 1.1 的 → skip 已存在
4. 通过去重的条目写入 memory.db，并按 type 反写到 facts.json / playbook.json
   - repetition / error → facts.json（confidence=0.75, source=insight_<date>）
   - success_path → playbook.json 的 success_patterns
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

# 反写到 facts.json 的 confidence：低于后台抽取(0.8)和主动写入(0.95)
# 因为是跨 session 统计推断，不是确定性事实
INSIGHT_CONFIDENCE = 0.75

# type → category 映射（反写到 facts.json 时用）
TYPE_CATEGORY_MAP = {
    "repetition": "preference",   # 重复行为模式 → 偏好
    "error": "correction",        # 错误纠正 → correction
}


def _memory_db_path() -> Path:
    """每次调用时按当前 user contextvar 求值，避免模块级缓存击穿 per-user 隔离。"""
    # 必须用 user_vectors_db_path()，与 MemoryStore/memory_vectors 同库（db/memory.db）
    from ethan.core.paths import user_vectors_db_path
    return user_vectors_db_path()

_CONSOLIDATION_PROMPT = """\
以下是今天记录的行为模式信号（可能有重复或噪音）。请整理为最终要永久保留的记忆条目。

要求：
- 合并语义相似的条目
- 排除噪音（过于泛泛的、一次性的、不值得长期记住的）
- 最终输出不超过 10 条
- 每条是一句完整的、自包含的描述（未来召回时能独立理解）
- 宁缺勿滥，如果今天的信号都不值得保留，输出空数组 []

输出格式（严格 JSON 数组）：
```json
[
  {{"type": "repetition|error|success_path", "text": "精炼后的记忆描述", "metadata": {{...原始关键信息...}}}}
]
```

今日原始信号：
{signals_text}
"""


async def run_daily_consolidation(target_date: date | None = None) -> int:
    """执行每日记忆沉淀。返回新写入 memory.db 的条目数。

    target_date: 指定处理哪天的信号。不传时默认处理"昨天"——因为 0 点触发时
    date.today() 已是今天，而信号是在"昨天"白天产生的。
    """
    from datetime import timedelta

    from ethan.memory.daily_signals import read_signals_by_date
    d = target_date or (date.today() - timedelta(days=1))
    signals = read_signals_by_date(d)

    if not signals:
        logger.info("[DailyConsolidation] No signals for %s, skipping", d)
        return 0

    # Step 0: 同步 facts.json/playbook.json 到 memory.db（让 insight 去重时覆盖已有 fact）
    await _sync_facts_to_memory_db()

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
    """对每条做 embedding，去重后写入 memory.db，并反写到 facts.json / playbook.json。"""
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
                "reflected": False,  # 标记是否已反写到 facts.json/playbook.json
            }
            # 保留原始 metadata
            if "metadata" in item and isinstance(item["metadata"], dict):
                extra = {k: v for k, v in item["metadata"].items() if k not in metadata}
                metadata.update(extra)

            store.add(id=item_id, text=text, embedding=emb, metadata=metadata)
            added += 1

            # 反写到 facts.json / playbook.json
            # 去重已由 _sync_facts_to_memory_db 保证：facts.json 的 active fact
            # 已同步进 memory.db（type=fact_sync），insight 的 L2 去重天然覆盖
            try:
                if _reflect_to_memory_files(text, insight_type, d, item.get("metadata", {})):
                    # 更新 memory.db 标记（用 update_metadata 避免 vec_index REPLACE 冲突）
                    metadata["reflected"] = True
                    store.update_metadata(id=item_id, metadata=metadata)
                    reflected += 1
            except Exception:
                logger.warning("[DailyConsolidation] Reflect failed for: %s", text[:50], exc_info=True)

    finally:
        store.close()

    logger.info("[DailyConsolidation] Reflected %d/%d insights to facts/playbook", reflected, added)
    return added


async def _sync_facts_to_memory_db() -> int:
    """把 facts.json / playbook.json 的 active 内容同步到 memory.db。

    同步后，insight 的 L2 去重天然覆盖已有 fact——不需要手动遍历算 embedding。

    策略：先删旧的 fact_sync 条目，再全量写入。保证 memory.db 跟 JSON 文件一致。
    fact_sync 条目不参与 LRU 过期（由本函数全量重建）。
    """
    from ethan.core.paths import user_facts_path, user_procedures_path
    from ethan.memory.embeddings import embed
    from ethan.memory.facts import FactStore
    from ethan.memory.procedures import ProcedureStore
    from ethan.memory.vector_store import VectorStore

    store = VectorStore(db_path=_memory_db_path())
    synced = 0

    try:
        # Step 1: 删旧的 fact_sync 条目（全量重建）—— 走公开 API，不触碰 _get_conn
        deleted = store.delete_by_type("fact_sync")
        if deleted:
            logger.debug("[DailyConsolidation] Cleared %d old fact_sync entries", deleted)

        # Step 2: 同步 facts.json 的 active fact
        fact_store = FactStore(path=user_facts_path())
        for fact in fact_store.get_active(min_confidence=0.0):
            try:
                emb = await embed(fact.content)
                item_id = f"fact_sync_{uuid.uuid4().hex[:12]}"
                metadata = {
                    "type": "fact_sync",
                    "source": fact.source,
                    "category": fact.category,
                    "confidence": fact.confidence,
                    "synced_at": time.time(),
                }
                store.add(id=item_id, text=fact.content, embedding=emb, metadata=metadata)
                synced += 1
            except Exception:
                logger.warning("[DailyConsolidation] Sync fact failed: %s", fact.content[:50], exc_info=True)

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

    logger.info("[DailyConsolidation] Synced %d fact/playbook entries to memory.db", synced)
    return synced


def _reflect_to_memory_files(
    text: str,
    insight_type: str,
    d: date,
    raw_meta: dict,
) -> bool:
    """将 insight 反写到 facts.json 或 playbook.json。返回是否成功写入。

    去重已由 _sync_facts_to_memory_db 保证：facts.json 的 active fact 已同步进
    memory.db（type=fact_sync），insight 的 L2 去重天然覆盖已有 fact。

    - repetition / error → facts.json（confidence=0.75, source=insight_<date>）
    - success_path → playbook.json 的 success_patterns
    - 其它类型不反写
    """
    from ethan.core.paths import user_facts_path, user_procedures_path
    from ethan.memory.facts import FactStore
    from ethan.memory.procedures import ProcedureStore

    source_tag = f"insight_{d.isoformat()}"

    if insight_type in TYPE_CATEGORY_MAP:
        # 反写到 facts.json
        category = TYPE_CATEGORY_MAP[insight_type]
        fact_store = FactStore(path=user_facts_path())
        fact_store.add(
            content=text,
            confidence=INSIGHT_CONFIDENCE,
            source=source_tag,
            category=category,
        )
        logger.debug("[DailyConsolidation] Reflected to facts.json: %s", text[:50])
        return True

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
        total = store.count_items(exclude_types=["fact_sync"])
        items = store.list_items(exclude_types=["fact_sync"], limit=limit, offset=offset)
        return {"total": total, "items": items, "limit": limit, "offset": offset}
    finally:
        store.close()


async def get_memories_by_date(d: date) -> list[dict]:
    """获取某日沉淀的记忆，过滤掉 fact_sync 同步条目。"""
    from ethan.memory.vector_store import VectorStore

    store = VectorStore(db_path=_memory_db_path())
    try:
        return store.list_items(
            exclude_types=["fact_sync"],
            date=d.isoformat(),
            limit=100,
            offset=0,
        )
    finally:
        store.close()
