"""飞书消息收发 IO：client 构建 + 发送/编辑/删除/回复 + 通知/图片 + 消息详情拉取。

依赖 lark_render 做 content 渲染。所有网络调用经 lark_oapi 或 lark-cli 子进程。
"""
from __future__ import annotations

import asyncio
import json
import logging

from ethan.interface.lark_render import (
    _markdown_to_post_elements,
    _render_card_content,
    _render_post_content,
)

logger = logging.getLogger(__name__)


async def _send_reaction(message_id: str) -> str | None:
    """给消息添加 THINKING 表情，返回 reaction_id 以便后续删除。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "im", "reactions", "create",
            "--as", "bot",
            "--params", json.dumps({"message_id": message_id}),
            "--data", json.dumps({"reaction_type": {"emoji_type": "THINKING"}}),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        data = json.loads(stdout.decode(errors="replace"))
        return data.get("data", {}).get("reaction_id")
    except Exception:
        logger.debug("Failed to add reaction to %s", message_id, exc_info=True)
        return None


async def _remove_reaction(message_id: str, reaction_id: str) -> None:
    """删除之前添加的 THINKING 表情。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "im", "reactions", "delete",
            "--as", "bot",
            "--params", json.dumps({"message_id": message_id, "reaction_id": reaction_id}),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=5)
    except Exception:
        pass


async def send_lark_notification(chat_id: str, text: str) -> bool:
    """向指定 chat_id 发一条 post 气泡通知（markdown 转 post elements）。

    适合定时任务结果、心跳通知等不需要流式编辑的场景。
    用 post 而不是卡片，外观是普通气泡，支持加粗/斜体/代码/链接格式。
    """
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
    import json as _json
    from ethan.core.config import get_config

    cfg = get_config()
    lark_cfg = getattr(cfg, "lark", None)
    if not lark_cfg or not lark_cfg.app_id:
        return False
    client = (
        lark.Client.builder()
        .app_id(lark_cfg.app_id)
        .app_secret(lark_cfg.app_secret)
        .build()
    )
    content = _json.dumps({
        "zh_cn": {"title": "", "content": _markdown_to_post_elements(text)}
    }, ensure_ascii=False)
    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("post")
            .content(content)
            .build()
        )
        .build()
    )
    try:
        resp = await asyncio.to_thread(client.im.v1.message.create, req)
        if not resp.success():
            logger.warning("Lark notification failed: code=%s msg=%s", resp.code, resp.msg)
        return resp.success()
    except Exception:
        logger.exception("Failed to send Lark notification to %s", chat_id)
        return False


async def send_lark_image(chat_id: str, image_path: str, caption: str = "") -> bool:
    """向指定 chat_id 发一张图片（可选附文字说明）。

    流程：先 upload 图片拿 image_key，再发 image 消息。
    如果有 caption，额外发一条 post 气泡跟在图片后面。
    适合定时任务发图表/截图等场景。
    """
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest, CreateMessageRequestBody,
        CreateImageRequest, CreateImageRequestBody,
    )
    import json as _json, os as _os
    from ethan.core.config import get_config

    cfg = get_config()
    lark_cfg = getattr(cfg, "lark", None)
    if not lark_cfg or not lark_cfg.app_id:
        return False
    client = (
        lark.Client.builder()
        .app_id(lark_cfg.app_id)
        .app_secret(lark_cfg.app_secret)
        .build()
    )

    path = _os.path.expanduser(image_path)
    if not _os.path.isfile(path):
        logger.warning("send_lark_image: file not found: %s", path)
        return False

    try:
        with open(path, "rb") as f:
            upload_req = (
                CreateImageRequest.builder()
                .request_body(
                    CreateImageRequestBody.builder()
                    .image_type("message")
                    .image(f)
                    .build()
                )
                .build()
            )
            upload_resp = await asyncio.to_thread(client.im.v1.image.create, upload_req)
        if not upload_resp.success() or not upload_resp.data:
            logger.warning("Lark image upload failed: %s %s", upload_resp.code, upload_resp.msg)
            return False
        image_key = upload_resp.data.image_key

        send_req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("image")
                .content(_json.dumps({"image_key": image_key}))
                .build()
            )
            .build()
        )
        send_resp = await asyncio.to_thread(client.im.v1.message.create, send_req)
        if not send_resp.success():
            logger.warning("Lark image send failed: %s %s", send_resp.code, send_resp.msg)
            return False

        if caption:
            await send_lark_notification(chat_id, caption)
        return True
    except Exception:
        logger.exception("send_lark_image failed for %s", chat_id)
        return False


def _lark_client():
    """构建 lark_oapi client，未配置返回 None。"""
    import lark_oapi as lark
    from ethan.core.config import get_config
    lark_cfg = getattr(get_config(), "lark", None)
    if not lark_cfg or not lark_cfg.app_id:
        return None
    return (
        lark.Client.builder()
        .app_id(lark_cfg.app_id)
        .app_secret(lark_cfg.app_secret)
        .build()
    )


