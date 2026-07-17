"""memory 路由：legacy memory + structured records（per-user 隔离）。"""
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .deps import verify_token

router = APIRouter(prefix="/memory")


def _memory_store():
    from ethan.memory.store import MemoryStore
    return MemoryStore()


def _record_to_fact(m) -> dict:
    """MemoryRecord → legacy Fact 响应 shape（Web UI facts 页兼容）。

    数据源已切换到 memories 表；companion 域不进 facts 页（情感数据有独立的
    /records?domain=companion 入口）。删除语义升级为 forget_memory（证据脱敏）。
    """
    category = {"preference": "preference", "decision": "decision"}.get(m.memory_type, "knowledge")
    if m.evidence_level == "corrected":
        category = "correction"
    return {
        "id": m.id,
        "content": m.content,
        "confidence": m.confidence,
        "source": m.source_session_id,
        "category": category,
        "created_at": m.created_at,
        "last_accessed": m.last_recalled_at or 0,
        "superseded": m.status == "superseded",
        "tags": [m.dimension] if m.dimension else [],
    }


def _episode_store(user_id: str):
    from ethan.core.paths import user_episodes_path
    from ethan.memory.episodic import EpisodeStore
    return EpisodeStore(path=user_episodes_path())


def _procedure_store(user_id: str):
    from ethan.core.paths import user_procedures_path
    from ethan.memory.procedures import ProcedureStore
    return ProcedureStore(path=user_procedures_path())


@router.get("/facts")
async def get_facts(user_id: str = Depends(verify_token)):
    store = _memory_store()
    try:
        records = store.list_memories(memory_domain="general", limit=1000)
        # forgotten/expired 不在 facts 页展示（旧语义里删除即消失）
        visible = [m for m in records if m.status in ("active", "superseded")]
        return {"facts": [_record_to_fact(m) for m in visible]}
    finally:
        store.close()


@router.get("/episodes")
async def get_episodes(user_id: str = Depends(verify_token)):
    store = _episode_store(user_id)
    return {"episodes": [e.__dict__ for e in store._episodes]}


@router.patch("/facts/{fact_id}")
async def update_fact(fact_id: str, req: dict, user_id: str = Depends(verify_token)):
    store = _memory_store()
    try:
        try:
            store.update_memory(
                fact_id,
                content=req.get("content"),
                confidence=req.get("confidence"),
            )
        except KeyError:
            raise HTTPException(404, "Fact not found")
        return {"ok": True}
    finally:
        store.close()


@router.delete("/facts/{fact_id}")
async def delete_fact(fact_id: str, user_id: str = Depends(verify_token)):
    store = _memory_store()
    try:
        try:
            store.forget_memory(fact_id)
        except KeyError:
            raise HTTPException(404, "Fact not found")
        return {"ok": True}
    finally:
        store.close()


@router.delete("/episodes/{episode_id}")
async def delete_episode(episode_id: str, user_id: str = Depends(verify_token)):
    store = _episode_store(user_id)
    before = len(store._episodes)
    store._episodes = [e for e in store._episodes if e.id != episode_id]
    if len(store._episodes) == before:
        raise HTTPException(404, "Episode not found")
    store._save()
    return {"ok": True}


@router.get("/procedures")
async def list_procedures(user_id: str = Depends(verify_token)):
    store = _procedure_store(user_id)
    return {"procedures": [
        {"id": str(i), "rule": p.rule, "context": p.context, "hit_count": p.hit_count, "created_at": p.created_at}
        for i, p in enumerate(store._procedures)
    ]}


@router.delete("/procedures/{proc_id}")
async def delete_procedure(proc_id: str, user_id: str = Depends(verify_token)):
    store = _procedure_store(user_id)
    idx = int(proc_id)
    if idx < 0 or idx >= len(store._procedures):
        raise HTTPException(404, "Not found")
    store._procedures.pop(idx)
    store._save()
    return {"ok": True}


# ── Insights (永久记忆 from memory.db) ───────────────────────────────────

@router.get("/insights")
async def list_insights(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(verify_token),
):
    """分页获取所有永久记忆。"""
    from ethan.memory.daily_consolidation import get_all_memories
    return await get_all_memories(limit=limit, offset=offset)


