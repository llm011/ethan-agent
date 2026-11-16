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
from ethan.core.services.heartbeat import start_heartbeat, stop_heartbeat
from ethan.desktop.ws_route import router as desktop_ws_router
from ethan.interface.routers import (
    agenda,
    annotations,
    ask_user,
    assets,
    auto_consent,
    background_tasks,
    chat,
    completions,
    consent,
    docs,
    documents,
    feishu_doc,
    files,
    images,
    knowledge,
    logs,
    memory,
    models,
    plugins,
    reading,
    releases,
    schedule,
    sessions,
    settings,
    skills,
    tts,
    ui_resources,
    wait_for_user,
)
from ethan.interface.routers.kernel_mcp import (
    get_kernel_tools_app as _get_kernel_tools_app,
)
from ethan.interface.routers.kernel_mcp import (
    get_kernel_tools_lifespan as _get_kernel_tools_lifespan,
)
from ethan.interface.routers.mcp_server import (
    get_mcp_app as _get_mcp_app,
)
from ethan.interface.routers.mcp_server import (
    get_mcp_lifespan as _get_mcp_lifespan,
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

# run_server 绑定的实际地址，供 lifespan 里的 watchdog 拉起逻辑取用
# （lifecycle 回调拿不到 run_server 的参数，只能通过模块级状态传递）。
_SERVER_BIND: tuple[str, int] = ("0.0.0.0", 8900)


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

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    if _lark_ready():
        # import lark_events 只顺带加载 lark_send/lark_stream——这俩的 lark_oapi 全是
        # 函数内 lazy import，所以这里 ~1.7s 而非 40s，不会让 restart 的端口探测超时。
        # （注意：uvicorn 是 lifespan.startup() 跑完之后才绑端口，所以这步必须快。）
        # lark_events 内部走 lark-cli 子进程收事件，lark_oapi 的重量级加载在子进程里，不挡本进程。
        from ethan.interface.channels.lark.events import start_lark_listener, stop_lark_listener
        start_lark_listener()
    from ethan.core.config import get_config as _gcfg
    if getattr(_gcfg().wechat, "enabled", False):
        from ethan.interface.channels.wechat.events import start_wechat_listener
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

    async def _prune_pending_uploads() -> None:
        # 用户传了附件却没发送 → 文件永远留在 uploads/_pending/。启动时清一次 7 天前的孤儿。
        from ethan.core.uploads import prune_pending

        await _asyncio.to_thread(prune_pending)

    _asyncio.create_task(_prune_pending_uploads())
    # 进程互相监控：写 server PID + 拉起 watchdog（独立进程，server 挂了它会重启）
    # worktree/开发场景设 ETHAN_NO_WATCHDOG=1 跳过，避免覆盖主 worktree 的 PID 文件被误杀
    from ethan.watchdog import ensure_watchdog_running, watchdog_disabled, write_server_pid

    if not watchdog_disabled():
        write_server_pid()
        # 把实际端口传给 watchdog，否则它只会盯 8900——服务跑在非默认端口时
        # 会被判"死亡"反复重启，且 _kill_server 的端口扫描会误杀别的实例。
        ensure_watchdog_running(port=_SERVER_BIND[1])
    # 主动启动调度器，确保持久化的定时任务在服务重启后自动恢复运行。
    # 不能依赖懒加载（首次 GET /api/schedule 才 start），否则服务空跑时 job 永远不触发。
    # 保存主 event loop 引用，供定时任务回调中 run_coroutine_threadsafe 使用。
    # 必须在 get_scheduler() 之前：scheduler 一启动就可能 misfire 触发回调，
    # 若此时 _server_loop 仍为 None 会走 fallback 线程路径（CLI/非 server 场景必炸）。
    from ethan.tools.builtin.schedule import set_server_loop
    set_server_loop(_asyncio.get_running_loop())
    from ethan.interface.routers.schedule import get_scheduler
    get_scheduler()
    # 日程对账：错过宽限窗口的一次性日程标 missed 并补发错过通知，
    # 丢 job 的 pending 日程补注册。必须在 scheduler 启动后执行。
    from ethan.scheduler.agenda import reconcile as _agenda_reconcile
    _agenda_reconcile()
    from ethan.browser.session_map import start_idle_sweep, stop_idle_sweep
    start_idle_sweep()
    key_store = APIKeyStore()
    await key_store.init()
    app.state.api_key_store = key_store
    # MCP 的 session manager 必须在这里启动：/mcp 是 mount 上去的子应用，Starlette 的
    # Mount 不转发子应用 lifespan，所以子应用自己挂的 lifespan 不会被执行；不 enter 的话
    # 每个 MCP 请求都抛 "Task group is not initialized" → 端点整体 HTTP 500。
    # 传 _MCP_APP 保证驱动的是 mount 出去的那个实例的 session manager。
    async with _get_mcp_lifespan(_MCP_APP)(app):
        # 内核工具端点同样需要顶层驱动 session manager（同 Mount 不转发 lifespan 的坑）。
        #
        # 注意：这里取的是 **模块级 _KERNEL_TOOLS_APP**，它与 mount 出去的是同一个
        # 实例——和 /mcp 一样必须保证「驱动的」与「处理请求的」一致。
        # 测试可以把它置 None 来跳过（见 test_mcp_server_endpoint 的 fixture），
        # 因为每个用例重建 /mcp 的 app 时，这个单例的 session manager 已被消耗。
        if _KERNEL_TOOLS_APP is not None:
            async with _get_kernel_tools_lifespan(_KERNEL_TOOLS_APP)(app):
                yield
        else:
            yield
    if _lark_ready():
        from ethan.interface.channels.lark.events import _wait_lark_listener_stopped, stop_lark_listener
        stop_lark_listener()
        await _wait_lark_listener_stopped()
    from ethan.interface.channels.wechat.events import stop_wechat_listener
    stop_wechat_listener()
    stop_heartbeat()
    stop_idle_sweep()
    await app.state.api_key_store.close()
    # 关闭 reranker/classifier 缓存的 provider 连接池（长跑进程退出时释放 fd）
    try:
        from ethan.memory.reranker import _close_judge_providers
        await _close_judge_providers()
    except Exception:
        pass
    try:
        from ethan.memory.classifier import _close_classify_providers
        await _close_classify_providers()
    except Exception:
        pass
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
app.include_router(agenda.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(skills.router, prefix="/api")
app.include_router(plugins.router, prefix="/api")
app.include_router(docs.router, prefix="/api")
app.include_router(documents.router, prefix="/api")  # /api/documents — 文档库（Agent 产出的文档）
app.include_router(completions.router)  # /v1 OpenAI-compat, no /api prefix
app.include_router(logs.router, prefix="/api")
app.include_router(models.router, prefix="/api")
app.include_router(consent.router, prefix="/api")
app.include_router(auto_consent.router, prefix="/api")  # /api/chat/auto-consent — 运行期切换超级权限
app.include_router(ask_user.router, prefix="/api")
app.include_router(wait_for_user.router, prefix="/api")
app.include_router(annotations.router, prefix="/api")
app.include_router(reading.router, prefix="/api")  # /api/reading — 网页辅助阅读模式标注（按 URL 存 JSON）
app.include_router(feishu_doc.router, prefix="/api")  # /api/feishu-doc — 扩展读飞书文档全文
app.include_router(background_tasks.router, prefix="/api")
app.include_router(ui_resources.router, prefix="/api")  # /api/ui-resources — 工具 UI 模板
app.include_router(images.router, prefix="/api")  # /api/images — image_search 下载的图片
app.include_router(tts.router, prefix="/api")  # /api/tts — 阅读模式朗读（代理本地 ethan-tts）
app.include_router(assets.router, prefix="/api")  # /api/assets — 用户上传的图片等资产
app.include_router(files.router, prefix="/api")  # /api/files — deliver_file 交付文件的下载/预览
app.include_router(releases.router, prefix="/api")  # /api/releases — Android APK 公开下载（302 到 CDN）
app.include_router(browser_ws_router)  # /ws/browser, WebSocket, no prefix
app.include_router(desktop_ws_router)  # /ws/desktop, WebSocket, no prefix
app.include_router(browser_http_router, prefix="/api")  # /api/browser/shot/{name}

# MCP Server endpoint: 豆包等外部 MCP 客户端通过 http://localhost:8900/mcp 连接
# 保存引用：lifespan 里要用**同一个** app 的 lifespan 来启动它的 session manager，
# 详见 _get_mcp_lifespan 的 docstring。
_MCP_APP = _get_mcp_app()
app.mount("/mcp", _MCP_APP)

# 内核工具端点：把 Ethan 的工具集暴露给外部内核（DSH / Claude Code 等）。
#
# 只在需要时挂载——不给不用外部内核的用户凭空多开一个攻击面。
# 判定：配置里 kernel_share_tools 不是 "off"，且至少有一个外部内核被启用过。
_KERNEL_TOOLS_APP = None
try:
    from ethan.core.config import get_config as _cfg_for_kernel

    _kcfg = _cfg_for_kernel()
    _share = getattr(_kcfg.defaults.kernel, "share_tools", "all") or "all"
    if _share != "off":
        _KERNEL_TOOLS_APP = _get_kernel_tools_app()
        app.mount("/kernel-tools", _KERNEL_TOOLS_APP)
except Exception:
    logging.getLogger(__name__).debug(
        "/kernel-tools 端点未挂载（配置读取或初始化失败）", exc_info=True
    )

def _serve_spa_response(web_dist: Path, path: str) -> Response:
    # API / WebSocket / MCP 路径绝不能回落到 index.html：
    # 否则未命中路由（例如旧版后端缺少新接口）会返回 200 text/html，
    # 前端 res.json() 在 Safari/WKWebView 中直接抛
    # "SyntaxError: The string did not match the expected pattern."，
    # 404 友好提示永远触发不到。
    first_seg = path.lstrip("/").split("/", 1)[0]
    if first_seg in {"api", "ws", "mcp", "kernel-tools", "v1"}:
        return Response(status_code=404)
    file_path = web_dist / path
    # Exact static file (favicon, images, etc.)
    if file_path.is_file():
        return FileResponse(file_path)
    # Directory index (trailingSlash: true generates /chat/index.html)
    if (file_path / "index.html").is_file():
        return FileResponse(file_path / "index.html")
    # Flat .html (e.g. web_dist/skills.html)
    if (web_dist / f"{path}.html").is_file():
        return FileResponse(web_dist / f"{path}.html")
    # 动态路由回落，两种形态都要支持：
    #
    # 1) 可选 catch-all `[[...id]]`（当前 chat 用的）：产物只有 `chat/index.html`
    #    一条，任意 `/chat/<任意id>` 都由它接管。所以先逐层往上找最近的
    #    `index.html`——/chat/a/b 找不到就用 chat/a/index.html，再找不到用
    #    chat/index.html。
    #
    # 2) 必选动态段 `[id]`（旧写法）：静态导出只预生成 `__placeholder__`，
    #    产物是 `xxx/__placeholder__/index.html`。保留这段兼容，
    #    避免其它动态路由（如 /settings/[tab]）受影响。
    parts = path.strip("/").split("/")
    for cut in range(len(parts), 0, -1):
        prefix_dir = web_dist.joinpath(*parts[:cut])
        index = prefix_dir / "index.html"
        if index.is_file():
            return FileResponse(index)
        placeholder = prefix_dir / "__placeholder__" / "index.html"
        if placeholder.is_file():
            return FileResponse(placeholder)
    # 真的什么都匹配不上才回落到站点根（首页），而不是把 /chat/xxx 也送回去
    root_index = web_dist / "index.html"
    if root_index.is_file():
        return FileResponse(root_index)
    return Response(status_code=404)


if _WEB_DIST.exists():
    # 产物陈旧自检：web_dist 不在 git 里，代码更新后忘记重建会让新前端路由
    # 静默失效（历史故障：会话详情页全白屏，后端数据完好）。只警告不阻塞。
    try:
        from ethan.interface.web_dist_check import warn_if_stale as _warn_if_stale

        _warn_if_stale(_WEB_DIST)
    except Exception:  # noqa: BLE001 - 自检失败绝不影响启动
        logging.getLogger(__name__).debug("web_dist 陈旧自检未执行", exc_info=True)

    app.mount("/_next", StaticFiles(directory=str(_WEB_DIST / "_next")), name="next-static")

    @app.get("/{path:path}")
    async def serve_spa(request: Request, path: str):
        return _serve_spa_response(_WEB_DIST, path)


def _port_is_served(host: str, port: int) -> bool:
    """端口上是否已有健康的 ethan 实例在应答（而非仅仅被占用）。

    只探测 /api/health：别的进程恰好占了端口不算「ethan 已在跑」，不该据此拒绝
    启动；而一个健康的 ethan 已经在这个端口上时，再起一个必然绑不上。
    """
    import urllib.error
    import urllib.request

    probe_host = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    try:
        req = urllib.request.Request(
            f"http://{probe_host}:{port}/api/health",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            body = resp.read(512).decode("utf-8", "replace")
        # 只有确认是 ethan 才判定「已在跑」，避免误判其它占用同端口的服务
        return resp.status == 200 and "ethan" in body.lower()
    except Exception:
        return False


def _find_db_conflicts() -> list[tuple[int, str]]:
    """找出其它正在写同一个 sessions.db 的 ethan 进程（不含自己）。

    conflict 的本质是抢**同一个 SQLite 文件**，不是抢端口——两个实例用不同端口
    照样互锁。判据复用 ``cli._find_conflicting_servers``，避免两处判据各自漂移
    （判据错过一次，幽灵实例就能双写全库排他写锁）。

    import 放在函数内，是为了不在 api.py 的模块级引入 cli 依赖：api.py 会被
    uvicorn 直接加载，而 cli 顶层 import typer。注意这**并不能**避免 Typer 进入
    进程（真走到这里就会加载它），只是把它推迟到需要判据的那一刻，别拖累不检查
    冲突的调用路径。

    任何异常都降级为「无冲突」——这是一道防御性闸门，不该因为 lsof 缺失
    / pgrep 行为差异而让服务起不来。
    """
    try:
        from ethan.interface.cli import _find_conflicting_servers

        return _find_conflicting_servers()
    except Exception:
        logging.getLogger(__name__).warning(
            "[Server] 重复实例检测不可用（检测本身失败），跳过", exc_info=True
        )
        return []


def run_server(host: str | None = None, port: int | None = None, *, force: bool = False):
    import uvicorn

    # 未显式指定时跟随 config.yaml 的 server.*，再回退内置默认。
    # config 读不到（首次运行/config 损坏）也不该让服务起不来，故兜底默认值。
    if host is None or port is None:
        try:
            from ethan.core.config import get_config

            srv = get_config().server
            host = host if host is not None else srv.host
            port = port if port is not None else srv.port
        except Exception:
            pass
    host = host or "0.0.0.0"
    port = port or 8900

    # 单实例锁必须先于下面所有「先查后做」的闸门：那两道闸门只回答「此刻有没有
    # 人在」，两个进程同时启动会同时听到「没有」，然后一起跑完 lifespan 才在 bind
    # 时撞 Errno 48。锁把「检查 + 启动」变成一个原子区间，第二个进程在检查之前
    # 就直接退出。详见 ethan/interface/serve_lock.py。
    #
    # force=True（`ethan serve --force`）明确表示「我知道自己在干什么」，不加锁；
    # ETHAN_NO_WATCHDOG=1 仍加锁，但按端口 + 数据目录分桶（多个 worktree 各自起
    # 实例是合法的，同一端口同一数据目录重复起才拦）。
    if not force:
        from ethan.interface import serve_lock

        got_lock, holder = serve_lock.acquire(port)
        if not got_lock:
            logging.getLogger(__name__).error(
                "[Server] 另一个 ethan serve 正在启动或已监听 %s:%d%s，拒绝重复启动。"
                "如需重启请先运行 `ethan serve stop`。",
                host,
                port,
                f"（pid={holder}）" if holder else "",
            )
            raise SystemExit(1)

    # 端口上已有健康的 ethan：立刻退出，别启动。
    # 这一条是「服务反复失联」的根治点——被 launchd/watchdog/桌面端拉起的重复实例
    # 曾在这里一路跑完 lifespan（含 memory reindex，耗时数十秒），最后才在 uvicorn
    # 绑端口时报 Errno 48，而 uvicorn 并不终止进程，于是挂成一个不监听任何端口、
    # 却持续占 CPU 的僵尸，并把 server.pid / heartbeat / 调度器全部污染一遍。
    # 重复拉起时应当干脆地失败，让上层（launchd 的 KeepAlive）不再得到「起来了」的假象。
    if _port_is_served(host, port):
        logging.getLogger(__name__).error(
            "[Server] 端口 %s:%d 上已有健康的 ethan 实例在运行，拒绝重复启动。"
            "如需重启请先运行 `ethan serve stop`。",
            host,
            port,
        )
        raise SystemExit(1)

    # 端口不同 ≠ 安全：真正互锁的是同一个 sessions.db（单写者模型）。
    # 上面那条只查端口，于是「被 watchdog 用别的端口拉起」的实例能一路穿透到这里，
    # 跑完整个 lifespan（scheduler / heartbeat / channel listener 全起来），
    # 和主实例双写 DELETE 模式的全库排他写锁 —— 实测表现为 journal 卡住不释放、
    # 连纯 SELECT 都 `database is locked`、前端「打开会话一直加载」。
    # 判据必须取「谁打开了同一个 sessions.db」，与端口无关；
    # ETHAN_NO_WATCHDOG=1 沿用 cli.py 的语义：开发/测试场景明确放行。
    #
    # force=True（`ethan serve --force`）也要放行：cli 层已用 `--force` 跳过它自己
    # 那道检测，这里若不再放行，`--force` 就完全失效（错误提示里还在推荐它）。
    from ethan.watchdog import watchdog_disabled

    if not force and not watchdog_disabled():
        conflicts = _find_db_conflicts()
        if conflicts:
            logging.getLogger(__name__).error(
                "[Server] 已有 ethan 实例在使用同一个 sessions.db，拒绝重复启动"
                "（端口不同也会抢同一把全库写锁）。冲突进程: %s。"
                "如需重启请先运行 `ethan serve stop`；"
                "确认要强行启动可加 `--force`（不推荐，会锁冲突）。",
                ", ".join(f"pid={pid}" for pid, _ in conflicts),
            )
            raise SystemExit(1)

    # lifespan 里的 watchdog 拉起逻辑拿不到这里的参数，通过模块级状态传递
    global _SERVER_BIND
    _SERVER_BIND = (host, port)

    # 暴露端口给同进程内的后台任务回调（background_task 用它拼 base url，而非写死 8900）
    os.environ["ETHAN_SERVER_PORT"] = str(port)
    try:
        uvicorn.run(app, host=host, port=port)
    except SystemExit:
        raise
    except BaseException:
        # 绑端口失败等启动期异常：必须让进程真的结束。
        # uvicorn 在 bind 失败时只打日志、不抛错也不退出，进程会带着一堆已启动的
        # 后台线程（调度器/心跳/channel listener）继续挂着——正是僵尸的来源。
        logging.getLogger(__name__).exception("[Server] uvicorn 异常退出")
        raise SystemExit(1)
