"""FastAPI HTTP 接口 — REST API + SSE 流式 + 鉴权 + Session CRUD。"""
import json
import os
import tempfile
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ethan import __version__
from ethan.core.agent import Agent
from ethan.core.config import get_config
from ethan.memory.session import SessionStore
from ethan.providers.base import Message
from ethan.skills.registry import SkillRegistry
from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
from ethan.tools.builtin.shell import ShellTool
from ethan.tools.builtin.web import WebFetchTool
from ethan.tools.builtin.web_search import WebSearchTool
from ethan.tools.registry import ToolRegistry

app = FastAPI(title="Ethan Agent API", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
async def list_sessions(limit: int = 50):
    store = SessionStore()
    await store.init()
    sessions = await store.list_recent(limit)
    await store.close()
    return {"sessions": [
        {"id": s.id, "title": s.title, "model": s.model, "created_at": s.created_at, "updated_at": s.updated_at}
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
        "messages": [{"role": m.role, "content": m.content} for m in session.messages if m.role in ("user", "assistant")],
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


def run_server(host: str = "0.0.0.0", port: int = 8900):
    import uvicorn
    uvicorn.run(app, host=host, port=port)
