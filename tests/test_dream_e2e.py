"""端到端测试：mock 当日 memories → 手动触发"做梦"→ 验证记忆沉淀。

"做梦" = nightly dream = run_daily_consolidation，是 ethan 在每晚 0 点整理
当日信号、去重、写入 memory.db 向量库的过程，模拟人做梦时大脑整理记忆的机制。

注：success_path → playbook.json 反写链路已于 2026-07 退役。
insight 现仅作为向量条目入库，不反写 memories 表或 playbook。

本测试不调真实 LLM（mock _llm_refine 返回固定结果），embedding 走 _hash_embed
（纯本地 sha256 字符 n-gram，确定性，相同文本向量相同）。
"""
import json
from datetime import date
from unittest.mock import patch

import pytest

from ethan.core.context import ETHAN_USER_ID

# 项目用 anyio 插件跑 async 测试（非 pytest-asyncio）
pytestmark = pytest.mark.anyio


# ── fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_fs(tmp_path):
    """隔离 CONFIG_DIR + reset ETHAN_USER_ID，所有 user_*_path() 落到 tmp_path。"""
    token = ETHAN_USER_ID.set("")
    # paths.py 在模块加载时 `from ethan.core.config import CONFIG_DIR`，
    # 所以必须 patch paths 模块里的 CONFIG_DIR 名字才生效
    with patch("ethan.core.paths.CONFIG_DIR", tmp_path), \
         patch("ethan.core.config.CONFIG_DIR", tmp_path):
        yield tmp_path
    ETHAN_USER_ID.reset(token)


@pytest.fixture(autouse=True)
def force_hash_embed():
    """禁用 sentence-transformers，强制走 _hash_embed（离线、确定性）。"""
    import ethan.memory.embeddings as emb
    emb._encoder = None
    emb._encoder_checked = True
    yield


def _seed_memory(content: str, *, confidence: float = 0.9):
    """直接往 memories 表写一条 active 记忆（模拟已有长期记忆）。"""
    from ethan.core.paths import user_vectors_db_path
    from ethan.memory.records import (
        EvidenceLevel,
        MemoryEvidence,
        MemoryRecord,
        MemoryStatus,
    )
    from ethan.memory.store import MemoryStore

    store = MemoryStore(db_path=user_vectors_db_path())
    try:
        record = MemoryRecord(
            memory_type="preference",
            dimension="preference.content",
            memory_key="seed_" + content[:20],
            content=content,
            status=MemoryStatus.ACTIVE.value,
            evidence_level=EvidenceLevel.EXPLICIT.value,
            confidence=confidence,
        )
        evidence = MemoryEvidence(
            memory_id=record.id,
            evidence_level=EvidenceLevel.EXPLICIT.value,
            source_session_id="manual",
            source_message_id="",
            source_role="user",
            source_quote=content,
        )
        store.create_memory_with_evidence(record, [evidence])
        return record.id
    finally:
        store.close()


def _list_active_memories():
    from ethan.core.paths import user_vectors_db_path
    from ethan.memory.store import MemoryStore

    store = MemoryStore(db_path=user_vectors_db_path())
    try:
        return store.list_memories(status="active", limit=100)
    finally:
        store.close()


# ── 端到端测试 ────────────────────────────────────────────────────────────

async def test_dream_e2e_insight_stored_as_vector_only(isolated_fs):
    """insight（任意类型）只进向量库，不反写到 memories 表。

    注：success_path → playbook.json 反写链路已于 2026-07 退役，
    所有类型（repetition/error/success_path/...）均仅作为向量条目入库。
    """
    from ethan.memory.daily_consolidation import run_daily_consolidation

    today = date.today()

    # mock _read_day_memories 返回当日 memories
    day_memories = [{"type": "memory", "text": "每天早上问天气"}]
    refined = [
        {"type": "repetition", "text": "用户每天早上都会询问当天天气",
         "metadata": {"count": 3}},
    ]

    with patch("ethan.memory.daily_consolidation._read_day_memories",
               return_value=day_memories), \
         patch("ethan.memory.daily_consolidation._llm_refine",
               return_value=refined):
        added = await run_daily_consolidation(target_date=today)

    # 向量库应有 1 条 insight 条目
    assert added == 1, f"应写入 1 条 insight，实际 {added}"

    from ethan.core.paths import user_vectors_db_path
    from ethan.memory.vector_store import VectorStore
    store = VectorStore(db_path=user_vectors_db_path())
    try:
        items = store.list_items(exclude_types=["fact_sync", "memory"], limit=10)
        assert len(items) == 1
        assert items[0]["metadata"]["type"] == "repetition"
    finally:
        store.close()

    # memories 表不应有反写条目（所有 insight 类型都不再反写）
    memories = _list_active_memories()
    assert len(memories) == 0, f"insight 不应反写到 memories 表，实际 {len(memories)} 条"


