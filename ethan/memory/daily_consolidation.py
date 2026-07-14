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
from typing import TYPE_CHECKING

from ethan.core.paths import user_memory_dir

if TYPE_CHECKING:
    from ethan.memory.facts import FactStore

logger = logging.getLogger(__name__)

DEDUP_THRESHOLD = 0.85  # cosine similarity 阈值（供参考）
# sqlite-vec 返回 L2 距离；对归一化 384-dim 向量，同义句 L2 通常 0.8~1.1
# 使用 L2 < 1.1 作为去重门槛（对应 cosine_sim ≈ 0.4，但实际效果更好）
L2_DEDUP_THRESHOLD = 1.1

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

            # 反写到 facts.json / playbook.json（带 embedding 语义去重）
            try:
                if await _reflect_to_memory_files(text, emb, insight_type, d, item.get("metadata", {})):
                    # 更新 memory.db 标记
                    metadata["reflected"] = True
                    store.add(id=item_id, text=text, embedding=emb, metadata=metadata)
                    reflected += 1
            except Exception:
                logger.warning("[DailyConsolidation] Reflect failed for: %s", text[:50], exc_info=True)

    finally:
        store.close()

    logger.info("[DailyConsolidation] Reflected %d/%d insights to facts/playbook", reflected, added)
    return added


async def _reflect_to_memory_files(
    text: str,
    insight_emb: list[float],
    insight_type: str,
    d: date,
    raw_meta: dict,
) -> bool:
    """将 insight 反写到 facts.json 或 playbook.json。返回是否成功写入。

    反写前用 embedding 做语义去重，弥补 FactStore 中文 _find_similar 失效的问题。

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

        # 语义去重：用 embedding 检查 facts.json 中是否已有同义 fact
        if await _is_semantic_duplicate_in_facts(insight_emb, fact_store):
            logger.debug("[DailyConsolidation] Skip reflect (semantic dup in facts): %s", text[:50])
            return False

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


async def _is_semantic_duplicate_in_facts(
    insight_emb: list[float],
    fact_store: "FactStore",
) -> bool:
    """检查 facts.json 中是否已有与 insight 语义相同的 fact。

    FactStore._find_similar 对中文几乎失效（中文无空格，split 返回整句），
    所以这里用 embedding 做 L2 查重作为补充。

    遍历 active facts，对每条算 embedding 后比较 L2 距离。
    因为反写是低频操作（每晚 0 点一次），且 facts 通常只有几十条，成本可接受。
    """
    from ethan.memory.embeddings import embed

    active_facts = fact_store.get_active(min_confidence=0.0)
    for fact in active_facts:
        try:
            fact_emb = await embed(fact.content)
            # 算 L2 距离
            dist = sum((a - b) ** 2 for a, b in zip(insight_emb, fact_emb)) ** 0.5
            if dist < L2_DEDUP_THRESHOLD:
                return True
        except Exception:
            logger.warning("[DailyConsolidation] embed failed for fact: %s", fact.content[:50], exc_info=True)
            continue
    return False


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
