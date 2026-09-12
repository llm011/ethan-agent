"""ACP session persistence: coding-agent sessions and mirror-session mapping."""
import asyncio
import json
import os
import weakref
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from ethan.core.paths import user_data_dir

# acp_sessions.json 的读-改-写是「读全文件 → 改字典 → 覆盖写」，多个协程并发调用会
# 互相覆盖丢映射（如一批并行的 delegate_coding 落同一条镜像会话时，最后只留一个
# winner，其余映射丢失）。这里按 key 串行化这几个映射写操作，保证原子性。
#
# 关于锁的存活：
# - 用 WeakValueDictionary 而非 defaultdict：每个新的 (agent, cwd) 都会要一把锁，
#   长跑 server 里 work_dir 一多，defaultdict 会永久驻留每把锁（无上限增长）。弱引用
#   让锁在最后一个持锁者/等待者释放后被回收。必须用「外部强引用 + 弱值」配对——
#   只靠 get 返回的临时引用，await 期间锁可能被 GC 掉，等于没锁。
# - asyncio.Lock 绑定创建它的 event loop，跨 loop 复用会炸（测试里按 loop 重置就是
#   绕这个）。生产是单 loop，没问题；若将来引入多 loop（如每请求一个 loop），
#   需改成按 loop 分桶。
_mapping_locks: "weakref.WeakValueDictionary[str, asyncio.Lock]" = weakref.WeakValueDictionary()
# 暂存「正在被使用」的锁对象，避免 await 临界区期间被弱引用表回收。
_mapping_locks_pinned: dict[str, asyncio.Lock] = {}


def _lock_for(key: str) -> asyncio.Lock:
    """取该映射 key 的串行锁（复用；无则新建并登记）。

    调用方必须自行持有返回的锁对象直到临界区结束（见 mapping_lock）。
    """
    lock = _mapping_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _mapping_locks[key] = lock
    return lock


@asynccontextmanager
async def mapping_lock(key: str):
    """对 `key` 上的映射做互斥：`async with mapping_lock(k): ...`。

    并发调用会串行执行临界区；不同 key 之间不互相阻塞。

    `_mapping_locks_pinned` 在本协程持锁期间强引用该锁，防止弱引用表在 await 让出
    时把它回收掉——回收后下一次 _lock_for 会新建一把，互斥就失效了。
    """
    lock = _lock_for(key)
    _mapping_locks_pinned.setdefault(key, lock)
    try:
        async with lock:
            yield
    finally:
        # 本协程放锁后再摘掉强引用；若同 key 还有别的等待者，它们各自也 pin 了一份。
        if _mapping_locks_pinned.get(key) is lock:
            _mapping_locks_pinned.pop(key, None)


def _sessions_path(user_id: str = "") -> Path:
    # user_data_dir() 已按当前 profile 解析目录，user_id 仅保留接口兼容。
    return user_data_dir() / "acp_sessions.json"


class SessionsFileCorruptError(RuntimeError):
    """acp_sessions.json 存在但读不出来（半截写入 / 解析失败）。

    刻意与「文件不存在」区分：不存在是正常的首次使用，返回 {} 即可；解析失败若也
    返回 {}，后面的读-改-写就会拿这个空 dict 当基底整份覆盖回去，把原文件里其它
    映射全抹掉（损坏被放大）。故这里抛出去，让调用方跳过这次写。
    """


def _load_sessions(user_id: str = "") -> dict:
    """读 acp_sessions.json。文件不存在 → {}；存在但解析失败 → 抛 SessionsFileCorruptError。"""
    p = _sessions_path(user_id)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise SessionsFileCorruptError(f"无法解析 {p}: {e}") from e
    if not isinstance(data, dict):
        raise SessionsFileCorruptError(f"{p} 顶层不是对象: {type(data).__name__}")
    return data


def _save_sessions(sessions: dict, user_id: str = "") -> None:
    p = _sessions_path(user_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")


# 全局文件级锁：保护 acp_sessions.json 的整个「读 → 改 → 写」周期。所有写操作都经
# _update_sessions() 串行化。用文件级（而非 per-key）锁，因为同一个 dict 里任意两个
# key 的读改写都会互相覆盖——per-key 锁挡不住「A 改 key1 时 B 在读同一份快照改 key2」。
_sessions_lock = asyncio.Lock()


def _update_sessions(mutate, user_id: str = "") -> object:
    """在锁内原子地「读 → mutate(dict) → 写」，返回 mutate 的返回值（同步，不 await）。

    读失败（文件损坏）会抛 SessionsFileCorruptError，此时**不写回**——宁可这次写失败，
    也不拿空 dict 覆盖掉原文件里其它映射。写失败同样是异常，不再静默吞掉。
    """
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
    try:
        return _load_sessions(user_id).get(_session_key(cwd, agent))
    except SessionsFileCorruptError:
        # 读侧放宽：续接信息拿不到就当作无历史（下次新建），由写侧报错暴露损坏。
        return None


async def set_session(cwd: str, session_id: str, user_id: str = "", agent: str = "claude") -> None:
    """写 coding-agent 的 session_id（供下次 resume）。走共用文件锁，与镜像映射互斥。"""
    await update_sessions(lambda s: s.__setitem__(_session_key(cwd, agent), session_id), user_id)


async def clear_session(cwd: str, user_id: str = "", agent: str = "claude") -> None:
    """清除该 (agent, cwd) 的 session_id（超时/坏会话/reset_session 时调用）。

    走共用文件锁：这个「读全文件 → pop 自己的 key → 整份覆盖写」在旧实现里是同步
    无锁的，会与并发写入的镜像映射互相覆盖（PR 里只堵了 mirror 那一半）。
    """
    await update_sessions(lambda s: s.pop(_session_key(cwd, agent), None), user_id)


# ── 镜像会话映射：(agent, cwd) → Ethan 会话 id ──────────────────────────
# 让同一个 (agent, cwd) 的连续多轮委派累加到同一条 Ethan 镜像 session（多轮对话），
# 而不是每次新建一条。与 coding-agent 的 session_id 分开存（不同 key 前缀）。

def _mirror_key(cwd: str, agent: str) -> str:
    return f"mirror::{agent}::{os.path.abspath(cwd)}"


def get_mirror_session(cwd: str, user_id: str = "", agent: str = "claude") -> Optional[str]:
    try:
        return _load_sessions(user_id).get(_mirror_key(cwd, agent))
    except SessionsFileCorruptError:
        return None


async def set_mirror_session(cwd: str, session_id: str, user_id: str = "", agent: str = "claude") -> None:
    """原子写：与并发 create 竞争时不会覆盖掉别的 key。"""
    await update_sessions(
        lambda s: s.__setitem__(_mirror_key(cwd, agent), session_id), user_id,
    )


async def clear_mirror_session(cwd: str, user_id: str = "", agent: str = "claude") -> None:
    """清除镜像映射。与 set_mirror_session 共用文件锁，避免互相覆盖。"""
    await update_sessions(lambda s: s.pop(_mirror_key(cwd, agent), None), user_id)


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
    try:
        info = _load_sessions(user_id).get(f"mirrorinfo::{session_id}")
    except SessionsFileCorruptError:
        return None
    return info if isinstance(info, dict) else None
