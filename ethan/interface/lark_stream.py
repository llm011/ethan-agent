"""飞书消息处理：命令路由 + Agent 流式回复（_handle_message）。

依赖 lark_send（收发 IO）/ lark_render（渲染）/ lark_state（共享状态）。

输出形态（基础能力，勿改坏）：
- 工具进度 → post 富文本气泡（流式 update）
- 最终回答 → interactive 卡片（流式 patch）
- ui_card 工具产出的自定义卡片（lark_card）→ 额外发一条 interactive 卡片（增量，可有可无）
"""
from __future__ import annotations

import asyncio
import logging

from ethan.interface.lark_event_handlers import (
    _handle_card_action,
    _handle_message_read,
    _handle_reaction,
)
from ethan.interface.lark_send import (
    TypingState,
    _send_interactive_card,
    _send_reply,
)
from ethan.interface.lark_state import (
    _ABORT_KEYWORDS,
    _already_handled,
    _append_debounce_queue,
    _cache_forwarded,
    _cache_group_message,
    _cancel_debounce_timer,
    _get_chat_lock,
    _get_debounce_queue,
    _init_debounce_queue,
    _is_forwarded_message,
    _lark_chat_map,  # noqa: F401 — re-exported; lark_agent lazy-imports from here
    _lark_running_tasks,  # noqa: F401
    _lark_welcomed,  # noqa: F401
    _load_lark_map,  # noqa: F401
    _looks_like_tool_trace,  # noqa: F401
    _mark_lark_welcomed,  # noqa: F401
    _pop_debounce_queue,
    _pop_forwarded,  # noqa: F401
    _save_lark_map,  # noqa: F401
    _schedule_debounce_flush,
    _should_respond_to_group_message,
    _stop_lark_task,
    _untrack_task,  # noqa: F401
)

logger = logging.getLogger(__name__)


async def _run_debounce_flush(chat_id: str, sender_open_id: str) -> None:
    """实际触发合并后的 Agent 调用。从队列取出所有文本拼接，用第 1 条的 event_data/identity。
    走原来的串行锁 + _handle_agent_message，保持行为一致。"""
    from ethan.interface.lark_agent import _handle_agent_message
    q = _pop_debounce_queue(chat_id, sender_open_id)
    if q is None:
        return
    merged_text = "\n".join(q["texts"])
    first_msg_id = q["message_ids"][0] if q["message_ids"] else ""
    ts = q["ts"]
    try:
        async with _get_chat_lock(chat_id):
            await _handle_agent_message(
                q["event_data"],
                chat_id=chat_id,
                message_id=first_msg_id,
                text=merged_text,
                sender_open_id=sender_open_id,
                owner_open_id=q["owner_open_id"],
                is_owner=q["is_owner"],
                owner_claimed=q["owner_claimed"],
                btw_mode=q["btw_mode"],
                ts=ts,
            )
    except Exception:
        # 锁本身或 _handle_agent_message 意外抛出时兜底清理表情，避免残留
        await ts.clear()
        raise


async def _delayed_debounce_flush(chat_id: str, sender_open_id: str, delay: float) -> None:
    """定时器回调：等 delay 秒后触发 flush。"""
    await asyncio.sleep(delay)
    await _run_debounce_flush(chat_id, sender_open_id)


async def _flush_debounce_for_sender(chat_id: str, sender_open_id: str) -> None:
    """立即 flush 同 sender 的 debounce 队列（命令路径 bypass 时用）。
    取消定时器并立即触发合并 Agent 调用。"""
    q = _get_debounce_queue(chat_id, sender_open_id)
    if q is None:
        return
    await _cancel_debounce_timer(q)
    await _run_debounce_flush(chat_id, sender_open_id)


async def _cancel_debounce_for_sender(chat_id: str, sender_open_id: str) -> None:
    """cancel 同 sender 的 debounce 队列（/stop/中止关键词用）。
    丢弃队列内容并清理第 1 条消息上的 THINKING 表情。"""
    q = _pop_debounce_queue(chat_id, sender_open_id)
    if q is None:
        return
    await _cancel_debounce_timer(q)
    try:
        await q["ts"].clear()
    except Exception:
        logger.debug("[Lark] clear ts on cancel debounce failed", exc_info=True)