async def _send_message(chat_id: str, text: str, use_card: bool, reply_to_msg_id: str = "") -> tuple[str | None, str]:
    """发一条消息（卡片或 post），返回 (message_id, msg_type)。msg_type 为 'interactive' 或 'post'。

    use_card=True 发卡片（markdown 渲染，适合复杂回复）；False 发 post（纯文本，适合简短回复）。
    两种类型都支持后续流式编辑（卡片用 patch，post 用 update）。
    reply_to_msg_id 非空时用 message.reply 锚定到用户那条消息（飞书显示成"引用回复"），否则普通 create。
    """
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest, CreateMessageRequestBody,
        ReplyMessageRequest, ReplyMessageRequestBody,
    )
    client = _lark_client()
    if client is None:
        return None, ""
    msg_type = "interactive" if use_card else "post"
    content = _render_card_content(text) if use_card else _render_post_content(text)
    try:
        if reply_to_msg_id:
            req = (
                ReplyMessageRequest.builder()
                .message_id(reply_to_msg_id)
                .request_body(
                    ReplyMessageRequestBody.builder()
                    .msg_type(msg_type).content(content).build()
                )
                .build()
            )
            resp = await asyncio.to_thread(client.im.v1.message.reply, req)
        else:
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type(msg_type)
                    .content(content)
                    .build()
                )
                .build()
            )
            resp = await asyncio.to_thread(client.im.v1.message.create, req)
        if resp.success() and resp.data:
            return resp.data.message_id, msg_type
        logger.warning("Lark send(%s) failed: code=%s msg=%s", msg_type, resp.code, resp.msg)
        return None, msg_type
    except Exception:
        logger.exception("Failed to send %s message to chat %s", msg_type, chat_id)
        return None, msg_type


async def _send_interactive_card(chat_id: str, card: dict, reply_to_msg_id: str = "") -> str | None:
    """发一条预构建的 interactive 卡片（card 已是飞书卡片 dict，整体 json.dumps 作 content）。

    用于 ui_card 工具产出的 lark_card：与流式答案卡片不同，这是一次性发出的完整卡片，
    不做后续编辑。reply_to_msg_id 非空时锚定到用户那条消息。失败返回 None。
    """
    import json as _json
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest, CreateMessageRequestBody,
        ReplyMessageRequest, ReplyMessageRequestBody,
    )
    client = _lark_client()
    if client is None:
        return None
    content = _json.dumps(card, ensure_ascii=False)
    try:
        if reply_to_msg_id:
            req = (
                ReplyMessageRequest.builder()
                .message_id(reply_to_msg_id)
                .request_body(
                    ReplyMessageRequestBody.builder()
                    .msg_type("interactive").content(content).build()
                )
                .build()
            )
            resp = await asyncio.to_thread(client.im.v1.message.reply, req)
        else:
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id).msg_type("interactive").content(content).build()
                )
                .build()
            )
            resp = await asyncio.to_thread(client.im.v1.message.create, req)
        if resp.success() and resp.data:
            return resp.data.message_id
        logger.warning("Lark interactive card send failed: code=%s msg=%s", resp.code, resp.msg)
        return None
    except Exception:
        logger.exception("Failed to send interactive card to chat %s", chat_id)
        return None


async def _edit_message(message_id: str, text: str, use_card: bool) -> bool:
    """更新已发送消息的内容（流式追加效果）。

    卡片用 message.patch（更新卡片 API）；post 用 message.update（更新消息内容 API，需带 msg_type）。
    两者整体替换 content。失败返回 False（调用方决定是否重试/兜底）。
    """
    from lark_oapi.api.im.v1 import (
        PatchMessageRequest, PatchMessageRequestBody,
        UpdateMessageRequest, UpdateMessageRequestBody,
    )
    client = _lark_client()
    if client is None:
        return False

    try:
        if use_card:
            req = (
                PatchMessageRequest.builder()
                .message_id(message_id)
                .request_body(PatchMessageRequestBody.builder().content(_render_card_content(text)).build())
                .build()
            )
            resp = await asyncio.to_thread(client.im.v1.message.patch, req)
        else:
            req = (
                UpdateMessageRequest.builder()
                .message_id(message_id)
                .request_body(
                    UpdateMessageRequestBody.builder()
                    .msg_type("post")
                    .content(_render_post_content(text))
                    .build()
                )
                .build()
            )
            resp = await asyncio.to_thread(client.im.v1.message.update, req)
        if not resp.success():
            logger.debug("Lark edit(%s) failed: code=%s msg=%s", "card" if use_card else "post", resp.code, resp.msg)
        return resp.success()
    except Exception:
        logger.exception("Lark edit failed")
        return False


async def _delete_message(message_id: str) -> bool:
    """撤回/删除已发送消息。用于误发的卡片（如把 reasoning 误当答案发出后清理）。"""
    from lark_oapi.api.im.v1 import DeleteMessageRequest
    client = _lark_client()
    if client is None or not message_id:
        return False
    try:
        req = DeleteMessageRequest.builder().message_id(message_id).build()
        resp = await asyncio.to_thread(client.im.v1.message.delete, req)
        if not resp.success():
            logger.debug("Lark delete failed: code=%s msg=%s", resp.code, resp.msg)
        return resp.success()
    except Exception:
        logger.exception("Lark delete failed")
        return False


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
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        data = json.loads(stdout.decode(errors="replace"))
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
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        data = json.loads(stdout.decode(errors="replace"))
        if not data.get("ok") and data.get("code") not in (0, None):
            return None
        d = data.get("data", {}) or {}
        items = d.get("items") or (d.get("data", {}) or {}).get("items") or []
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


async def _resolve_quoted_text(message_id: str) -> str:
    """用户引用了某条消息时，返回被引用消息的文本。

    lark-cli 压平的事件里没有 parent_id，需先 mget 当前消息详情，
    从中找被引用消息 id（parent_id / upper_message_id / root_id），再 mget 那条取文本。
    任何环节失败返回空串，不阻断主流程。
    """
    detail = await _fetch_message_detail(message_id)
    if not detail:
        return ""
    parent_id = (
        detail.get("parent_id")
        or detail.get("upper_message_id")
        or detail.get("root_id")
        or ""
    )
    if not parent_id or parent_id == message_id:
        return ""
    parent = await _fetch_message_detail(parent_id)
    if not parent:
        return ""
    return _extract_msg_text(parent)[:1000]
