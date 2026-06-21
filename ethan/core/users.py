"""多用户体系 — 用户定义与 token→user_id 解析。

每个用户在 config.yaml 的 users 段定义，拥有：
  - id          稳定标识符（用作 per-user 数据目录名，建议纯英文）
  - name        显示名
  - web_token   Web UI 浏览器登录 token
  - api_keys    /v1/chat/completions 用的 API key 列表
  - is_admin    是否管理员

同一个用户的 web_token 和 api_keys 都解析到同一个 user_id ——
浏览器登录和程序调用 API 访问的是同一份记忆/skills/knowledge。
"""
from __future__ import annotations

import secrets
from typing import Optional

from pydantic import BaseModel, Field


class UserConfig(BaseModel):
    id: str
    name: str = ""
    web_token: str = ""
    api_keys: list[str] = Field(default_factory=list)
    is_admin: bool = False


class UserStore:
    """用户解析：web_token → user_id，api_key → user_id。"""

    def __init__(self, users: list[UserConfig]):
        self._users: list[UserConfig] = users
        self._by_id: dict[str, UserConfig] = {u.id: u for u in users}
        self._web_token_map: dict[str, str] = {}
        self._api_key_map: dict[str, str] = {}
        for u in users:
            if u.web_token:
                self._web_token_map[u.web_token] = u.id
            for k in u.api_keys:
                if k:
                    self._api_key_map[k] = u.id

    def resolve_web_token(self, token: str) -> Optional[str]:
        return self._web_token_map.get(token)

    def resolve_api_key(self, key: str) -> Optional[str]:
        return self._api_key_map.get(key)

    def get_admin_user_id(self) -> str:
        """第一个 is_admin=True 的用户；都没有则回退第一个用户；都没有则 'admin'。"""
        for u in self._users:
            if u.is_admin:
                return u.id
        if self._users:
            return self._users[0].id
        return "admin"

    def all_user_ids(self) -> list[str]:
        return [u.id for u in self._users]

    def get_user(self, user_id: str) -> Optional[UserConfig]:
        return self._by_id.get(user_id)


# ── 单例 ─────────────────────────────────────────────────────────
_user_store: Optional[UserStore] = None


def set_user_store(store: UserStore) -> None:
    global _user_store
    _user_store = store


def get_user_store() -> UserStore:
    """惰性初始化：从 get_config() 读取 users 构建 UserStore。"""
    global _user_store
    if _user_store is None:
        from ethan.core.config import get_config
        config = get_config()
        _user_store = UserStore(config.users)
    return _user_store


def reset_user_store() -> None:
    """reload_config 后调用，强制重建。"""
    global _user_store
    _user_store = None


def ensure_admin_user_exists(users: list[UserConfig], fallback_token: str = "") -> list[UserConfig]:
    """users 为空时自动生成一个 admin 用户（兼容现有单用户部署）。

    web_token 复用现有 network.auth_token，保证旧 token 仍能登录。
    """
    if users:
        return users
    return [UserConfig(
        id="admin",
        name="Admin",
        web_token=fallback_token or secrets.token_hex(6),
        api_keys=[],
        is_admin=True,
    )]
