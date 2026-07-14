"""每日记忆沉淀 — 整理当日信号、LLM 去重、embedding 去重后写入 memory.db。

每晚 0 点由 heartbeat 触发。流程：
1. 读取当日 daily/<YYYYMMDD>.jsonl
2. LLM 整理去重（合并相似、排除噪音，限 ≤10 条）
3. 对精炼结果做 embedding → 在 memory.db 里查相似度 > 0.85 的 → skip 已存在
4. 通过去重的条目写入 memory.db（永久保留）
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import date
from pathlib import Path

from ethan.core.paths import user_memory_dir

logger = logging.getLogger(__name__)

DEDUP_THRESHOLD = 0.85  # cosine similarity 阈值（供参考）
# sqlite-vec 返回 L2 距离；对归一化 384-dim 向量，同义句 L2 通常 0.8~1.1
# 使用 L2 < 1.1 作为去重门槛（对应 cosine_sim ≈ 0.4，但实际效果更好）
L2_DEDUP_THRESHOLD = 1.1


def _memory_db_path() -> Path:
    """每次调用时按当前 user contextvar 求值，避免模块级缓存击穿 per-user 隔离。"""
    return user_memory_dir() / "memory.db"

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
    """执行每日记忆沉淀。返回新写入 memory.db 的条目数。"""
    from ethan.memory.daily_signals import read_signals_by_date, read_today_signals

    d = target_date or date.today()
    signals = read_signals_by_date(d) if target_date else read_today_signals()

    if not signals:
        logger.info("[DailyConsolidation] No signals for %s, skipping", d)
        return 0

    # Step 1: LLM 整理去重
    refined = await _llm_refine(signals)
    if not refined:
        logger.info("[DailyConsolidation] LLM refined to 0 items, skipping")
        return 0

    # Step 2: Embedding 去重 + 写入
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
    """对每条做 embedding，去重后写入 memory.db。"""
    from ethan.memory.embeddings import embed
    from ethan.memory.vector_store import VectorStore

    store = VectorStore(db_path=_memory_db_path())
    added = 0

    try:
        for item in items:
            text = item["text"]
            emb = await embed(text)

            # 检查是否已存在相似记忆
            existing = store.search(query_embedding=emb, limit=1)
            # sqlite-vec 返回 L2 距离；L2 < L2_DEDUP_THRESHOLD 视为重复
            if existing and existing[0]["distance"] < L2_DEDUP_THRESHOLD:
                logger.debug("[DailyConsolidation] Skipping duplicate: %s (L2=%.3f)",
                             text[:50], existing[0]["distance"])
                continue

            # 写入
            item_id = f"insight_{d.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
            metadata = {
                "type": item.get("type", "unknown"),
                "date": d.isoformat(),
                "created_at": time.time(),
            }
            # 保留原始 metadata
            if "metadata" in item and isinstance(item["metadata"], dict):
                metadata.update(item["metadata"])

            store.add(id=item_id, text=text, embedding=emb, metadata=metadata)
            added += 1

    finally:
        store.close()

    return added


async def get_all_memories(limit: int = 20, offset: int = 0) -> dict:
    """分页获取所有永久记忆（从 memory.db）。"""
    from ethan.memory.vector_store import VectorStore

    store = VectorStore(db_path=_memory_db_path())
    try:
        conn = store._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM vec_items").fetchone()[0]
        rows = conn.execute(
            "SELECT id, text, metadata FROM vec_items ORDER BY rowid DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()

        items = []
        for row in rows:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            items.append({
                "id": row["id"],
                "text": row["text"],
                "metadata": meta,
            })

        return {"total": total, "items": items, "limit": limit, "offset": offset}
    finally:
        store.close()


async def get_memories_by_date(d: date) -> list[dict]:
    """获取某日沉淀的记忆。"""
    from ethan.memory.vector_store import VectorStore

    store = VectorStore(db_path=_memory_db_path())
    try:
        conn = store._get_conn()
        date_str = d.isoformat()
        rows = conn.execute(
            "SELECT id, text, metadata FROM vec_items WHERE json_extract(metadata, '$.date') = ?",
            (date_str,),
        ).fetchall()

        items = []
        for row in rows:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            items.append({
                "id": row["id"],
                "text": row["text"],
                "metadata": meta,
            })
        return items
    finally:
        store.close()
