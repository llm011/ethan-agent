"""WeChat iLink Bot API — protocol client.

Implements the five iLink endpoints needed to operate a personal-WeChat bot:
  get_bot_qrcode / get_qrcode_status / getupdates / sendmessage / sendtyping

Based on the MIT-licensed openclaw-weixin plugin:
  https://github.com/Tencent/openclaw-weixin  (MIT License, Copyright Tencent 2026)

Reference implementation:
  https://github.com/co-pine/wx-robot-ilink

No OpenClaw gateway needed — this module talks to the Tencent iLink cloud
(https://ilinkai.weixin.qq.com) directly.
"""
from __future__ import annotations

import base64
import json
import logging
import random
import struct
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_ILINK_LOGIN_BASE = "https://ilinkai.weixin.qq.com"
_APP_ID = "bot"
# Version 2.0.0 encoded as (major<<16 | minor<<8 | patch) = 131072
_CLIENT_VERSION = str(2 << 16 | 0 << 8 | 0)
_QR_REFRESH_LIMIT = 3
_LONGPOLL_TIMEOUT_S = 40  # slightly longer than server's 35s

_CREDS_PATH = Path.home() / ".ethan" / "memory" / "wechat_credentials.json"


# ── Credentials ───────────────────────────────────────────────────────────────

@dataclass
class WeChatCredentials:
    bot_token: str
    base_url: str      # IDC-routed base, e.g. "https://ilinkai.weixin.qq.com"
    ilink_bot_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WeChatCredentials":
        return cls(**{k: d[k] for k in ("bot_token", "base_url", "ilink_bot_id") if k in d})


def load_credentials() -> WeChatCredentials | None:
    if not _CREDS_PATH.exists():
        return None
    try:
        return WeChatCredentials.from_dict(json.loads(_CREDS_PATH.read_text()))
    except Exception:
        return None


def save_credentials(creds: WeChatCredentials) -> None:
    _CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CREDS_PATH.write_text(json.dumps(creds.to_dict(), ensure_ascii=False))
    _CREDS_PATH.chmod(0o600)


def clear_credentials() -> None:
    _CREDS_PATH.unlink(missing_ok=True)


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _random_wechat_uin() -> str:
    """Random uint32 → decimal string → base64, fresh per request."""
    val = random.randint(0, 0xFFFFFFFF)
    return base64.b64encode(str(val).encode()).decode()


def _build_headers(token: str = "") -> dict[str, str]:
    h: dict[str, str] = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "iLink-App-Id": _APP_ID,
        "iLink-App-ClientVersion": _CLIENT_VERSION,
        "X-WECHAT-UIN": _random_wechat_uin(),
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _base_info() -> dict:
    return {"channel_version": _CLIENT_VERSION, "bot_agent": "ethan-agent/1.0"}


# ── QR Login ──────────────────────────────────────────────────────────────────

async def _save_qr_image(data_or_url: str) -> Path:
    """Save QR code to ~/.ethan/wechat_qr.png; data may be base64 or a URL."""
    qr_path = Path.home() / ".ethan" / "wechat_qr.png"
    qr_path.parent.mkdir(parents=True, exist_ok=True)

    # Try to decode as raw base64 first
    try:
        img = base64.b64decode(data_or_url)
        qr_path.write_bytes(img)
        return qr_path
    except Exception:
        pass

    # Might be a URL — download it
    if data_or_url.startswith("http"):
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(data_or_url)
            r.raise_for_status()
            qr_path.write_bytes(r.content)
        return qr_path

    # Fallback: write as-is
    qr_path.write_text(data_or_url)
    return qr_path


