"""FastAPI 入口 — 挂载所有路由模块。"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from ethan import __version__
from ethan.core.heartbeat import start_heartbeat, stop_heartbeat
from ethan.memory.api_keys import APIKeyStore

from ethan.interface.routers import chat, sessions, settings, memory, schedule, knowledge, skills, docs, completions, logs, models, consent
from ethan.browser.ws_route import router as browser_ws_router
from ethan.browser.http_route import router as browser_http_router

try:
    from ethan.interface.lark import lark_router
    from ethan.interface.lark_events import start_lark_listener, stop_lark_listener
    _lark_available = True
except ImportError:
    _lark_available = False

_WEB_DIST = Path(__file__).parent.parent / "web_dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
    # 给 ethan logger 配 handler + INFO 级别，否则 lark/heartbeat 等子模块的
    # info 日志会被 root logger（默认 WARNING）吞掉，serve 前台看不到任何状态。
    ethan_logger = logging.getLogger("ethan")
    ethan_logger.setLevel(logging.INFO)
    if not ethan_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s", "%H:%M:%S"))
        ethan_logger.addHandler(handler)
    ethan_logger.propagate = False  # 已有自己的 handler，别再冒泡到 root 重复打印

    if _lark_available:
        start_lark_listener()
    start_heartbeat()
    from ethan.browser.session_map import start_idle_sweep, stop_idle_sweep
    start_idle_sweep()
    key_store = APIKeyStore()
    await key_store.init()
    app.state.api_key_store = key_store
    yield
    if _lark_available:
        stop_lark_listener()
    stop_heartbeat()
    stop_idle_sweep()
    await app.state.api_key_store.close()


app = FastAPI(
    title="Ethan Agent API",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/swagger",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if _lark_available:
    app.include_router(lark_router)

app.include_router(chat.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(memory.router, prefix="/api")
app.include_router(schedule.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(skills.router, prefix="/api")
app.include_router(docs.router, prefix="/api")
app.include_router(completions.router)  # /v1 OpenAI-compat, no /api prefix
app.include_router(logs.router, prefix="/api")
app.include_router(models.router, prefix="/api")
app.include_router(consent.router, prefix="/api")
app.include_router(browser_ws_router)  # /ws/browser, WebSocket, no prefix
app.include_router(browser_http_router, prefix="/api")  # /api/browser/shot/{name}

if _WEB_DIST.exists():
    app.mount("/_next", StaticFiles(directory=str(_WEB_DIST / "_next")), name="next-static")

    @app.get("/{path:path}")
    async def serve_spa(request: Request, path: str):
        file_path = _WEB_DIST / path
        # Exact static file (favicon, images, etc.)
        if file_path.is_file():
            return FileResponse(file_path)
        # Directory index (trailingSlash: true generates /chat/index.html)
        if (file_path / "index.html").is_file():
            return FileResponse(file_path / "index.html")
        # Flat .html (e.g. web_dist/skills.html)
        if (_WEB_DIST / f"{path}.html").is_file():
            return FileResponse(_WEB_DIST / f"{path}.html")
        # Dynamic route: Next.js static export only pre-generates __placeholder__
        # e.g. /chat/abc123 → chat/__placeholder__/index.html
        parts = path.strip("/").split("/")
        if len(parts) >= 2:
            placeholder = _WEB_DIST / "/".join(parts[:-1]) / "__placeholder__" / "index.html"
            if placeholder.is_file():
                return FileResponse(placeholder)
        # SPA fallback
        root_index = _WEB_DIST / "index.html"
        if root_index.is_file():
            return FileResponse(root_index)
        return Response(status_code=404)


def run_server(host: str = "0.0.0.0", port: int = 8900):
    import uvicorn
    uvicorn.run(app, host=host, port=port)
