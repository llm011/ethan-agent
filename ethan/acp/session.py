"""ACP session persistence: coding-agent sessions and mirror-session mapping."""
import json
import os
from pathlib import Path
from typing import Optional

from ethan.core.paths import user_data_dir


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


def set_mirror_session(cwd: str, session_id: str, user_id: str = "", agent: str = "claude") -> None:
    sessions = _load_sessions(user_id)
    sessions[_mirror_key(cwd, agent)] = session_id
    _save_sessions(sessions, user_id)


def clear_mirror_session(cwd: str, user_id: str = "", agent: str = "claude") -> None:
    sessions = _load_sessions(user_id)
    sessions.pop(_mirror_key(cwd, agent), None)
    _save_sessions(sessions, user_id)


# 反向映射：Ethan 镜像会话 id → (agent, cwd)。
# 用户直接在某条镜像会话里发消息时，据此查出该续接哪个 coding agent 的哪个 cwd。

def set_mirror_info(session_id: str, agent: str, cwd: str, user_id: str = "") -> None:
    sessions = _load_sessions(user_id)
    sessions[f"mirrorinfo::{session_id}"] = {"agent": agent, "cwd": os.path.abspath(cwd)}
    _save_sessions(sessions, user_id)


def get_mirror_info(session_id: str, user_id: str = "") -> Optional[dict]:
    """返回 {"agent", "cwd"}，非镜像会话返回 None。"""
    info = _load_sessions(user_id).get(f"mirrorinfo::{session_id}")
    return info if isinstance(info, dict) else None
