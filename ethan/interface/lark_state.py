"""飞书渠道共享状态与工具函数。

纯数据 + 轻量工具，无 IO，供 lark_stream / lark_agent_loop 复用：
- 会话映射（chat_id → session_id）
- 聊天锁（同 chat 串行化 Agent 处理）
- 任务登记表（供 /stop 取消进行中生成）
- 幂等去重（message_id 去重）
- 转发消息缓存（merge_forward 等待说明消息）
- 持久化辅助（lark_sessions.json）
- 工具进度气泡污染检测
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections import deque

logger = logging.getLogger(__name__)

# ── chat_id → session_id 内存映射 ─────────────────────────────────────────────
_lark_chat_map: dict[str, str] = {}

# ── chat 串行锁 ────────────────────────────────────────────────────────────────
_lark_chat_locks: dict[str, asyncio.Lock] = {}


def _get_chat_lock(chat_id: str) -> asyncio.Lock:
    """取（或创建）该 chat 的串行锁。锁对象复用，跨消息持久。"""
    lock = _lark_chat_locks.get(chat_id)
    if lock is None:
        lock = asyncio.Lock()
        _lark_chat_locks[chat_id] = lock
    return lock


# ── 任务登记表 ─────────────────────────────────────────────────────────────────
# chat_id -> 正在处理该 chat 消息的 Agent task 集合。供 /stop 取消进行中的生成。
# 事件分发是 fire-and-forget，同一 chat 连发多条会并发跑，故用 set 而非单值。
_lark_running_tasks: dict[str, set[asyncio.Task]] = {}


def _untrack_task(chat_id: str, task) -> None:
    """从登记表摘掉某个 task（每条消息结束时调）。空集合顺手清掉，避免泄漏。"""
    s = _lark_running_tasks.get(chat_id)
    if s is not None:
        s.discard(task)
        if not s:
            _lark_running_tasks.pop(chat_id, None)


async def _stop_lark_task(cid: str) -> bool:
    """取消该 chat 所有进行中的 Agent 生成任务。返回是否真的停了至少一个。"""
    tasks = _lark_running_tasks.get(cid)
    if not tasks:
        return False
    stopped = False
    for t in list(tasks):
        if not t.done():
            t.cancel()
            stopped = True
    return stopped


# ── 自然语言中止关键词 ─────────────────────────────────────────────────────────
_ABORT_KEYWORDS = {"停", "停下", "不用了", "取消", "stop", "中止", "停止"}

# ── 幂等去重 ──────────────────────────────────────────────────────────────────
_seen_message_ids: set[str] = set()
_seen_message_order: deque[str] = deque(maxlen=2000)


def _already_handled(message_id: str) -> bool:
    """命中返回 True（重复事件，应丢弃）；否则登记并返回 False。同步执行，天然原子。"""
    if not message_id:
        return False
    if message_id in _seen_message_ids:
        return True
    if len(_seen_message_order) == _seen_message_order.maxlen:
        _seen_message_ids.discard(_seen_message_order[0])
    _seen_message_order.append(message_id)
    _seen_message_ids.add(message_id)
    return False


# ── 转发消息缓存 ───────────────────────────────────────────────────────────────
_FORWARD_MSG_TYPES = {"merge_forward", "forward", "share_chat", "system_status", "complex"}
_FORWARD_CONTENT_RE = re.compile(
    r"^\s*(?:\[Merged forward|---------- Forwarded message|\[System message|\[Chat card)"
)
_forwarded_cache: dict[str, list[tuple[str, str, float]]] = {}
_FORWARDED_TTL = 120.0  # 秒


def _is_forwarded_message(msg_type: str, text: str) -> bool:
    if (msg_type or "") in _FORWARD_MSG_TYPES:
        return True
    return bool(_FORWARD_CONTENT_RE.match(text or ""))


def _cache_forwarded(chat_id: str, message_id: str, content: str) -> None:
    import time as _t
    _forwarded_cache.setdefault(chat_id, []).append((message_id, content, _t.time()))
    logger.debug("[Lark] cached forwarded msg chat=%s msg=%s len=%d", chat_id, message_id, len(content))


def _pop_forwarded(chat_id: str) -> str:
    import time as _t
    entries = _forwarded_cache.pop(chat_id, None)
    if not entries:
        return ""
    now = _t.time()
    fresh = [c for (_mid, c, ts) in entries if now - ts <= _FORWARDED_TTL]
    if not fresh:
        return ""
    if len(fresh) == 1:
        return fresh[0]
    return "\n\n".join(f"--- 转发消息 {i + 1} ---\n{c}" for i, c in enumerate(fresh))


# ── 持久化辅助 ────────────────────────────────────────────────────────────────
def _lark_map_file():
    from ethan.core.config import CONFIG_DIR
    return CONFIG_DIR / "memory" / "lark_sessions.json"


def _load_lark_map():
    import json
    f = _lark_map_file()
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return {}


def _save_lark_map(mapping: dict):
    import json
    f = _lark_map_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(mapping, ensure_ascii=False))


def _lark_welcomed() -> bool:
    from ethan.core.config import CONFIG_DIR
    return (CONFIG_DIR / "memory" / ".lark_welcomed").exists()


def _mark_lark_welcomed() -> None:
    from ethan.core.config import CONFIG_DIR
    f = CONFIG_DIR / "memory" / ".lark_welcomed"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.touch()


# ── 工具进度污染检测 ───────────────────────────────────────────────────────────
_TOOL_LINE_RE = re.compile(r'\*\*(?:📖|💻|🔍|🌐|📁|✏️|🧠|💾|⏰|📋|✨|👤|📝|🔧)')


def _looks_like_tool_trace(text: str) -> bool:
    """检测文本是否像工具调用过程格式（模型污染历史后在正文里模仿的格式）。"""
    if not text:
        return False
    lines = [l for l in text.split("\n") if l.strip()]
    if len(lines) < 2:
        return False
    tool_lines = sum(1 for l in lines if _TOOL_LINE_RE.search(l))
    return tool_lines >= 2