async def test_dream_e2e_dedup_skips_existing_insight(isolated_fs):
    """相同 insight 二次做梦时被 L2 去重跳过（不重复写入 memory.db）。"""
    from ethan.memory.daily_consolidation import run_daily_consolidation

    today = date.today()

    day_memories = [{"type": "memory", "text": "每天早上问天气"}]
    refined = [
        {"type": "repetition", "text": "用户每天早上都会询问当天天气"},
    ]

    # 第一次做梦
    with patch("ethan.memory.daily_consolidation._read_day_memories",
               return_value=list(day_memories)), \
         patch("ethan.memory.daily_consolidation._llm_refine",
               return_value=list(refined)):
        added1 = await run_daily_consolidation(target_date=today)
    assert added1 == 1

    # 第二次做梦（相同 text）—— 应被 L2 去重跳过
    with patch("ethan.memory.daily_consolidation._read_day_memories",
               return_value=list(day_memories)), \
         patch("ethan.memory.daily_consolidation._llm_refine",
               return_value=list(refined)):
        added2 = await run_daily_consolidation(target_date=today)
    assert added2 == 0, f"重复 insight 应被去重，实际写入 {added2}"


async def test_dream_e2e_fact_sync_enables_dedup(isolated_fs):
    """fact_sync 机制：memories 表已有的记忆不会被 insight 重复反写。

    场景：memories 表已有"用户喜欢深色模式"（主动写入）。
    做梦产生相同文本的 insight —— 因 fact_sync 已把 memories 内容
    同步进向量库，L2=0 必然去重跳过。
    """
    from ethan.memory.daily_consolidation import run_daily_consolidation

    today = date.today()
    fact_text = "用户喜欢深色模式"

    # 预置结构化记忆
    _seed_memory(fact_text)

    # mock _read_day_memories 返回当日 memories
    day_memories = [{"type": "memory", "text": fact_text}]

    # insight 用完全相同的文本 —— L2=0，必然被 fact_sync 去重
    refined = [{"type": "repetition", "text": fact_text}]

    with patch("ethan.memory.daily_consolidation._read_day_memories",
               return_value=day_memories), \
         patch("ethan.memory.daily_consolidation._llm_refine",
               return_value=refined):
        added = await run_daily_consolidation(target_date=today)

    assert added == 0, (
        f"insight 与已有记忆完全相同应被 fact_sync 去重跳过，实际写入 {added}"
    )

    # memories 表不应出现重复
    memories = _list_active_memories()
    assert sum(1 for m in memories if m.content == fact_text) == 1


async def test_dream_e2e_no_signals_returns_zero(isolated_fs):
    """无信号时做梦返回 0，不报错。"""
    from ethan.memory.daily_consolidation import run_daily_consolidation

    # 不写任何 memories，mock _read_day_memories 返回空
    with patch("ethan.memory.daily_consolidation._read_day_memories",
               return_value=[]):
        added = await run_daily_consolidation(target_date=date.today())
    assert added == 0


