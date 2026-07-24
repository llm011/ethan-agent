"""共享依赖：鉴权、Agent 工厂。"""
from urllib.parse import unquote

from fastapi import HTTPException, Request

from ethan.core.context import set_user_id


def _resolve_user(token: str, request: Request) -> str:
    """token → user_id，命中后 set 进 ContextVar 并注入 request.state。"""
    from ethan.core.users import get_user_store

    user_id = get_user_store().resolve_web_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
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
    return _resolve_user(auth.removeprefix("Bearer ").strip(), request)


async def verify_token_or_cookie(request: Request) -> str:
    """三通道鉴权：Authorization header 优先，其次 cookie ethan_token，最后短期签名 URL。

    <img src> / <a href download> 这类浏览器直接发起的请求无法带 Authorization
    header：Web 同源部署从 cookie 读 token（前端 setAuthToken 已写 cookie，path=/）；
    跨源/Tauri webview cookie 带不上，用 ?user=&sig= 短期签名（前端先调
    POST /files/sign 换 path 级签名，详见 ethan.core.signed_url），不再把长效
    token 放进 URL（会留在访问日志/浏览器历史里）。
    其余流程与 verify_token 一致：解析 user_id、set_user_id、注入 request.state。
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return _resolve_user(auth.removeprefix("Bearer ").strip(), request)

    # 前端写 cookie 时做了 encodeURIComponent，读回必须 unquote 才能与配置比对
    token = unquote(request.cookies.get("ethan_token", ""))
    if token:
        return _resolve_user(token, request)

    # 签名通道：user + sig（"exp.sighex"）+ path（签名消息含 path，从 query 原样取）
    from ethan.core.signed_url import verify_path_sig

    user = request.query_params.get("user")
    sig = request.query_params.get("sig", "")
    path = request.query_params.get("path", "")
    if user is not None and sig and path and verify_path_sig(user, path, sig):
        set_user_id(user)
        request.state.user_id = user
        return user
    raise HTTPException(status_code=401, detail="Unauthorized")


def create_agent(model: str | None = None, channel: str = "web", user_id: str = "", mode: str = ""):
    """Web 端 Agent 工厂，委托给 core.agent_factory。"""
    from ethan.core.agent_factory import create_agent as _create
    return _create(model=model, channel=channel, user_id=user_id, toolset="full", mode=mode)