@router.get("/insights/date/{date_str}")
async def get_insights_by_date(date_str: str, user_id: str = Depends(verify_token)):
    """获取指定日期沉淀的记忆。"""
    from ethan.memory.daily_consolidation import get_memories_by_date
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")
    items = await get_memories_by_date(d)
    return {"date": date_str, "items": items}


@router.get("/signals/today")
async def get_today_signals(user_id: str = Depends(verify_token)):
    """获取今日采集的原始信号。"""
    from ethan.memory.daily_signals import read_today_signals
    return {"signals": read_today_signals()}


@router.get("/signals/date/{date_str}")
async def get_signals_by_date(date_str: str, user_id: str = Depends(verify_token)):
    """获取指定日期的原始信号。"""
    from ethan.memory.daily_signals import read_signals_by_date
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")
    return {"date": date_str, "signals": read_signals_by_date(d)}


@router.post("/consolidate")
async def trigger_consolidation(user_id: str = Depends(verify_token)):
    """手动触发今日记忆沉淀（测试用）。"""
    from ethan.memory.daily_consolidation import run_daily_consolidation
    added = await run_daily_consolidation()
    return {"ok": True, "added": added}


# ── Structured records ──────────────────────────────────────────────────────
# Structured memories live in the per-user memory.db ``memories`` table. The
# HTTP layer only calls MemoryStore; per-user isolation is physical (one DB
# per profile), so no user_id filter is needed at the store level. Companion
# memories are excluded from default listing — they require an explicit
# ``domain=companion`` query so emotional data never leaks into other tabs.

class _StructuredRecordApi(BaseModel):
    id: str
    memory_type: str
    dimension: str
    memory_key: str
    content: str
    structured_data: dict[str, Any]
    scope_type: str
    scope_id: str
    memory_domain: str
    status: str
    evidence_level: str
    confidence: float
    importance: float
    sensitivity: str
    valid_from: float | None = None
    valid_until: float | None = None
    source_session_id: str
    source_message_id: str
    created_at: float
    updated_at: float
    last_recalled_at: float | None = None
    superseded_by: str | None = None


class _UpdateRecordRequest(BaseModel):
    content: str | None = None
    structured_data: dict[str, Any] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    importance: float | None = Field(default=None, ge=0, le=1)
    valid_from: float | None = None
    valid_until: float | None = None
    clear_valid_from: bool = False
    clear_valid_until: bool = False


def _structured_store() -> "Any":
    from ethan.memory.store import MemoryStore
    return MemoryStore()


def _record_to_api(record) -> _StructuredRecordApi:
    return _StructuredRecordApi(
        id=record.id,
        memory_type=record.memory_type,
        dimension=record.dimension,
        memory_key=record.memory_key,
        content=record.content,
        structured_data=record.structured_data,
        scope_type=record.scope_type,
        scope_id=record.scope_id,
        memory_domain=record.memory_domain,
        status=record.status,
        evidence_level=record.evidence_level,
        confidence=record.confidence,
        importance=record.importance,
        sensitivity=record.sensitivity,
        valid_from=record.valid_from,
        valid_until=record.valid_until,
        source_session_id=record.source_session_id,
        source_message_id=record.source_message_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_recalled_at=record.last_recalled_at,
        superseded_by=record.superseded_by,
    )


@router.get("/records/search")
async def search_records(
    q: str = Query("", description="search query"),
    type: str | None = Query(None),
    domain: str | None = Query(None, description="general|companion; defaults to general"),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(verify_token),
):
    """Search structured memories by FTS/LIKE. Default domain=general."""
    store = _structured_store()
    try:
        memory_domain = domain or "general"
        types = [type] if type else None
        statuses = [status] if status else ["active"]
        hits = store.search_memories(
            q, memory_types=types, memory_domain=memory_domain,
            statuses=statuses, limit=limit,
        )
        return {"items": [_record_to_api(m).model_dump() for m in hits]}
    finally:
        store.close()


