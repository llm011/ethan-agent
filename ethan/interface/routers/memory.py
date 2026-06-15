"""memory 路由：facts / episodes / procedures。"""
from fastapi import APIRouter, Depends, HTTPException
from .deps import verify_token

router = APIRouter(prefix="/memory")


@router.get("/facts", dependencies=[Depends(verify_token)])
async def get_facts():
    from ethan.memory.facts import FactStore
    store = FactStore()
    return {"facts": [f.__dict__ for f in store._facts]}


@router.get("/episodes", dependencies=[Depends(verify_token)])
async def get_episodes():
    from ethan.memory.episodic import EpisodeStore
    store = EpisodeStore()
    return {"episodes": [e.__dict__ for e in store._episodes]}


@router.patch("/facts/{fact_id}", dependencies=[Depends(verify_token)])
async def update_fact(fact_id: str, req: dict):
    from ethan.memory.facts import FactStore
    store = FactStore()
    for i, f in enumerate(store._facts):
        if str(i) == fact_id or f.id == fact_id:
            if "content" in req:
                f.content = req["content"]
            if "confidence" in req:
                f.confidence = req["confidence"]
            store._save()
            return {"ok": True}
    raise HTTPException(404, "Fact not found")


@router.delete("/facts/{fact_id}", dependencies=[Depends(verify_token)])
async def delete_fact(fact_id: str):
    from ethan.memory.facts import FactStore
    store = FactStore()
    before = len(store._facts)
    store._facts = [f for f in store._facts if f.id != fact_id and str(store._facts.index(f)) != fact_id]
    if len(store._facts) == before:
        raise HTTPException(404, "Fact not found")
    store._save()
    return {"ok": True}


@router.delete("/episodes/{episode_id}", dependencies=[Depends(verify_token)])
async def delete_episode(episode_id: str):
    from ethan.memory.episodic import EpisodeStore
    store = EpisodeStore()
    before = len(store._episodes)
    store._episodes = [e for e in store._episodes if e.id != episode_id]
    if len(store._episodes) == before:
        raise HTTPException(404, "Episode not found")
    store._save()
    return {"ok": True}


@router.get("/procedures", dependencies=[Depends(verify_token)])
async def list_procedures():
    from ethan.memory.procedures import ProcedureStore
    store = ProcedureStore()
    return {"procedures": [
        {"id": str(i), "rule": p.rule, "context": p.context, "hit_count": p.hit_count, "created_at": p.created_at}
        for i, p in enumerate(store._procedures)
    ]}


@router.delete("/procedures/{proc_id}", dependencies=[Depends(verify_token)])
async def delete_procedure(proc_id: str):
    from ethan.memory.procedures import ProcedureStore
    store = ProcedureStore()
    idx = int(proc_id)
    if idx < 0 or idx >= len(store._procedures):
        raise HTTPException(404, "Not found")
    store._procedures.pop(idx)
    store._save()
    return {"ok": True}
