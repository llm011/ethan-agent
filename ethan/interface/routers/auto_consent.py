"""运行期切换超级权限（auto_consent）。

背景：super 权限原本只在发起 `/api/chat` 那一刻决定（请求体里的 `auto_consent`
字段），而 `run` 的 ConsentProvider 是那时创建并冻结的。用户很可能是在**生成
过程中**才想起要点开这个开关（比如发现 Agent 正在被一个个弹窗打断），此时
开关亮着却毫无效果——下一次工具调用仍会弹窗，体感就是「以开始时的状态为准」。

本路由让开关立即生效：改的是**正在跑的那个 run** 的 provider 实例属性，
agent loop 每次工具调用都会重新读它，所以下一条需要授权的工具就会用新策略。

安全约束与 `/api/chat` 完全一致：超级权限等于在用户主机上放开普通命令执行，
绝不能因为「token 泄露」就允许远程打开。因此仅接受本地回环 / RFC1918 来源，
其它来源一律 403 并保持关闭。

请求体：
    {"enabled": true, "session_id": "s_..."}

- `enabled=True`  开启：普通（非破坏性）授权自动放行
- `enabled=False` 关闭：恢复逐个弹窗确认（这是降权方向，任何来源都安全，
  但为保持语义一致仍统一走本地校验——远程客户端本就不该有开着的超级权限）

响应：
    {"ok": true, "enabled": true, "applied": true}

`applied=False` 表示当前 session 没有活跃 run（开关已记录，但下一次 chat
请求仍以请求体里的 `auto_consent` 为准）。
"""
from __future__ import annotations

import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .deps import verify_token

router = APIRouter()

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]


def _is_local(request: Request) -> bool:
    """与 `/api/chat` 的 `_is_local` 同一判定（不信任 X-Forwarded-For）。"""
    client = request.client
    if client is None:
        return False
    host = client.host
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or any(ip in net for net in _PRIVATE_NETWORKS)


class AutoConsentBody(BaseModel):
    enabled: bool
    session_id: str = ""


@router.post("/chat/auto-consent")
async def set_auto_consent(
    body: AutoConsentBody,
    request: Request,
    user_id: str = Depends(verify_token),
):
    if not _is_local(request):
        raise HTTPException(
            status_code=403,
            detail="auto_consent 仅允许来自本地网络的请求",
        )

    from ethan.core.consent import SuperConsentProvider, WebConsentProvider
    from ethan.core.run_manager import RunManager

    if not body.session_id:
        # 没有会话时没有可作用的 run —— 客户端的开关已存在本地，下一次
        # /api/chat 会带上 auto_consent，行为正确。这里直接回 not applied。
        return {"ok": True, "enabled": body.enabled, "applied": False, "reason": "no session_id"}

    run = RunManager.instance().get(body.session_id, user_id)
    if run is None or run.done:
        # 没有活跃 run：开关会由下一次 chat 请求的 auto_consent 字段生效。
        return {"ok": True, "enabled": body.enabled, "applied": False, "reason": "no active run"}

    consent = getattr(run, "consent", None)

    if body.enabled:
        # 当前 provider 若还不是 Super，就地升级（保留已注册的 pending Future，
        # 否则正在等待用户确认的那次弹窗会失去解析入口）。
        if consent is None or not getattr(consent, "auto_approve", False):
            if isinstance(consent, WebConsentProvider) and not isinstance(consent, SuperConsentProvider):
                consent.auto_approve = True
            elif consent is None:
                run.consent = SuperConsentProvider(session_id=body.session_id)
            else:
                # 非 Web 的 provider（REPL / 自动场景）：不支持运行期切换
                return {"ok": False, "enabled": False, "applied": False, "reason": "provider not switchable"}
    else:
        # 降权：普通 WebConsentProvider 没有 auto_approve 属性 → getattr 拿到 False，
        # agent loop 自然回到逐项弹窗。
        if consent is not None and isinstance(consent, WebConsentProvider):
            consent.auto_approve = False

    return {"ok": True, "enabled": body.enabled, "applied": True}
