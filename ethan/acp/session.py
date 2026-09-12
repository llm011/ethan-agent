"""ACP session persistence: coding-agent sessions and mirror-session mapping."""
import asyncio
import json
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from ethan.core.paths import user_data_dir

# acp_sessions.json 的读-改-写是「读全文件 → 改字典 → 覆盖写」，多个协程并发调用会
# 互相覆盖丢映射（如一批并行的 delegate_coding 落同一条镜像会话时，最后只留一个
# winner，其余映射丢失）。这里按 key 串行化这几个映射写操作，保证原子性。
# 用 defaultdict(asyncio.Lock) 复用锁对象，避免每次新建锁导致互斥失效。
_mapping_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _lock_for(key: str) -> asyncio.Lock:
    """取该映射 key 的串行锁（复用，跨调用持久）。"""
    return _mapping_locks[key]


@asynccontextmanager
async def mapping_lock(key: str):
    """对 `key` 上的映射做互斥：`async with mapping_lock(k): ...`。

    并发调用会串行执行临界区；不同 key 之间不互相阻塞。
    """
    async with _lock_for(key):
        yield


def _sessions_path(user_id: str = "") -> Path:
    # user_data_dir() 已按当前 profile 解析目录，user_id 仅保留接口兼容。
    return user_data_dir() / "acp_sessions.json"


def _load_sessions(user_id: str = "") -> dict:
    p = _sessions_path(user_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_sessions(sessions: dict, user_id: str = "") -> None:
    p = _sessions_path(user_id)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# 全局文件级锁：保护 acp_sessions.json 的整个「读 → 改 → 写」周期。所有写操作都经
# _update_sessions() 串行化。用文件级（而非 per-key）锁，因为同一个 dict 里任意两个
# key 的读改写都会互相覆盖——per-key 锁挡不住「A 改 key1 时 B 在读同一份快照改 key2」。
_sessions_lock = asyncio.Lock()


def _update_sessions(mutate, user_id: str = "") -> object:
    """在锁内原子地「读 → mutate(dict) → 写」，返回 mutate 的返回值（同步，不 await）。"""
    sessions = _load_sessions(user_id)
    result = mutate(sessions)
    _save_sessions(sessions, user_id)
    return result


async def update_sessions(mutate, user_id: str = "") -> object:
    """持锁完成整个读改写，避免并发覆盖丢映射。mutate(dict) 同步修改并返回结果。"""
    async with _sessions_lock:
        return _update_sessions(mutate, user_id)


def _session_key(cwd: str, agent: str) -> str:
    """会话键：按 agent + cwd 隔离，避免 claude/codex 在同一目录互相覆盖 session_id
    （两者 id 格式不同，混用会导致 resume 失败）。"""
    return f"{agent}::{os.path.abspath(cwd)}"


def get_session(cwd: str, user_id: str = "", agent: str = "claude") -> Optional[str]:
    """返回该 (agent, cwd) 上次 Coding Agent 会话的 session_id（用于续接多轮）。"""
    return _load_sessions(user_id).get(_session_key(cwd, agent))


def set_session(cwd: str, session_id: str, user_id: str = "", agent: str = "claude") -> None:
    sessions = _load_sessions(user_id)
    sessions[_session_key(cwd, agent)] = session_id
    _save_sessions(sessions, user_id)


def clear_session(cwd: str, user_id: str = "", agent: str = "claude") -> None:
    sessions = _load_sessions(user_id)
    sessions.pop(_session_key(cwd, agent), None)
    _save_sessions(sessions, user_id)


# ── 镜像会话映射：(agent, cwd) → Ethan 会话 id ──────────────────────────
# 让同一个 (agent, cwd) 的连续多轮委派累加到同一条 Ethan 镜像 session（多轮对话），
# 而不是每次新建一条。与 coding-agent 的 session_id 分开存（不同 key 前缀）。

def _mirror_key(cwd: str, agent: str) -> str:
    return f"mirror::{agent}::{os.path.abspath(cwd)}"


def get_mirror_session(cwd: str, user_id: str = "", agent: str = "claude") -> Optional[str]:
    return _load_sessions(user_id).get(_mirror_key(cwd, agent))


async def set_mirror_session(cwd: str, session_id: str, user_id: str = "", agent: str = "claude") -> None:
    """原子写：与并发 create 竞争时不会覆盖掉别的 key。"""
    await update_sessions(
        lambda s: s.__setitem__(_mirror_key(cwd, agent), session_id), user_id,
    )


def clear_mirror_session(cwd: str, user_id: str = "", agent: str = "claude") -> None:
    sessions = _load_sessions(user_id)
    sessions.pop(_mirror_key(cwd, agent), None)
    _save_sessions(sessions, user_id)


# 反向映射：Ethan 镜像会话 id → (agent, cwd)。
# 用户直接在某条镜像会话里发消息时，据此查出该续接哪个 coding agent 的哪个 cwd。

async def set_mirror_info(session_id: str, agent: str, cwd: str, user_id: str = "") -> None:
    await update_sessions(
        lambda s: s.__setitem__(
            f"mirrorinfo::{session_id}", {"agent": agent, "cwd": os.path.abspath(cwd)}
        ),
        user_id,
    )


def get_mirror_info(session_id: str, user_id: str = "") -> Optional[dict]:
    """返回 {"agent", "cwd"}，非镜像会话返回 None。"""
    info = _load_sessions(user_id).get(f"mirrorinfo::{session_id}")
    return info if isinstance(info, dict) else None
