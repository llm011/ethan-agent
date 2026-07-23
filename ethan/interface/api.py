"""FastAPI 入口 — 挂载所有路由模块。"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from ethan import __version__
from ethan.browser.http_route import router as browser_http_router
from ethan.browser.ws_route import router as browser_ws_router
from ethan.core.heartbeat import start_heartbeat, stop_heartbeat
from ethan.interface.routers import (
    annotations,
    assets,
    background_tasks,
    chat,
    completions,
    consent,
    docs,
    images,
    knowledge,
    logs,
    memory,
    models,
    schedule,
    sessions,
    settings,
    skills,
    ui_resources,
)
from ethan.memory.api_keys import APIKeyStore

# 飞书接入走 WebSocket 长连接（lark_events.py，由 lifespan 里 start_lark_listener 启动），
# 不挂任何 lark 路由。lark.py 里的 /lark/webhook 是旧的 webhook 模式遗留代码——
# 它在模块顶层 `import lark_oapi`，若在这里 include_router 会触发 ~40s 的冷启动卡顿
# （lark_oapi 加载一堆业务域 model 包），且 uvicorn 在 lifespan.startup() 之后才绑端口，
# 所以即便挪进 lifespan 也照样挡住 restart 的端口探测。webhook 路由当前无人使用，直接不挂。
_lark_available: bool | None = None


def _lark_ready() -> bool:
    """是否可用飞书渠道。检测 lark_oapi 包已安装且飞书已配置。

    lifespan 据此决定是否 start_lark_listener；start_lark_listener 内部走 lark-cli
    子进程，lark_send/lark_stream 里的 lark_oapi 都是函数内 lazy import，所以探测本身
    不会卡冷启动。
    """
    global _lark_available
    if _lark_available is None:
        import importlib.util
        if importlib.util.find_spec("lark_oapi") is None:
            _lark_available = False
            logging.getLogger(__name__).info(
                "lark-oapi 未安装，飞书渠道不可用。"
                "如需启用，运行 ethan setup → 渠道 → 飞书"
            )
        else:
            from ethan.core.config import get_config
            lark_cfg = getattr(get_config(), "lark", None)
            if lark_cfg and lark_cfg.app_id:
                if not lark_cfg.enabled:
                    # 向下兼容：老用户配了 app_id 但没有 enabled 字段，
                    # 不静默失效，而是提示并仍然启用。
                    logging.getLogger(__name__).warning(
                        "飞书已配置 app_id 但 enabled 未设为 true，"
                        "为向下兼容仍启动飞书渠道。"
                        "建议在 config.yaml 的 lark 段添加 enabled: true"
                    )
                _lark_available = True
            else:
                _lark_available = False
    return _lark_available


import os as _os  # noqa: E402

_WEB_DIST = Path(_os.environ.get("WEB_DIST_PATH") or (Path(__file__).parent.parent / "web_dist"))


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

    if _lark_ready():
        # import lark_events 只顺带加载 lark_send/lark_stream——这俩的 lark_oapi 全是
        # 函数内 lazy import，所以这里 ~1.7s 而非 40s，不会让 restart 的端口探测超时。
        # （注意：uvicorn 是 lifespan.startup() 跑完之后才绑端口，所以这步必须快。）
        # lark_events 内部走 lark-cli 子进程收事件，lark_oapi 的重量级加载在子进程里，不挡本进程。
        from ethan.interface.lark_events import start_lark_listener, stop_lark_listener
        start_lark_listener()
    from ethan.core.config import get_config as _gcfg
    if getattr(_gcfg().wechat, "enabled", False):
        from ethan.interface.wechat_events import start_wechat_listener
        start_wechat_listener()
    start_heartbeat()
    # facts.json → memories 一次性迁移（结构化记忆统一）：本地 SQLite+文件操作，
    # 量小秒级完成，但仍放后台线程，不挡 lifespan 完成后的端口绑定。
    # 迁移后顺带重建 memory 向量索引（准入语义配对/混合召回的底层）。
    import asyncio as _asyncio

    async def _migrate_and_reindex() -> None:
        from ethan.core.context import ETHAN_USER_ID
        from ethan.core.users import get_user_store
        from ethan.memory.legacy_migration import migrate_all_users
        from ethan.memory.memory_vectors import reindex_all

        await _asyncio.to_thread(migrate_all_users)
        for uid in get_user_store().all_user_ids():
            token = ETHAN_USER_ID.set(uid)
            try:
                await _asyncio.to_thread(reindex_all)
            except Exception:
                import logging
                logging.getLogger(__name__).exception("[Startup] memory reindex failed for %s", uid)
            finally:
                ETHAN_USER_ID.reset(token)

    _asyncio.create_task(_migrate_and_reindex())
    # 进程互相监控：写 server PID + 拉起 watchdog（独立进程，server 挂了它会重启）
    # worktree/开发场景设 ETHAN_NO_WATCHDOG=1 跳过，避免覆盖主 worktree 的 PID 文件被误杀
    if os.environ.get("ETHAN_NO_WATCHDOG") != "1":
        from ethan.watchdog import ensure_watchdog_running, write_server_pid
        write_server_pid()
        ensure_watchdog_running()
    # 主动启动调度器，确保持久化的定时任务在服务重启后自动恢复运行。
    # 不能依赖懒加载（首次 GET /api/schedule 才 start），否则服务空跑时 job 永远不触发。
    from ethan.interface.routers.schedule import get_scheduler
    get_scheduler()
    from ethan.browser.session_map import start_idle_sweep, stop_idle_sweep
    start_idle_sweep()
    key_store = APIKeyStore()
    await key_store.init()
    app.state.api_key_store = key_store
    yield
    if _lark_ready():
        from ethan.interface.lark_events import _wait_lark_listener_stopped, stop_lark_listener
        stop_lark_listener()
        await _wait_lark_listener_stopped()
    from ethan.interface.wechat_events import stop_wechat_listener
    stop_wechat_listener()
    stop_heartbeat()
    stop_idle_sweep()
    await app.state.api_key_store.close()
    # 清理 server PID 文件
    from ethan.watchdog import SERVER_PID_FILE, _remove_pid
    _remove_pid(SERVER_PID_FILE)


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

# 飞书接入走 WebSocket（lark_events.py 的 start_lark_listener），不挂任何路由。
# 旧的 /lark/webhook（lark.py）遗留但未用——挂它会触发顶层 import lark_oapi 卡 40s。
# refactor-note: 若未来需恢复 webhook 模式，必须把 import lark_oapi 移到函数内，避免
# 模块级 import 卡冷启动。lark_send.py 里所有的 lark_oapi 都是函数内 lazy import，是
# 正确的延迟加载模式。

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
app.include_router(annotations.router, prefix="/api")
app.include_router(background_tasks.router, prefix="/api")
app.include_router(ui_resources.router, prefix="/api")  # /api/ui-resources — 工具 UI 模板
app.include_router(images.router, prefix="/api")  # /api/images — image_search 下载的图片
app.include_router(assets.router, prefix="/api")  # /api/assets — 用户上传的图片等资产
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
    import os

    import uvicorn
    # 暴露端口给同进程内的后台任务回调（background_task 用它拼 base url，而非写死 8900）
    os.environ["ETHAN_SERVER_PORT"] = str(port)
    uvicorn.run(app, host=host, port=port)
