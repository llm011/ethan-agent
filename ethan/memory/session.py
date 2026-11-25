"""Session 管理 — 对话会话的持久化。

每次对话是一个 Session，包含完整的消息历史，存储在 SQLite 中。
支持创建、恢复、列出、删除。

架构：进程级单例 SessionStore（通过 get_session_store() 获取），
同一 db_path 只维护一个连接实例，消除多连接写锁竞争。
"""

import asyncio
import logging
import re
import sqlite3
import types as _types
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from . import session_titles as _titles
from .session_assets import SessionAssetsMixin
from .session_checkpoints import SessionCheckpointsMixin
from .session_maintenance import SessionMaintenanceMixin
from .session_messages import SessionMessagesMixin
from .session_metadata import SessionMetadataMixin
from .session_queries import SessionQueriesMixin
from .session_schema import SessionSchemaMixin

logger = logging.getLogger(__name__)

# Bind extracted functions to this facade: old monkeypatch paths remain effective.
def _bind_function(fn):
    bound = _types.FunctionType(fn.__code__, globals(), fn.__name__, fn.__defaults__, fn.__closure__)
    bound.__kwdefaults__ = fn.__kwdefaults__
    bound.__annotations__ = fn.__annotations__
    return bound

for _name, _value in vars(_titles).items():
    if not _name.startswith("__"):
        globals()[_name] = _bind_function(_value) if isinstance(_value, _types.FunctionType) else _value

import sys as _sys  # noqa: E402

for _mixin in (SessionSchemaMixin, SessionAssetsMixin, SessionMessagesMixin, SessionMetadataMixin, SessionQueriesMixin, SessionMaintenanceMixin,):
    for _dependency, _object in vars(_sys.modules[_mixin.__module__]).items():
        if not _dependency.startswith("__") and _dependency not in globals():
            globals()[_dependency] = _object
    for _name, _value in list(vars(_mixin).items()):
        if isinstance(_value, _types.FunctionType):
            setattr(_mixin, _name, _bind_function(_value))

class SessionStore(SessionCheckpointsMixin, SessionSchemaMixin, SessionAssetsMixin, SessionMessagesMixin, SessionMetadataMixin, SessionQueriesMixin, SessionMaintenanceMixin):
    """SQLite-backed session storage; responsibility-specific mixins keep this API stable."""

# ── 进程级单例 SessionStore ──────────────────────────────────────────────────
_session_stores: dict[str, "SessionStore"] = {}
_session_store_lock = asyncio.Lock()


def _is_store_alive(store: "SessionStore") -> bool:
    """探活单例连接是否仍可复用。

    aiosqlite 的 Connection 没有公开的存活探针，这里读 `_running` 私有
    属性。包一层 try 是为了在 aiosqlite 升级把属性改名/改语义时不抛
    AttributeError——降级为 False 走 slow path 重建，最坏只是多一次
    init()，不会误判存活或静默失效。
    """
    try:
        return store._db is not None and bool(store._db._running)
    except AttributeError:
        return False


async def retry_on_db_locked(
    fn: Callable[..., Awaitable[Any]],
    *args: Any,
    retries: int = 5,
    base_delay: float = 0.5,
    **kwargs: Any,
) -> Any:
    """对 sqlite「database is locked / busy」做指数退避重试。

    sessions.db 为 DELETE journal 模式，写锁全库排他；多个连接（对话 producer、
    定时任务、heartbeat 各自的 store）并发写时，busy_timeout（30s）耗尽会抛
    OperationalError。用于「失败即永久丢失」的关键落库点（如最终回复持久化）；
    普通进度落库失败可容忍，无需经过本函数。非锁类错误不重试，直接抛出。
    """
    delay = base_delay
    for attempt in range(retries + 1):
        try:
            return await fn(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
            if attempt >= retries:
                raise
            logger.warning(
                "数据库撞锁，%.1fs 后重试 %s（第 %d/%d 次）: %s",
                delay,
                getattr(fn, "__name__", fn),
                attempt + 1,
                retries,
                e,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 8.0)
    raise AssertionError("unreachable")


async def session_exists(session_id: str) -> bool:
    """会话是否存在（便宜查询，不加载消息）。

    附件下载路由用它做归属校验：`store.load()` 会把整条会话的消息读出来并反序列化，
    每次开附件都做一遍太浪费；这里只 `SELECT 1 FROM sessions`。
    会话库不可用（还没初始化）时按「不存在」处理，路由返回 404，不抛 500。
    """
    try:
        store = await get_session_store()
        async with store._db.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)) as cursor:
            return await cursor.fetchone() is not None
    except Exception:  # noqa: BLE001 — 归属校验失败一律按不存在处理
        return False


async def get_session_store(db_path: Path | None = None) -> "SessionStore":
    """获取进程级单例 SessionStore。

    同一 db_path 只维护一个连接实例，消除多连接写锁竞争。
    所有路由和后台任务应通过本函数获取 store，不再各自 new/close。
    """
    if db_path is None:
        from ethan.core.paths import user_sessions_db_path

        db_path = user_sessions_db_path()
    key = str(db_path)

    # Fast path（无锁）：已存在且连接健康
    if key in _session_stores:
        store = _session_stores[key]
        if _is_store_alive(store):
            return store

    # Slow path：创建或重建
    async with _session_store_lock:
        # Double-check after acquiring lock
        if key in _session_stores:
            store = _session_stores[key]
            if _is_store_alive(store):
                return store
            # 连接已断，清除旧实例
            del _session_stores[key]
        store = SessionStore(db_path=db_path, _singleton=True)
        await store.init()
        _session_stores[key] = store
        return store


def list_archived_dbs() -> list[tuple[Path, str, str]]:
    """列出当前用户的所有归档 session DB，按起始日期排序。

    返回 [(path, start_date, end_date), ...]
    如 [(archive/sessions.2026-01-01~2026-02-10.db, '2026-01-01', '2026-02-10'), ...]
    """

    from ethan.core.paths import user_session_archive_dir

    archive_dir = user_session_archive_dir()
    if not archive_dir.exists():
        return []
    pattern = re.compile(r"sessions\.(\d{4}-\d{2}-\d{2})~(\d{4}-\d{2}-\d{2})(?:\.\d+)?\.db")
    result = []
    for f in archive_dir.glob("sessions.*~*.db"):
        m = pattern.match(f.name)
        if m:
            result.append((f, m.group(1), m.group(2)))
    result.sort(key=lambda x: x[1])
    return result