async def login_via_qrcode() -> WeChatCredentials:
    """Interactive QR-code login flow.

    Displays a QR code for the user to scan with WeChat, then polls until
    the login is confirmed. Returns credentials on success.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(_QR_REFRESH_LIMIT):
            # 1. Request QR code
            r = await client.post(
                f"{_ILINK_LOGIN_BASE}/ilink/bot/get_bot_qrcode",
                params={"bot_type": "3"},
                headers=_build_headers(),
                json={"base_info": _base_info()},
            )
            r.raise_for_status()
            body = r.json()
            logger.debug("[WeChat] get_bot_qrcode response: %s", body)

            ret = body.get("ret", -1)
            if ret != 0:
                raise RuntimeError(f"get_bot_qrcode failed: ret={ret} body={body}")

            qrcode_key = body.get("qrcode") or body.get("qrcode_key") or ""
            # 实际字段名是 qrcode_img_content（URL 形式）
            qr_url = (
                body.get("qrcode_img_content")
                or body.get("qrcode_image")
                or body.get("qrcode_img")
                or ""
            )

            if qr_url:
                print(f"\n[WeChat] 请用微信扫以下二维码登录:\n  {qr_url}\n")
                # 用系统浏览器打开二维码页面（页面内含二维码，可直接扫）
                try:
                    import subprocess, sys
                    if sys.platform == "darwin":
                        subprocess.Popen(["open", qr_url])
                    elif sys.platform == "linux":
                        subprocess.Popen(["xdg-open", qr_url])
                    print("[WeChat] 已在浏览器打开二维码页面，请用微信扫码...")
                except Exception:
                    print("[WeChat] 请手动在浏览器打开上方链接后扫码")
            elif qrcode_key:
                print(f"\n[WeChat] 二维码 key={qrcode_key}（未收到图片 URL，请联系开发者）")
            else:
                logger.warning("[WeChat] 未收到二维码，原始响应: %s", body)

            # 2. Poll for scan status
            poll_url = f"{_ILINK_LOGIN_BASE}/ilink/bot/get_qrcode_status"
            poll_params = {"qrcode": qrcode_key}
            confirmed = False
            while True:
                await __import__("asyncio").sleep(2)
                pr = await client.get(
                    poll_url,
                    params=poll_params,
                    headers=_build_headers(),
                )
                pr.raise_for_status()
                ps = pr.json()
                logger.debug("[WeChat] qrcode_status: %s", ps)

                status = ps.get("status") or ps.get("qrcode_status") or ""

                if status == "wait":
                    continue

                if status == "scaned":
                    print("[WeChat] 已扫码，请在手机上确认...")
                    continue

                if status in ("scaned_but_redirect", "redirect"):
                    # Switch polling host
                    new_base = ps.get("baseurl") or ps.get("redirect_url") or ""
                    if new_base:
                        poll_url = f"{new_base.rstrip('/')}/ilink/bot/get_qrcode_status"
                    continue

                if status == "expired":
                    print(f"[WeChat] 二维码已过期，刷新中 ({attempt + 1}/{_QR_REFRESH_LIMIT})...")
                    break  # outer loop will re-request QR

                if status in ("confirmed", "binded", "binded_redirect", "success"):
                    token = ps.get("bot_token") or ps.get("token") or ""
                    bot_id = ps.get("ilink_bot_id") or ps.get("bot_id") or ""
                    base_url = (ps.get("baseurl") or ps.get("base_url") or _ILINK_LOGIN_BASE).rstrip("/")
                    if not token:
                        raise RuntimeError(f"Login succeeded but no token in response: {ps}")
                    creds = WeChatCredentials(bot_token=token, base_url=base_url, ilink_bot_id=bot_id)
                    save_credentials(creds)
                    print("[WeChat] 登录成功！")
                    confirmed = True
                    return creds

                if status == "need_verifycode":
                    code = input("[WeChat] 请输入手机上显示的验证码: ").strip()
                    poll_params["verifycode"] = code
                    continue

                logger.warning("[WeChat] 未知 qrcode status: %s", status)

            if not confirmed and attempt == _QR_REFRESH_LIMIT - 1:
                raise RuntimeError("WeChat QR code expired too many times — login failed")

    raise RuntimeError("WeChat login failed after all retries")


# ── Long-poll (getUpdates) ────────────────────────────────────────────────────

async def get_updates(
    client: httpx.AsyncClient,
    creds: WeChatCredentials,
    buf: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """Long-poll for new messages. Returns (msgs, new_buf).

    An empty list is normal on timeout — just call again with the returned buf.
    Raises on hard errors so the caller can decide to re-login.
    """
    try:
        r = await client.post(
            f"{creds.base_url}/ilink/bot/getupdates",
            headers=_build_headers(creds.bot_token),
            json={"get_updates_buf": buf, "base_info": _base_info()},
            timeout=_LONGPOLL_TIMEOUT_S,
        )
        r.raise_for_status()
        body = r.json()
    except httpx.ReadTimeout:
        return [], buf
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            raise PermissionError("iLink token expired or invalid") from e
        raise

    ret = body.get("ret", -1)
    if ret != 0:
        logger.warning("[WeChat] getupdates ret=%s body=%s", ret, body)
        if ret in (100, 401, 403):
            raise PermissionError(f"iLink auth error: ret={ret}")
        return [], buf

    msgs = body.get("msgs") or body.get("messages") or []
    new_buf = body.get("get_updates_buf", buf)
    return msgs, new_buf


# ── Send message ──────────────────────────────────────────────────────────────

async def send_text(
    client: httpx.AsyncClient,
    creds: WeChatCredentials,
    context_token: str,
    text: str,
) -> None:
    """Send a plain-text reply using the context_token from the received message."""
    r = await client.post(
        f"{creds.base_url}/ilink/bot/sendmessage",
        headers=_build_headers(creds.bot_token),
        json={
            "context_token": context_token,
            "msg_type": "text",
            "content": text,
            "base_info": _base_info(),
        },
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("ret", -1) != 0:
        logger.warning("[WeChat] sendmessage failed: %s", body)


async def send_typing(
    client: httpx.AsyncClient,
    creds: WeChatCredentials,
    context_token: str,
    typing: bool = True,
) -> None:
    """Send or cancel the 'typing...' indicator."""
    try:
        r = await client.post(
            f"{creds.base_url}/ilink/bot/sendtyping",
            headers=_build_headers(creds.bot_token),
            json={
                "context_token": context_token,
                "typing": 1 if typing else 0,
                "base_info": _base_info(),
            },
            timeout=5,
        )
        r.raise_for_status()
    except Exception:
        pass  # typing indicator is best-effort