async def test_dream_e2e_get_all_memories_filters_fact_sync(isolated_fs):
    """get_all_memories 正确过滤 fact_sync 镜像条目。"""
    from ethan.memory.daily_consolidation import (
        get_all_memories,
        get_memories_by_date,
        run_daily_consolidation,
    )

    today = date.today()

    # 预置 1 条结构化记忆（会产生 1 条 fact_sync 镜像）
    _seed_memory("用户喜欢 Python")

    # mock _read_day_memories + 做梦产生 1 条 insight
    day_memories = [{"type": "memory", "text": "忘了 commit"}]
    refined = [{"type": "error", "text": "用户曾因忘记 git commit 丢失工作"}]

    with patch("ethan.memory.daily_consolidation._read_day_memories",
               return_value=day_memories), \
         patch("ethan.memory.daily_consolidation._llm_refine",
               return_value=refined):
        await run_daily_consolidation(target_date=today)

    # get_all_memories 应排除 fact_sync，只返回 insight
    result = await get_all_memories(limit=10)
    assert result["total"] == 1, f"应只有 1 条 insight，实际 {result['total']}"
    assert result["items"][0]["metadata"]["type"] == "error"

    # get_memories_by_date 按 today 过滤
    by_date = await get_memories_by_date(today)
    assert len(by_date) == 1
    assert by_date[0]["metadata"]["type"] == "error"


async def test_dream_e2e_multiple_insights_all_vector_only(isolated_fs):
    """混合信号：repetition + error + success_path 同时做梦，全部仅入向量库。

    注：success_path → playbook.json 反写链路已于 2026-07 退役，
    所有类型一视同仁，仅作为向量条目入库。
    """
    from ethan.memory.daily_consolidation import run_daily_consolidation

    today = date.today()

    day_memories = [
        {"type": "memory", "text": "每晚查邮件"},
        {"type": "memory", "text": "误删文件"},
        {"type": "memory", "text": "部署前跑测试"},
    ]
    refined = [
        {"type": "repetition", "text": "用户每晚都会检查邮件", "metadata": {}},
        {"type": "error", "text": "用户曾误删文件，建议先做备份", "metadata": {}},
        {"type": "success_path", "text": "部署前跑 shell:pytest 是成功路径",
         "metadata": {"tool_sequence": ["shell:pytest"]}},
    ]

    with patch("ethan.memory.daily_consolidation._read_day_memories",
               return_value=day_memories), \
         patch("ethan.memory.daily_consolidation._llm_refine",
               return_value=refined):
        added = await run_daily_consolidation(target_date=today)

    assert added == 3

    # memories 表不应有反写条目（所有类型都不再反写）
    memories = _list_active_memories()
    assert len(memories) == 0, f"所有 insight 都不应反写，实际 {len(memories)} 条"

    # playbook.json 不应有 success_patterns（已退役）
    from ethan.core.paths import user_procedures_path
    pb_path = user_procedures_path()
    if pb_path.exists():
        pb = json.loads(pb_path.read_text(encoding="utf-8"))
        assert pb.get("success_patterns", []) == [], "success_patterns 应为空（已退役）"


async def test_dream_e2e_insight_exempt_from_lru_cleanup(isolated_fs):
    """P2.2：第五层是"永久记忆"，insight 条目即使 90 天未访问也不被 cleanup_expired 删除。"""
    from ethan.core.paths import user_vectors_db_path
    from ethan.memory.daily_consolidation import run_daily_consolidation
    from ethan.memory.vector_store import VectorStore

    today = date.today()

    day_memories = [{"type": "memory", "text": "反复问汇率"}]
    refined = [{"type": "repetition", "text": "用户反复询问汇率换算"}]

    with patch("ethan.memory.daily_consolidation._read_day_memories",
               return_value=day_memories), \
         patch("ethan.memory.daily_consolidation._llm_refine",
               return_value=refined):
        added = await run_daily_consolidation(target_date=today)
    assert added == 1

    store = VectorStore(db_path=user_vectors_db_path())
    try:
        # 把 last_accessed 改成 100 天前（超过 90 天 LRU 阈值）
        import time as _time
        old_ts = _time.time() - 100 * 86400
        conn = store._get_conn()
        conn.execute(
            "UPDATE vec_items SET last_accessed = ? "
            "WHERE json_extract(metadata, '$.type') = 'repetition'",
            (old_ts,),
        )
        conn.commit()

        before = store.count_items(exclude_types=["fact_sync"])
        deleted = store.cleanup_expired()  # 应该 0 条——insight 永久保留
        after = store.count_items(exclude_types=["fact_sync"])

        assert deleted == 0, f"insight 不应被 LRU 清理，实际删除 {deleted}"
        assert after == before, "insight 数量不应变化"
    finally:
        store.close()
