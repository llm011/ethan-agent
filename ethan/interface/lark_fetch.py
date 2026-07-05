"""飞书 CLI 子进程操作：消息发送/拉取/文本提取/引用解析/群聊历史。"""
from __future__ import annotations

import asyncio
import json
import logging

from ethan.interface.lark_auth import _is_lark_auth_error, _send_auth_guidance_card

logger = logging.getLogger(__name__)


async def _send_reply(chat_id: str, text: str) -> str | None:
    """通过 lark-cli 回复消息，使用 --markdown 以正确渲染格式。
    返回发出的消息 message_id（从 JSON stdout 解析），失败时返回 None。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "im", "+messages-send",
            "--chat-id", chat_id,
            "--markdown", text,
            "--as", "bot",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        out_text = stdout.decode(errors="replace")
        err_text = stderr.decode(errors="replace")
        # 鉴权失败 → 发授权引导卡片（节流）
        if _is_lark_auth_error(err_text, out_text, proc.returncode or 0):
            logger.warning("[Lark] _send_reply auth error, sending guidance card to chat %s", chat_id)
            await _send_auth_guidance_card(chat_id)
        data = json.loads(out_text)
        return data.get("data", {}).get("message_id")
    except Exception:
        logger.exception("Failed to send Lark reply to chat %s", chat_id)
        return None


async def _fetch_message_detail(message_id: str) -> dict | None:
    """用 messages-mget 拉单条消息详情，返回 items[0]（dict）或 None。"""
    if not message_id:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "im", "+messages-mget",
            "--message-ids", message_id,
            "--as", "bot",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        out_text = stdout.decode(errors="replace")
        err_text = stderr.decode(errors="replace")
        # mget 用 bot 身份，不会触发 user 鉴权失败；但保留检测以备未来切到 user 身份
        if _is_lark_auth_error(err_text, out_text, proc.returncode or 0):
            logger.warning("[Lark] _fetch_message_detail auth error for msg %s", message_id)
        data = json.loads(out_text)
        if not data.get("ok") and data.get("code") not in (0, None):
            return None
        d = data.get("data", {}) or {}
        # 本版 lark-cli 返回 data.messages；旧结构用 items / data.items 兜底。
        items = d.get("messages") or d.get("items") or (d.get("data", {}) or {}).get("items") or []
        return items[0] if items else None
    except Exception:
        logger.debug("Failed to mget message %s", message_id, exc_info=True)
        return None


def _extract_msg_text(msg: dict) -> str:
    """从消息详情里抽出可读文本。text 消息的 body.content 是 {"text": "..."} 的 JSON 串。"""
    body = msg.get("body") or {}
    raw = body.get("content") if isinstance(body, dict) else None
    raw = raw or msg.get("content") or msg.get("text") or ""
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            obj = json.loads(raw)
            # text 类型 → {"text": "..."}；post 等富文本结构复杂，退化为原串
            if isinstance(obj, dict) and "text" in obj:
                return str(obj["text"]).strip()
        except Exception:
            pass
    return str(raw).strip()


async def _resolve_quoted_text(message_id: str) -> tuple[str, str]:
    """用户引用了某条消息时，返回 (被引用消息的可读文本, 被引用消息 id)。

    lark-cli 压平的事件里没有引用关系，需先 mget 当前消息详情，从中找被引用消息 id，
    再 mget 那条取文本。本版 lark-cli 用 reply_to 字段表示引用关系；
    parent_id / upper_message_id / root_id 作旧结构兜底。任何环节失败返回 ("", "")，不阻断主流程。
    """
    detail = await _fetch_message_detail(message_id)
    if not detail:
        return "", ""
    parent_id = (
        detail.get("reply_to")
        or detail.get("parent_id")
        or detail.get("upper_message_id")
        or detail.get("root_id")
        or ""
    )
    if not parent_id or parent_id == message_id:
        return "", ""
    parent = await _fetch_message_detail(parent_id)
    if not parent:
        return "", ""
    return _extract_msg_text(parent)[:1000], parent_id


async def _fetch_recent_chat_messages(chat_id: str, limit: int = 10) -> list[dict]:
    """拉取群聊最近 limit 条消息，返回 [{"sender": str, "text": str, "time": str}, ...]（按时间正序）。

    用于给 agent 注入群聊背景上下文，让它感知 @mention 之间群里发生的讨论。
    任何步骤失败返回空列表，不阻断主流程。

    权限说明：
    - Bot 身份只能读被 @ 的消息，看不到群里其他没 @ 的消息
    - 用户身份可读群内所有消息（需 im:message.group_msg:get_as_user 权限）
    - 这里用 lark-cli --as user 调用，能拿到完整群消息历史
    """
    try:
        # 用 lark-cli 子进程调用（用户身份），而不是 lark_oapi client（bot 身份）
        # 原因：bot 身份只能读被 @ 的消息，用户身份能读全部群消息
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "im", "+chat-messages-list",
            "--as", "user",  # 用户身份，能读全部群消息
            "--chat-id", chat_id,
            "--page-size", str(limit),
            "--order", "desc",
            "--no-reactions",  # 跳过 reactions 批量查询，背景上下文用不到
            "--format", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        out_text = stdout.decode(errors="replace")
        err_text = stderr.decode(errors="replace")
        # 用户身份调用最易触发鉴权失败（user token 缺失/过期）→ 发授权引导卡片
        if _is_lark_auth_error(err_text, out_text, proc.returncode or 0):
            logger.warning("[Lark] _fetch_recent_chat_messages auth error for chat_id=%s", chat_id)
            await _send_auth_guidance_card(chat_id)
            return []
        raw = json.loads(out_text)

        # lark-cli 返回结构：{"ok": ..., "identity": ..., "data": {"messages": [...]}}
        data = raw.get("data", raw) if isinstance(raw, dict) else {}
        messages = data.get("messages") if isinstance(data, dict) else None
        if not messages:
            return []

        results = []
        for msg in messages:
            if not msg or msg.get("deleted"):
                continue
            # 支持 text / post / image / file / audio / video 等类型
            # lark-cli 已预渲染 content 为可读文本（post → markdown，image → ![Image](img_xxx)）
            # interactive（卡片）跳过：通常是 bot 自己发的工具进度/答案卡片，作为背景噪音大且无意义
            msg_type = msg.get("msg_type", "text")
            if msg_type not in ("text", "post", "image", "file", "audio", "video"):
                continue

            try:
                # lark-cli +chat-messages-list 已渲染 content 为可读文本
                text = msg.get("content", "").strip()
                if not text:
                    continue

                # sender.name 在用户身份下有值；bot 发的消息 name 为空，用 sender_type 区分
                sender_info = msg.get("sender", {}) or {}
                sender_name = sender_info.get("name", "")
                if not sender_name:
                    # bot/应用发的消息没有用户名，标个 "bot" 让 agent 知道是机器人发的
                    sender_name = "bot" if sender_info.get("sender_type") == "app" else ""

                # lark-cli 返回 create_time 形如 "2026-07-03 13:32"（已格式化），直接用
                time_str = msg.get("create_time", "") or ""

                results.append({"sender": sender_name, "text": text, "time": time_str})
            except Exception:
                continue

        results.reverse()  # 时间正序
        return results
    except Exception:
        logger.exception("[Lark] _fetch_recent_chat_messages failed for chat_id=%s", chat_id)
        return []
