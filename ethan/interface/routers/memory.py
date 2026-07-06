"""memory 路由：facts / episodes / procedures（per-user 隔离）。"""
from fastapi import APIRouter, Depends, HTTPException

from .deps import verify_token

router = APIRouter(prefix="/memory")


def _fact_store(user_id: str):
    from ethan.core.paths import user_facts_path
    from ethan.memory.facts import FactStore
    return FactStore(path=user_facts_path())


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
    store = _fact_store(user_id)
    return {"facts": [f.__dict__ for f in store._facts]}


@router.get("/episodes")
async def get_episodes(user_id: str = Depends(verify_token)):
    store = _episode_store(user_id)
    return {"episodes": [e.__dict__ for e in store._episodes]}


@router.patch("/facts/{fact_id}")
async def update_fact(fact_id: str, req: dict, user_id: str = Depends(verify_token)):
    store = _fact_store(user_id)
    for i, f in enumerate(store._facts):
        if str(i) == fact_id or f.id == fact_id:
            if "content" in req:
                f.content = req["content"]
            if "confidence" in req:
                f.confidence = req["confidence"]
            store._save()
            return {"ok": True}
    raise HTTPException(404, "Fact not found")


@router.delete("/facts/{fact_id}")
async def delete_fact(fact_id: str, user_id: str = Depends(verify_token)):
    store = _fact_store(user_id)
    before = len(store._facts)
    store._facts = [f for f in store._facts if f.id != fact_id and str(store._facts.index(f)) != fact_id]
    if len(store._facts) == before:
        raise HTTPException(404, "Fact not found")
    store._save()
    return {"ok": True}


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
