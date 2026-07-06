"""共享依赖：鉴权、Agent 工厂。"""
from fastapi import HTTPException, Request

from ethan.core.context import set_user_id


async def verify_token(request: Request) -> str:
    """Bearer token 鉴权（用于内部管理 API），返回 user_id 并 set 进 ContextVar。

    解析顺序：
      1. config.users[].web_token / network.auth_token(default profile) → user_id
      2. 命中后 set_user_id，后续所有 path 函数自动读到正确 profile
    """
    from ethan.core.users import get_user_store
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth.removeprefix("Bearer ").strip()

    user_store = get_user_store()
    user_id = user_store.resolve_web_token(token)

    if user_id is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    set_user_id(user_id)  # 后续 ensure_user_dirs / path 函数依赖此 ContextVar
    request.state.user_id = user_id
    return user_id


def create_agent(model: str | None = None, channel: str = "web", user_id: str = "", mode: str = ""):
    """Web 端 Agent 工厂，委托给 core.agent_factory。"""
    from ethan.core.agent_factory import create_agent as _create
    return _create(model=model, channel=channel, user_id=user_id, toolset="full", mode=mode)
