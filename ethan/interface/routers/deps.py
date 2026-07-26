"""共享依赖：鉴权、Agent 工厂。"""
from urllib.parse import unquote

from fastapi import HTTPException, Request

from ethan.core.context import set_user_id


def _resolve_user(token: str, request: Request) -> str | None:
    """token → user_id，命中后 set 进 ContextVar 并注入 request.state；失败返回 None。

    返回 Optional 而非直接抛 401，让 verify_token_or_cookie 能在 Bearer miss 后继续
    尝试 cookie / 签名通道（否则一个过期 Bearer 会短路掉后两个兜底）。
    """
    from ethan.core.users import get_user_store

    user_id = get_user_store().resolve_web_token(token)
    if user_id is None:
        return None
    set_user_id(user_id)  # 后续 ensure_user_dirs / path 函数依赖此 ContextVar
    request.state.user_id = user_id
    return user_id


async def verify_token(request: Request) -> str:
    """Bearer token 鉴权（用于内部管理 API），返回 user_id 并 set 进 ContextVar。

    解析顺序：
      1. config.users[].web_token / network.auth_token(default profile) → user_id
      2. 命中后 set_user_id，后续所有 path 函数自动读到正确 profile
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user_id = _resolve_user(auth.removeprefix("Bearer ").strip(), request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id


async def verify_token_or_cookie(request: Request) -> str:
    """三通道鉴权：Authorization header 优先，其次 cookie ethan_token，最后短期签名 URL。

    <img src> / <a href download> 这类浏览器直接发起的请求无法带 Authorization
    header：Web 同源部署从 cookie 读 token（前端 setAuthToken 已写 cookie，path=/）；
    跨源/Tauri webview cookie 带不上，用 ?user=&sig= 短期签名（前端先调
    POST /files/sign 换 path 级签名，详见 ethan.core.signed_url），不再把长效
    token 放进 URL（会留在访问日志/浏览器历史里）。
    其余流程与 verify_token 一致：解析 user_id、set_user_id、注入 request.state。
    """
    # 三通道依次尝试，任一命中即返回；前一通道 miss（如过期 Bearer）不短路后续，
    # 否则前端揣着轮换前的旧 token 会让 cookie/签名兜底永远轮不到 → 全 401。
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        user_id = _resolve_user(auth.removeprefix("Bearer ").strip(), request)
        if user_id is not None:
            return user_id

    # 前端写 cookie 时做了 encodeURIComponent，读回必须 unquote 才能与配置比对
    token = unquote(request.cookies.get("ethan_token", ""))
    if token:
        user_id = _resolve_user(token, request)
        if user_id is not None:
            return user_id

    # 签名通道：user + sig（"exp.sighex"）+ path（签名消息含 path，从 query 原样取）
    from ethan.core.signed_url import verify_path_sig

    user = request.query_params.get("user")
    sig = request.query_params.get("sig", "")
    path = request.query_params.get("path", "")
    # user="" 是 default profile（admin）的签名通道——不是提权：admin token 即 admin
    # 身份，拿到 admin token 的攻击者早就能直接 Bearer 进来。这里显式接受空串，
    # 避免 ?user= 被 query 解析成 None 而误拒 admin 签名（get_admin_user_id 返回 ""）。
    if user is not None and sig and path and verify_path_sig(user, path, sig):
        set_user_id(user)
        request.state.user_id = user
        return user
    raise HTTPException(status_code=401, detail="Unauthorized")


def create_agent(model: str | None = None, channel: str = "web", user_id: str = "", mode: str = ""):
    """Web 端 Agent 工厂，委托给 core.agent_factory。"""
    from ethan.core.agent_factory import create_agent as _create
    return _create(model=model, channel=channel, user_id=user_id, toolset="full", mode=mode)
