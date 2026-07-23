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
    from ethan.core.paths import user_lark_sessions_path
    target = user_lark_sessions_path()
    # 迁移：旧路径 memory/lark_sessions.json → 新路径 lark_sessions.json
    if not target.exists():
        from ethan.core.paths import user_memory_dir
        old = user_memory_dir() / "lark_sessions.json"
        if old.exists():
            import shutil
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(old), str(target))
    return target


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
    from ethan.core.paths import user_lark_welcomed_path
    target = user_lark_welcomed_path()
    if not target.exists():
        # 迁移：旧路径 memory/.lark_welcomed
        from ethan.core.paths import user_memory_dir
        old = user_memory_dir() / ".lark_welcomed"
        if old.exists():
            import shutil
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(old), str(target))
    return target.exists()


def _mark_lark_welcomed() -> None:
    from ethan.core.paths import user_lark_welcomed_path
    f = user_lark_welcomed_path()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.touch()


# ── 群聊消息本地缓存 ───────────────────────────────────────────────────────────
# 仅群聊（oc_ 前缀），私聊不需要（session history 已有全量记录）。
_GROUP_CACHE_SIZE = 30
_group_chat_cache: dict[str, deque] = {}  # chat_id -> deque[{sender, text, time}]


def _cache_group_message(chat_id: str, sender_id: str, text: str, time_str: str) -> None:
    cache = _group_chat_cache.setdefault(chat_id, deque(maxlen=_GROUP_CACHE_SIZE))
    cache.append({"sender": sender_id, "text": text, "time": time_str})


def _get_group_context(chat_id: str, limit: int = 10) -> list[dict]:
    """从本地缓存读取群聊最近消息，不含最后一条（当前正在处理的消息本身），时间正序。"""
    cache = _group_chat_cache.get(chat_id)
    if not cache:
        return []
    items = list(cache)
    if items:
        items = items[:-1]
    return items[-limit:]


async def _should_respond_to_group_message(text: str, lark_cfg, event_data: dict | None = None) -> bool:
    """根据 group_response_mode 判断是否响应该群聊消息。P2P 消息不经此函数。"""
    import fnmatch
    mode = getattr(lark_cfg, "group_response_mode", "mention_only") or "mention_only"
    if mode == "always":
        return True
    if mode == "mention_only":
        # 优先用结构化 mentions 判断（lark-cli 展平后格式: {'key': '@_user_1', 'id': 'ou_xxx', 'name': 'xxx'}）
        # ⚠️ 不能只看 mentions 非空——群消息事件会带上所有被 @ 的对象（包括 @ 别的 bot / @ 普通人），
        # 必须校验 mentions 里是否包含本 bot。
        bot_name = getattr(lark_cfg, "bot_name", "") or ""
        if event_data:
            # lark-cli 提供的明确标志，优先级最高
            if event_data.get("is_mentioned") or event_data.get("mentioned_bot"):
                return True
            mentions = event_data.get("mentions") or []
            if mentions:
                # 校验是否有某个 mention 的 name 等于本 bot_name
                if bot_name:
                    for m in mentions:
                        _m_name = (m.get("name", "") or m.get("key", "") or "").lstrip("@")
                        if _m_name and _m_name == bot_name:
                            return True
                    # 有 mentions 但都不匹配本 bot → 别人 @ 了其它对象，不响应
                    return False
                # 没配 bot_name 无法精确判断，回退到文本匹配
        # 兜底文本匹配
        if bot_name and f"@{bot_name}" in text:
            return True
        # 没有 bot_name 配置且无结构化 mentions → 无法判断是否 @ 了 bot，不响应
        return False
    if mode == "keywords":
        keywords = getattr(lark_cfg, "group_keywords", []) or []
        tl = text.lower()
        return any(fnmatch.fnmatch(tl, f"*{kw.lower()}*") or kw.lower() in tl for kw in keywords)
    if mode == "llm_filter":
        try:
            from ethan.core.config import get_config
            from ethan.memory.consolidator import get_lite_model
            from ethan.providers.base import Message as _Msg
            from ethan.providers.manager import create_provider
            cfg = get_config()
            provider = create_provider(get_lite_model(cfg.defaults.model), cfg)
            hint = getattr(lark_cfg, "group_llm_filter_hint", "") or \
                "这条群聊消息是否需要AI助手回复？只回答 yes 或 no，不要其他内容。"
            resp = await provider.chat(
                [_Msg(role="user", content=f"{hint}\n\n消息：{text}")],
                system="你是一个判断器，只输出 yes 或 no。",
            )
            return "yes" in (resp.content or "").lower()
        except Exception:
            logger.warning("[Lark] llm_group_filter failed, defaulting to NOT respond")
            return False
    # 未知模式，安全起见不响应
    return False


# ── 工具进度污染检测 ───────────────────────────────────────────────────────────
_TOOL_LINE_RE = re.compile(r'\*\*(?:📖|💻|🔍|🌐|📁|✏️|🧠|💾|⏰|📋|✨|👤|📝|🔧)')


def _looks_like_tool_trace(text: str) -> bool:
    """检测文本是否像工具调用过程格式（模型污染历史后在正文里模仿的格式）。"""
    if not text:
        return False
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) < 2:
        return False
    tool_lines = sum(1 for ln in lines if _TOOL_LINE_RE.search(ln))
    return tool_lines >= 2
