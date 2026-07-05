"""飞书鉴权检测 + 授权引导卡片。"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# 授权引导卡片节流：同一 chat_id 5 分钟内只发一次
_AUTH_CARD_THROTTLE_SECONDS = 300
_auth_card_sent: dict[str, float] = {}  # chat_id -> last_sent_timestamp


def _is_lark_auth_error(err_text: str, out_text: str, exit_code: int) -> bool:
    """判断 lark-cli 输出是否为鉴权类错误（需发授权引导卡片）。

    匹配场景：
    1. stderr 含 "Error: need_user_authorization"（用户未登录）
    2. stdout JSON 含 error.type == "auth_error"
    3. stdout JSON 含 error.code 为 99991663/99991661 等鉴权码
    4. stdout JSON 含 error.message 含 "User token has expired" / "Token does not exist"

    不触发场景：
    - 网络/参数错误（api_error / validation_error）
    - not found
    - JSON parse 错误
    """
    # 场景 1：用户未登录（stderr 直接报错）
    if "need_user_authorization" in err_text or "No user logged in" in err_text:
        return True

    # 场景 2-4：解析 stdout JSON
    if not out_text:
        return False
    try:
        data = json.loads(out_text)
        if data.get("ok"):
            return False  # 成功响应，不是错误
        err = data.get("error") or {}
        # 场景 2：error.type
        if err.get("type") == "auth_error":
            return True
        # 场景 3：error.code（99991663 user auth missing, 99991661 token invalid）
        code = err.get("code")
        if isinstance(code, int) and code in (99991663, 99991661):
            return True
        # 场景 4：error.message
        msg = err.get("message", "") or ""
        if "User token has expired" in msg or "Token does not exist" in msg:
            return True
        return False
    except (json.JSONDecodeError, TypeError):
        return False


async def _send_auth_guidance_card(chat_id: str) -> bool:
    """发送授权引导卡片。同一 chat_id 5 分钟内只发一次，返回是否真的发了。"""
    import time as _time

    now = _time.time()
    last_sent = _auth_card_sent.get(chat_id, 0)
    if now - last_sent < _AUTH_CARD_THROTTLE_SECONDS:
        logger.debug("[Lark] auth guidance card throttled for chat_id=%s", chat_id)
        return False

    card = {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "需要飞书用户授权"},
            "template": "red",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        "当前操作需要用户身份授权，但检测到用户未登录或授权已过期。\n\n"
                        "**解决方法：** 在终端执行以下命令完成授权：\n"
                        "```\nlark-cli auth login --domain im\n```\n"
                        "按提示在浏览器中完成授权后，重新尝试即可。"
                    ),
                }
            ]
        },
    }
    # lazy import 避免循环依赖lark_send 依赖 lark_auth，lark_auth 不能顶层导入 lark_send）
    from ethan.interface.lark_send import _send_interactive_card
    msg_id = await _send_interactive_card(chat_id, card)
    if msg_id:
        _auth_card_sent[chat_id] = now
        logger.info("[Lark] sent auth guidance card to chat_id=%s", chat_id)
        return True
    return False
