"""FastAPI 入口 — 挂载所有路由模块。"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ethan import __version__
from ethan.core.heartbeat import start_heartbeat, stop_heartbeat
from ethan.memory.api_keys import APIKeyStore

from ethan.interface.routers import chat, sessions, settings, memory, schedule, knowledge, skills, docs, completions, logs

try:
    from ethan.interface.lark import lark_router
    from ethan.interface.lark_events import start_lark_listener, stop_lark_listener
    _lark_available = True
except ImportError:
    _lark_available = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    if _lark_available:
        start_lark_listener()
    start_heartbeat()
    key_store = APIKeyStore()
    await key_store.init()
    app.state.api_key_store = key_store
    yield
    if _lark_available:
        stop_lark_listener()
    stop_heartbeat()
    await app.state.api_key_store.close()


app = FastAPI(title="Ethan Agent API", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if _lark_available:
    app.include_router(lark_router)

app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(settings.router)
app.include_router(memory.router)
app.include_router(schedule.router)
app.include_router(knowledge.router)
app.include_router(skills.router)
app.include_router(docs.router)
app.include_router(completions.router)
app.include_router(logs.router)


def run_server(host: str = "0.0.0.0", port: int = 8900):
    import uvicorn
    uvicorn.run(app, host=host, port=port)