@router.post("/records/consolidate")
async def trigger_structured_consolidation(
    target_date: str | None = Query(None, description="YYYY-MM-DD, defaults to yesterday"),
    user_id: str = Depends(verify_token),
):
    """Manually trigger structured daily consolidation (test/debug)."""
    from ethan.memory.structured_consolidation import run_structured_consolidation
    d = None
    if target_date:
        try:
            d = date.fromisoformat(target_date)
        except ValueError:
            raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")
    result = await run_structured_consolidation(d)
    return {"ok": True, "result": result}


@router.get("/records/summaries")
async def list_daily_summaries_api(
    domain: str | None = Query(None),
    limit: int = Query(30, ge=1, le=366),
    user_id: str = Depends(verify_token),
):
    store = _structured_store()
    try:
        return {"items": store.list_daily_summaries(memory_domain=domain, limit=limit)}
    finally:
        store.close()


@router.get("/records/summaries/{date_str}")
async def get_daily_summaries_by_date(
    date_str: str,
    domain: str | None = Query(None),
    user_id: str = Depends(verify_token),
):
    try:
        date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(400, "Invalid date format, use YYYY-MM-DD")
    store = _structured_store()
    try:
        return {"items": store.get_daily_summary(date_str, memory_domain=domain)}
    finally:
        store.close()


@router.get("/records")
async def list_records(
    type: str | None = Query(None),
    status: str | None = Query(None),
    domain: str | None = Query(None, description="general|companion; defaults to general"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(verify_token),
):
    """List structured memories. Default domain=general (excludes companion)."""
    store = _structured_store()
    try:
        memory_domain = domain
        if memory_domain is None:
            memory_domain = "general"
        records = store.list_memories(
            memory_type=type, status=status, memory_domain=memory_domain,
            limit=limit, offset=offset,
        )
        return {"items": [_record_to_api(r).model_dump() for r in records]}
    finally:
        store.close()


@router.get("/records/{memory_id}")
async def get_record(memory_id: str, user_id: str = Depends(verify_token)):
    store = _structured_store()
    try:
        record = store.get_memory(memory_id)
        if not record:
            raise HTTPException(404, "Memory not found")
        evidence = store.list_evidence(memory_id, redact_restricted=True)
        return {"record": _record_to_api(record).model_dump(), "evidence": evidence}
    finally:
        store.close()


@router.get("/records/{memory_id}/evidence")
async def get_record_evidence(memory_id: str, user_id: str = Depends(verify_token)):
    store = _structured_store()
    try:
        record = store.get_memory(memory_id)
        if not record:
            raise HTTPException(404, "Memory not found")
        return {"evidence": store.list_evidence(memory_id, redact_restricted=True)}
    finally:
        store.close()


@router.patch("/records/{memory_id}")
async def update_record(
    memory_id: str,
    req: _UpdateRecordRequest,
    user_id: str = Depends(verify_token),
):
    store = _structured_store()
    try:
        try:
            updated = store.update_memory(
                memory_id,
                content=req.content,
                structured_data=req.structured_data,
                confidence=req.confidence,
                importance=req.importance,
                valid_from=req.valid_from,
                valid_until=req.valid_until,
                clear_valid_from=req.clear_valid_from,
                clear_valid_until=req.clear_valid_until,
            )
        except KeyError:
            raise HTTPException(404, "Memory not found")
        return {"record": _record_to_api(updated).model_dump()}
    finally:
        store.close()


@router.delete("/records/{memory_id}")
async def forget_record(memory_id: str, user_id: str = Depends(verify_token)):
    store = _structured_store()
    try:
        try:
            store.forget_memory(memory_id)
        except KeyError:
            raise HTTPException(404, "Memory not found")
        return {"ok": True}
    finally:
        store.close()


@router.post("/records/{memory_id}/confirm")
async def confirm_record(memory_id: str, user_id: str = Depends(verify_token)):
    """Promote a candidate memory to active (manual confirmation)."""
    from ethan.memory.admission import AdmissionPolicy
    store = _structured_store()
    try:
        candidate = store.get_candidate(memory_id)
        if not candidate:
            raise HTTPException(404, "Candidate not found")
        policy = AdmissionPolicy(store)
        policy.admit_candidate(candidate)
        record = store.get_memory(memory_id)
        return {"ok": True, "record": _record_to_api(record).model_dump() if record else None}
    finally:
        store.close()