async def _handle_message(event_data: dict) -> None:
    """处理收到的消息事件，调用 Agent 并流式回复。

    lark-cli event consume 输出的是扁平结构：
    {"chat_id": "oc_xxx", "content": "text", "message_id": "om_xxx",
     "message_type": "text", "sender_id": "ou_xxx", ...}

    流式策略：
    - 积累 chunk 直到 ≥80 字符或距上次发送 ≥2 秒
    - 首次 flush：移除 THINKING 表情后发送第一条消息
    - 后续 flush：lark-cli 不支持 patch，直接追加新消息
    - 最终确保完整内容已发出
    """

    # lark-cli 已经把 event 字段展平，直接从顶层读取
    # post（图文混合）/ image / file / audio / video 的 content 也是 lark-cli 预渲染的可读文本：
    # post → markdown（图片占位 ![Image](img_xxx) + 正文）
    # image → ![Image](img_xxx)
    # file/audio/video → <file key="file_xxx" .../> 等
    _HANDLED_TYPES = {"text", "post", "image", "file", "audio", "video"}
    msg_type = event_data.get("message_type", "")
    if msg_type not in _HANDLED_TYPES:
        return

    text = event_data.get("content", "").strip()
    if not text:
        return

    chat_id = event_data.get("chat_id", "")
    message_id = event_data.get("message_id", "")

    # 幂等去重：飞书 at-least-once 重投同一事件时直接丢弃，避免重复处理（重复回复 + 双份 token 统计）。
    # 放在转发缓存之前——否则重投的转发消息会被重复缓存，注入时内容翻倍。
    if _already_handled(message_id):
        logger.info("[Lark] duplicate event dropped: message_id=%s", message_id)
        return

    # ── 批量转发消息：缓存但不进 agent ──
    # 用户「合并转发」一批消息给 bot 时，单看转发内容 agent 不知道要干嘛；但用户转完一般还会
    # 紧跟一条说明消息（"总结下"/"这个怎么处理"）。所以转发消息只缓存，等同 chat 后续消息来时
    # 把缓存内容拼进其上下文一起处理。message_type 命中 merge_forward 等直接判；兜底看 content
    # 前缀（lark-cli 偶尔把转发渲染成 post/text，靠 [Merged forward…]/---------- Forwarded 识别）。
    # 注意：post 里的转发会被 lark-cli 渲染成以 [Merged forward] 开头的可读文本，仍属此列。
    # 转发消息故意绕过下方的 60s 过期过滤：它是「待后续说明消息消费」的暂存上下文，重连重放时
    # 应保留而非丢弃（自有 120s TTL 兜底，超时自动失效）。
    if _is_forwarded_message(msg_type, text):
        _cache_forwarded(chat_id, message_id, text)
        return

    # 过滤过期事件：进程重启后 _seen_message_ids 清空，lark-cli 重连会重放旧消息；
    # 超过 60 秒的消息直接丢弃，避免 restart 后处理历史命令（如 /help）刷屏。
    import time as _t
    _create_ms = int(event_data.get("create_time", "0") or "0")
    if _create_ms and (_t.time() * 1000 - _create_ms) > 60_000:
        logger.info("[Lark] stale event dropped: message_id=%s age=%ds", message_id, int((_t.time() * 1000 - _create_ms) / 1000))
        return

    # 发消息者 open_id（飞书按 open_id 认主人）。lark-cli 展平后字段名是 sender_id
    # （对应飞书原始 event.sender.sender_id.open_id）。
    # ⚠️ 不用 open_id 兜底——open_id 在不同事件类型中含义不同（可能是 reader/operator/bot），
    # 误取会导致 is_owner 判定出错，造成非主人拿到主人权限（安全漏洞）。
    sender_open_id = (
        event_data.get("sender_open_id")
        or event_data.get("sender_id")
        or ""
    )
    if not sender_open_id:
        logger.warning(
            "[Lark] sender_open_id is empty! event keys=%s chat_id=%s msg_id=%s — treating as non-owner",
            list(event_data.keys()), chat_id, event_data.get("message_id", ""),
        )

    if not chat_id:
        return

    # lark-cli 新格式：所有 chat_id 统一用 oc_ 前缀，P2P / 群聊靠 chat_type 区分。
    # 旧格式：P2P chat_id 以 p2p_ 开头，但新版 lark-cli 已不再使用该前缀。
    is_group_chat = event_data.get("chat_type", "") == "group"

    # 群聊消息写入本地缓存（不论是否回复，供背景上下文使用）
    if is_group_chat:
        from datetime import datetime as _dt
        _time_str = _dt.fromtimestamp(int(_create_ms) / 1000).strftime("%Y-%m-%d %H:%M") if _create_ms else ""
        _cache_group_message(chat_id, sender_open_id, text, _time_str)

    # 主人判定：config.lark.owner_open_id 为空 = 还没认主人。
    from ethan.core.config import get_config as _gc
    _lark_cfg = getattr(_gc(), "lark", None)
    owner_open_id = getattr(_lark_cfg, "owner_open_id", "") if _lark_cfg else ""
    is_owner = bool(owner_open_id) and bool(sender_open_id) and sender_open_id == owner_open_id
    owner_claimed = bool(owner_open_id)
    logger.debug(
        "[Lark] identity: sender=%s owner=%s is_owner=%s chat=%s",
        sender_open_id[:12] if sender_open_id else "(empty)",
        owner_open_id[:12] if owner_open_id else "(empty)",
        is_owner, chat_id,
    )

    # 群聊响应过滤：按 group_response_mode 决定是否处理（私聊不过滤）
    if is_group_chat and _lark_cfg:
        if not await _should_respond_to_group_message(text, _lark_cfg, event_data):
            logger.debug(
                "[Lark] group message skipped by mode=%s msg=%s",
                getattr(_lark_cfg, "group_response_mode", "mention_only"), message_id,
            )
            return

    # ── 群聊剥离 @mention：兼容 "@agent /new" 和 "/new @agent" 两种写法 ──
    # 用 lark-cli 事件中的 mentions 结构化数据移除所有 @文本；兜底用通用正则。
    if is_group_chat:
        import re as _re
        _stripped = False
        # 方式1：从 mentions 结构中提取每个被 @ 的 name，移除对应 @文本
        _mentions = event_data.get("mentions") or []
        if _mentions:
            for m in _mentions:
                _m_name = m.get("name", "") or m.get("key", "") or ""
                if _m_name:
                    text = _re.sub(rf"@{_re.escape(_m_name)}\s*", "", text, flags=_re.IGNORECASE).strip()
                    _stripped = True
        # 方式2：兜底用配置的 bot_name
        if not _stripped and _lark_cfg:
            _bot_name = getattr(_lark_cfg, "bot_name", "") or ""
            if _bot_name:
                text = _re.sub(rf"@{_re.escape(_bot_name)}\s*", "", text, flags=_re.IGNORECASE).strip()
                _stripped = True
        # 方式3：再兜底——只去开头的 @word（避免误删正文中的邮箱、装饰器等 @ 文本）
        if not _stripped and "@" in text:
            text = _re.sub(r"^@\S+\s*", "", text).strip()

    # ── /btw：顺带一问——不带历史、不带 cold facts 的单轮轻量查询 ──
    # 解析放在 /command 之前，因为 /btw 需要走完整 agent 流程（只是上下文为空）。
    from ethan.interface.channel_commands import (
        btw_question,
        handle_command,
        is_btw,
        is_command,
        is_review,
        resolve_custom_command,
        review_target,
    )
    btw_mode = False

    # ── debounce bypass：命令路径不参与合并 ──
    # /stop 命令 + 自然语言中止关键词 → cancel（用户主动停止，丢弃队列内容）
    # 其他命令路径 → flush（先把队列里待合并的消息合并触发一次 agent，再执行命令）
    # 必须在命令分流之前处理，否则命令立即 return，队列里的消息永远不会被 flush。
    _text_lower = text.strip().lower()
    _is_stop_cmd = _text_lower == "/stop" or _text_lower.startswith("/stop ")
    _is_stop_intent = _is_stop_cmd or _text_lower in _ABORT_KEYWORDS
    # 自定义命令展开（缓存结果，避免后面再调一次）
    _expanded_cmd = resolve_custom_command(text)
    _is_cmd_path = (
        _text_lower in ("/test-card", "/test-card ")
        or is_btw(text) or is_review(text) or is_command(text)
        or _expanded_cmd is not None
    )
    if _is_stop_intent:
        await _cancel_debounce_for_sender(chat_id, sender_open_id)
    elif _is_cmd_path:
        await _flush_debounce_for_sender(chat_id, sender_open_id)

    # ── /test-card：发一张带按钮的测试卡片，用于验证 card.action.trigger 事件链路 ──
    # 点按钮后飞书回调 card.action.trigger，_handle_card_action 会回一张绿色确认卡。
    # 调试用：链路打通后可删。
    if _text_lower in ("/test-card", "/test-card "):
        card = {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "card.action.trigger 测试"},
                "template": "blue",
            },
            "body": {
                "elements": [
                    {
                        "tag": "markdown",
                        "content": (
                            "点击下面的按钮，验证飞书卡片回调事件是否打通。\n"
                            "点击后应自动收到一张绿色确认卡。"
                        ),
                    },
                    {
                        "tag": "action",
                        "actions": [
                            {
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "🔘 点我测试"},
                                "type": "primary",
                                "value": {"cmd": "test"},
                            }
                        ],
                    }
                ]
            },
        }
        msg_id = await _send_interactive_card(chat_id, card)
        if msg_id:
            logger.info("[Lark] sent test card to chat=%s msg=%s", chat_id, msg_id)
        else:
            logger.warning("[Lark] failed to send test card to chat=%s", chat_id)
        return
    if is_btw(text):
        q = btw_question(text)
        if not q:
            await _send_reply(chat_id, "用法：/btw <问题>，例如：/btw 今天几号？")
            return
        btw_mode = True
        text = q

    # ── /review：不带历史、强制触发 code-review 技能 ──
    # 把文本改写成含 trigger 关键词的形式，让 skill matcher 自然命中 code-review 技能。
    # 行为同 /btw：清空历史上下文，不拉群消息背景。
    elif is_review(text):
        target = review_target(text)
        if not target:
            await _send_reply(chat_id, "用法：/review <PR/MR 链接>，例如：/review https://github.com/foo/bar/pull/123")
            return
        btw_mode = True  # 复用 btw_mode：不带历史、不拉群消息
        text = f"帮我 code review 这个 PR/MR：{target}"

    # ── 自定义命令：展开后交 agent 处理（保留历史上下文）──
    elif _expanded_cmd is not None:
        text = _expanded_cmd

    # ── /command：以 / 开头的命令先于 Agent 处理（不加思考表情，直接回复）──
    if is_command(text):
        from ethan.interface.lark_cmd_context import build_cmd_context
        cmd_ctx = build_cmd_context(chat_id, text, sender_open_id, is_group_chat=is_group_chat)
        reply = await handle_command(cmd_ctx)
        if reply:
            await _send_reply(chat_id, reply)
        return

    # ── 自然语言中止快速路径 ──
    # 用户在飞书里直接发"停"/"不用了"/"取消"等词（非 /stop 命令）时，若当前有正在跑的
    # Agent 任务则中止之，并直接回复，不进 Agent 流程；若无任务在跑则不拦截，继续走正常
    # Agent 流程（避免误把空 chat 的一句"停"当命令丢弃）。关键词用精确匹配防误伤。
    if _text_lower in _ABORT_KEYWORDS:
        if await _stop_lark_task(chat_id):
            await _send_reply(chat_id, "🛑 已停止当前回复。")
            return

    # ── 普通消息：进 debounce 队列 ──
    # 同一 (chat_id, sender) 在 1-5s 窗口内连发的消息合并成一次 Agent 调用，避免连发 N 条
    # 触发 N 次 Agent。策略：第 1 条等 1s 触发，每来一条重置为 1s（"延长 1s"语义），
    # 总等待不超过 5s。命令路径已在上方 bypass 处理（flush 或 cancel），不会进到这里。
    #
    # 第 1 条立即加 THINKING 表情给反馈；后续追加消息不再加表情（复用第 1 条的 ts）。
    # flush 时用第 1 条的 event_data/message_id/identity，文本按顺序拼成 \n 分隔。
    existing_q = _get_debounce_queue(chat_id, sender_open_id)
    if existing_q is not None:
        # 已有队列：追加文本，重置定时器
        _append_debounce_queue(chat_id, sender_open_id, text=text, message_id=message_id)
        _schedule_debounce_flush(existing_q, chat_id, sender_open_id)
        logger.debug(
            "[Lark] buffered msg chat=%s sender=%s queue_size=%d",
            chat_id, sender_open_id[:12] if sender_open_id else "(empty)", len(existing_q["texts"]),
        )
        return

    # 第 1 条：加表情，入队，起 1s 定时器
    ts = TypingState(message_id)
    await ts.__aenter__()

    q = _init_debounce_queue(
        chat_id, sender_open_id,
        event_data=event_data,
        text=text,
        message_id=message_id,
        owner_open_id=owner_open_id,
        is_owner=is_owner,
        owner_claimed=owner_claimed,
        btw_mode=btw_mode,
        ts=ts,
    )
    _schedule_debounce_flush(q, chat_id, sender_open_id)


async def _dispatch(event_key: str, event_data: dict) -> None:
    """按 event_key 路由到对应 handler。

    lark-cli event consume 输出的是扁平结构（见 _handle_message 注释），event_data 顶层即可取字段。
    未知 key 走 debug 跳过，不报错——避免新事件类型上线时旧版本直接崩。
    """
    if event_key == "im.message.receive_v1":
        # 收消息：复用既有完整流程（去重/命令/Agent 流式回复）。fire-and-forget 起 task，
        # 与原 lark_events 的 asyncio.create_task(_handle_message(event)) 行为一致。
        asyncio.create_task(_handle_message(event_data))
    elif event_key == "im.message.message_read_v1":
        await _handle_message_read(event_data)
    elif event_key == "im.message.reaction.created_v1":
        await _handle_reaction(event_data)
    elif event_key == "card.action.trigger":
        await _handle_card_action(event_data)
    else:
        logger.debug("[Lark] unknown event_key=%s skipped", event_key)


