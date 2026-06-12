"""FastAPI HTTP 接口 — REST API + SSE 流式 + 鉴权 + Session CRUD。"""
import json
import os
import tempfile
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ethan import __version__
from ethan.core.agent import Agent
from ethan.core.config import get_config, save_config, reload_config
from ethan.memory.session import SessionStore
from ethan.memory.facts import FactStore
from ethan.memory.episodic import EpisodeStore
from ethan.providers.base import Message
from ethan.skills.registry import SkillRegistry
from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
from ethan.tools.builtin.shell import ShellTool
from ethan.tools.builtin.web import WebFetchTool
from ethan.tools.builtin.web_search import WebSearchTool
from ethan.tools.registry import ToolRegistry
from ethan.scheduler.cron import Scheduler
from ethan.knowledge.base import FilesystemKnowledgeBase
from ethan.core.config import CONFIG_DIR
from ethan.interface.lark import lark_router
from ethan.interface.lark_events import start_lark_listener, stop_lark_listener


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: auto-connect to Feishu via WebSocket (skips if not configured)
    start_lark_listener()
    yield
    # Shutdown
    stop_lark_listener()


app = FastAPI(title="Ethan Agent API", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(lark_router)


# ── Auth ────────────────────────────────────────────────────────

async def verify_token(request: Request):
    config = get_config()
    token = config.network.auth_token
    if not token:
        return
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Agent factory ───────────────────────────────────────────────

def _create_agent(model: str | None = None) -> Agent:
    registry = ToolRegistry()
    registry.register(ShellTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    registry.register(FileListTool())

    skills = SkillRegistry()
    skills.load()

    return Agent(tool_registry=registry, skill_registry=skills, model=model)


# ── Request/Response models ─────────────────────────────────────

class ChatRequest(BaseModel):
    messages: list[dict]
    model: str | None = None
    stream: bool = False
    session_id: str | None = None


class ChatResponse(BaseModel):
    content: str
    model: str
    usage: dict | None = None


class AuthRequest(BaseModel):
    token: str


# ── Endpoints ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": __version__}


# ── Onboarding ───────────────────────────────────────────────────

class OnboardingCompleteRequest(BaseModel):
    agent_name: str
    user_info: str


@app.get("/onboarding/status", dependencies=[Depends(verify_token)])
async def onboarding_status():
    from ethan.core.onboarding import is_first_time, ONBOARDING_MESSAGE
    first_time = is_first_time()
    return {"first_time": first_time, "message": ONBOARDING_MESSAGE if first_time else ""}


@app.post("/onboarding/complete", dependencies=[Depends(verify_token)])
async def onboarding_complete(req: OnboardingCompleteRequest):
    agent_name = req.agent_name.strip() or "Ethan"
    user_info = req.user_info.strip()

    # Persist agent name
    config = get_config()
    config.defaults.agent_name = agent_name
    save_config(config)
    reload_config()

    # Persist user info as a high-confidence Fact
    if user_info:
        store = FactStore()
        store.add(user_info, confidence=1.0, source="onboarding", category="preference")

    return {"ok": True, "agent_name": agent_name}


@app.post("/auth")
async def auth(req: AuthRequest):
    config = get_config()
    if not config.network.auth_token:
        return {"ok": True}
    if req.token == config.network.auth_token:
        return {"ok": True}
    raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/models", dependencies=[Depends(verify_token)])
async def list_models():
    config = get_config()
    return {"models": [m.model_dump() for m in config.models]}


@app.post("/chat", dependencies=[Depends(verify_token)])
async def chat(req: ChatRequest):
    agent = _create_agent(req.model)
    messages = [Message(role=m["role"], content=m.get("content", "")) for m in req.messages]

    # Persist to session if session_id provided
    store = SessionStore()
    await store.init()

    if req.session_id:
        for m in messages[-1:]:  # save last user message
            if m.role == "user":
                await store.save_message(req.session_id, m)

    if req.stream:
        return StreamingResponse(
            _stream_response(agent, messages, store, req.session_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    response = await agent.chat(messages)

    if req.session_id:
        await store.save_message(req.session_id, response)
        await store.touch(req.session_id)

    await store.close()
    return ChatResponse(
        content=response.content,
        model=agent._provider.model,
        usage={"input": agent.usage.input_tokens, "output": agent.usage.output_tokens, "cache": agent.usage.cache_tokens},
    )


@app.get("/sessions", dependencies=[Depends(verify_token)])
async def list_sessions(limit: int = 50, offset: int = 0, q: str | None = None):
    store = SessionStore()
    await store.init()
    if q:
        sessions = await store.search(q, limit, offset)
    else:
        sessions = await store.list_recent(limit, offset)
    await store.close()
    return {"sessions": [
        {"id": s.id, "title": s.title, "model": s.model, "created_at": s.created_at, "updated_at": s.updated_at, "snippet": getattr(s, "snippet", None), "source": getattr(s, 'source', 'web')}
        for s in sessions
    ]}


@app.post("/sessions", dependencies=[Depends(verify_token)])
async def create_session(model: str | None = None):
    config = get_config()
    store = SessionStore()
    await store.init()
    session = await store.create(model or config.defaults.model)
    await store.close()
    return {"id": session.id, "title": session.title, "model": session.model}


@app.get("/sessions/{session_id}", dependencies=[Depends(verify_token)])
async def get_session(session_id: str):
    store = SessionStore()
    await store.init()
    session = await store.load(session_id)
    await store.close()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "id": session.id,
        "title": session.title,
        "model": session.model,
        "messages": [{"role": m.role, "content": m.content, "created_at": getattr(m, "created_at", None)} for m in session.messages if m.role in ("user", "assistant")],
    }


@app.delete("/sessions/{session_id}", dependencies=[Depends(verify_token)])
async def delete_session(session_id: str):
    store = SessionStore()
    await store.init()
    ok = await store.delete(session_id)
    await store.close()
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


class RenameSessionRequest(BaseModel):
    title: str


@app.patch("/sessions/{session_id}", dependencies=[Depends(verify_token)])
async def rename_session(session_id: str, req: RenameSessionRequest):
    store = SessionStore()
    await store.init()
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    await store.update_title(session_id, title)
    await store.close()
    return {"ok": True}


class AgentSettingsPatch(BaseModel):
    workspace: str | None = None
    system_prompt: str | None = None
    agent_name: str | None = None
    language: str | None = None
    default_model: str | None = None


@app.get("/settings/agent", dependencies=[Depends(verify_token)])
async def get_agent_settings():
    config = get_config()
    return {
        "workspace": config.defaults.workspace,
        "system_prompt": config.defaults.system_prompt,
        "agent_name": config.defaults.agent_name,
        "language": config.defaults.language,
        "default_model": config.defaults.model,
    }


@app.patch("/settings/agent", dependencies=[Depends(verify_token)])
async def update_agent_settings(req: AgentSettingsPatch):
    config = get_config()
    if req.system_prompt is not None:
        config.defaults.system_prompt = req.system_prompt
    if req.agent_name is not None:
        config.defaults.agent_name = req.agent_name
    if req.language is not None:
        config.defaults.language = req.language
    if req.default_model is not None:
        config.defaults.model = req.default_model
    if req.workspace is not None:
        config.defaults.workspace = req.workspace
    save_config(config)
    reload_config()
    return {"ok": True}


class SystemSettingsPatch(BaseModel):
    identity: str | None = None
    soul: str | None = None
    format: str | None = None

@app.get("/settings/system", dependencies=[Depends(verify_token)])
async def get_system_settings():
    from pathlib import Path
    import os
    system_dir = Path(os.path.expanduser("~/.ethan/system"))
    identity_path = system_dir / "identity.md"
    soul_path = system_dir / "soul.md"
    format_path = system_dir / "format.md"
    
    identity = identity_path.read_text(encoding="utf-8") if identity_path.exists() else ""
    soul = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""
    format_content = format_path.read_text(encoding="utf-8") if format_path.exists() else ""
    
    return {
        "identity": identity,
        "soul": soul,
        "format": format_content
    }

@app.patch("/settings/system", dependencies=[Depends(verify_token)])
async def update_system_settings(req: SystemSettingsPatch):
    from pathlib import Path
    import os
    system_dir = Path(os.path.expanduser("~/.ethan/system"))
    system_dir.mkdir(parents=True, exist_ok=True)
    
    if req.identity is not None:
        (system_dir / "identity.md").write_text(req.identity, encoding="utf-8")
    if req.soul is not None:
        (system_dir / "soul.md").write_text(req.soul, encoding="utf-8")
    if req.format is not None:
        (system_dir / "format.md").write_text(req.format, encoding="utf-8")
        
    return {"ok": True}




@app.get("/settings/providers", dependencies=[Depends(verify_token)])
async def get_provider_settings():
    config = get_config()
    return {
        k: {
            "api_key": v.api_key,
            "base_url": v.base_url
        } for k, v in config.providers.items()
    }

@app.patch("/settings/providers", dependencies=[Depends(verify_token)])
async def update_provider_settings(req: dict[str, dict]):
    from ethan.core.config import ProviderConfig
    config = get_config()
    for k, v in req.items():
        if k not in config.providers:
            config.providers[k] = ProviderConfig()
        if "api_key" in v and v["api_key"] is not None:
            config.providers[k].api_key = v["api_key"]
        if "base_url" in v and v["base_url"] is not None:
            config.providers[k].base_url = v["base_url"]
    save_config(config)
    reload_config()
    return {"ok": True}


@app.post("/upload", dependencies=[Depends(verify_token)])
async def upload_file(file: UploadFile = File(...)):
    content = await file.read()
    tmp_dir = tempfile.mkdtemp(prefix="ethan_upload_")
    path = os.path.join(tmp_dir, file.filename or "upload.txt")
    with open(path, "wb") as f:
        f.write(content)
    return {"path": path, "filename": file.filename, "size": len(content)}


# ── SSE streaming ───────────────────────────────────────────────

async def _stream_response(
    agent: Agent,
    messages: list[Message],
    store: SessionStore,
    session_id: str | None,
) -> AsyncGenerator[str, None]:
    from ethan.providers.base import ToolEvent

    full = ""
    try:
        async for item in agent.stream_chat(messages):
            if isinstance(item, ToolEvent):
                evt_data = json.dumps({
                    "tool": item.tool_name,
                    "args": item.args_summary,
                    "state": item.state,
                }, ensure_ascii=False)
                yield f"data: {evt_data}\n\n"
            else:
                full += item
                data = json.dumps({"content": item}, ensure_ascii=False)
                yield f"data: {data}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

    if session_id and full:
        await store.save_message(session_id, Message(role="assistant", content=full))
        await store.touch(session_id)

    done_data = json.dumps({
        "done": True,
        "model": agent._provider.model,
        "usage": {"input": agent.usage.input_tokens, "output": agent.usage.output_tokens, "cache": agent.usage.cache_tokens},
    }, ensure_ascii=False)
    yield f"data: {done_data}\n\n"
    await store.close()



# ── Scheduler ─────────────────────────────────────────────────────────

_scheduler = None

def get_scheduler():
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
        _scheduler.start()
    return _scheduler

@app.get("/schedule", dependencies=[Depends(verify_token)])
async def get_schedules():
    scheduler = get_scheduler()
    jobs = scheduler._scheduler.get_jobs()
    result = []
    for job in jobs:
        # Extract prompt and session_id from kwargs
        kwargs = job.kwargs or {}
        prompt = kwargs.get("prompt", "")
        session_id = kwargs.get("session_id", "")
        
        # Determine status
        is_paused = job.next_run_time is None
        
        result.append({
            "id": job.id,
            "name": job.name or job.id,
            "trigger": str(job.trigger),
            "next_run_time": str(job.next_run_time) if job.next_run_time else None,
            "status": "paused" if is_paused else "active",
            "prompt": prompt,
            "session_id": session_id
        })
    return {"jobs": result}

class ScheduleCreateRequest(BaseModel):
    job_id: str
    prompt: str
    cron: str = ""
    interval_minutes: int = 0
    session_id: str

@app.post("/schedule", dependencies=[Depends(verify_token)])
async def create_schedule(req: ScheduleCreateRequest):
    scheduler = get_scheduler()
    from ethan.tools.builtin.schedule import fire_schedule_job
    if req.cron:
        scheduler.add_cron(req.job_id, fire_schedule_job, req.cron, session_id=req.session_id, prompt=req.prompt)
    elif req.interval_minutes > 0:
        scheduler.add_interval(req.job_id, fire_schedule_job, minutes=req.interval_minutes, session_id=req.session_id, prompt=req.prompt)
    else:
        raise HTTPException(400, "Need cron or interval_minutes")
    return {"ok": True}


@app.delete("/schedule/{job_id}", dependencies=[Depends(verify_token)])
async def delete_schedule(job_id: str):
    scheduler = get_scheduler()
    success = scheduler.remove(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found or could not be removed")
    return {"ok": True}

class SchedulePatchRequest(BaseModel):
    state: str

@app.patch("/schedule/{job_id}", dependencies=[Depends(verify_token)])
async def patch_schedule(job_id: str, req: SchedulePatchRequest):
    scheduler = get_scheduler()
    if req.state == "paused":
        success = scheduler.pause(job_id)
    elif req.state == "active":
        success = scheduler.resume(job_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid state. Use 'paused' or 'active'")
        
    if not success:
        raise HTTPException(status_code=404, detail="Job not found or could not be updated")
    return {"ok": True}


# ── Memory endpoints ───────────────────────────────────────────────

@app.get("/memory/facts", dependencies=[Depends(verify_token)])
async def get_facts():
    # Read the facts.json file via FactStore
    store = FactStore()
    return {"facts": [f.__dict__ for f in store._facts]}

@app.get("/memory/episodes", dependencies=[Depends(verify_token)])
async def get_episodes():
    # Read the episodes.json file via EpisodeStore
    store = EpisodeStore()
    return {"episodes": [e.__dict__ for e in store._episodes]}

# ── Knowledge Base ───────────────────────────────────────────────────

_knowledge_manager = None

def get_knowledge_manager():
    global _knowledge_manager
    if _knowledge_manager is None:
        from pathlib import Path
        kb_dir = CONFIG_DIR / "knowledge"
        _knowledge_manager = FilesystemKnowledgeBase(kb_dir)
    return _knowledge_manager

@app.get("/knowledge", dependencies=[Depends(verify_token)])
async def get_knowledge(q: str = None, mode: str = "keyword"):
    manager = get_knowledge_manager()
    if q:
        if mode == "semantic":
            items = await manager.semantic_search(q)
        else:
            items = manager.search(q)
    else:
        items = manager.list_all()

    return {"items": [
        {
            "title": item.title,
            "content": item.snippet(),
            "source": item.source,
            "tags": item.tags
        } for item in items
    ]}

class KnowledgeAddRequest(BaseModel):
    title: str
    content: str
    tags: list[str] | None = None

@app.post("/knowledge", dependencies=[Depends(verify_token)])
async def add_knowledge(req: KnowledgeAddRequest):
    manager = get_knowledge_manager()
    source = manager.add(title=req.title, content=req.content, tags=req.tags)
    return {"ok": True, "source": source}

@app.delete("/knowledge/{source:path}", dependencies=[Depends(verify_token)])
async def delete_knowledge(source: str):
    manager = get_knowledge_manager()
    # Find item
    item = manager.get(source)
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
        
    from pathlib import Path
    try:
        Path(item.source).unlink()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete: {str(e)}")



@app.get("/logs", dependencies=[Depends(verify_token)])
async def get_logs(type: str = "backend", lines: int = 500, q: str | None = None):
    # Determine which file to read
    from pathlib import Path
    
    # Need to go up one directory from the web directory where we normally start, 
    # but api.py runs from project root usually. Let's resolve project root reliably.
    import os
    project_root = Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    
    log_file = project_root / ".run" / f"{type}.log"
    
    # Try the absolute paths as specified if the calculated path doesn't exist
    if not log_file.exists():
        abs_log = Path("/Users/jsongo/code/life/ethan-ai/.run") / f"{type}.log"
        if abs_log.exists():
            log_file = abs_log
            
    if not log_file.exists():
        return {"content": f"Log file not found: {log_file}"}
        
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            
        if q:
            all_lines = [line for line in all_lines if q.lower() in line.lower()]
            
        # Get last N lines
        tail_lines = all_lines[-lines:] if lines > 0 else all_lines
        return {"content": "".join(tail_lines)}
    except Exception as e:
        return {"content": f"Error reading log: {str(e)}"}



# ── Skills ───────────────────────────────────────────────────────────

from ethan.skills.loader import SKILLS_DIR
import yaml

@app.get("/skills", dependencies=[Depends(verify_token)])
async def list_skills():
    skills_reg = SkillRegistry()
    skills_reg.load()
    return {"skills": [
        {
            "name": s.name,
            "description": s.description,
            "trigger": s.trigger,
            "content": s.content
        } for s in skills_reg.all()
    ]}

@app.get("/skills/{name}", dependencies=[Depends(verify_token)])
async def get_skill(name: str):
    skills_reg = SkillRegistry()
    skills_reg.load()
    skill = skills_reg.get(name)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {
        "name": skill.name,
        "description": skill.description,
        "trigger": skill.trigger,
        "content": skill.content
    }

class SkillSaveRequest(BaseModel):
    name: str
    description: str
    trigger: list[str]
    content: str

@app.post("/skills", dependencies=[Depends(verify_token)])
async def save_skill_api(req: SkillSaveRequest):
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Simple validation for name to avoid path traversal
    safe_name = "".join(c for c in req.name if c.isalnum() or c in "-_")
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid skill name")
        
    skill_path = SKILLS_DIR / f"{safe_name}.md"
    
    frontmatter = {
        "name": safe_name,
        "description": req.description,
        "trigger": req.trigger
    }
    
    content = f"---\n{yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)}---\n\n{req.content}"
    
    skill_path.write_text(content, encoding="utf-8")
    return {"ok": True, "name": safe_name}


def run_server(host: str = "0.0.0.0", port: int = 8900):
    import uvicorn
    uvicorn.run(app, host=host, port=port)
