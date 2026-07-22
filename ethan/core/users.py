"""Profile 体系 — 命名 profile 定义与 token→user_id 解析。

default profile（user_id=""）隐式存在，数据在 ~/.ethan 顶层，无需 config 条目。
命名 profile 在 config.yaml 的 users 段定义：
  - id          稳定标识符（= profiles/<id> 目录名，建议纯英文）
  - name        显示名
  - web_token   Web UI 浏览器登录 token
  - api_keys    /v1/chat/completions 用的 API key 列表
  - is_admin    是否管理员（仅用于标记，default profile 始终是事实上的 admin）

default profile 的鉴权：
  - web_token 复用 network.auth_token
  - api_keys 复用 network.api_keys（新增字段）
  命中均解析到 user_id=""。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class UserConfig(BaseModel):
    id: str
    name: str = ""
    web_token: str = ""
    api_keys: list[str] = Field(default_factory=list)
    is_admin: bool = False


class UserStore:
    """用户解析：web_token → user_id，api_key → user_id。

    default profile（""）的 token 来自 network.auth_token / network.api_keys，
    由 set_default_tokens() 注入，命中返回 ""。
    """

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
        # default profile 的 token（由 set_default_tokens 注入）
        self._default_web_tokens: set[str] = set()
        self._default_api_keys: set[str] = set()

    def set_default_tokens(self, web_token: str = "", api_keys: list[str] | None = None) -> None:
        """注入 default profile 的鉴权 token。"""
        self._default_web_tokens = {web_token} if web_token else set()
        self._default_api_keys = set(api_keys or [])

    def resolve_web_token(self, token: str) -> Optional[str]:
        if token in self._web_token_map:
            return self._web_token_map[token]
        if token in self._default_web_tokens:
            return ""  # default profile
        return None

    def resolve_api_key(self, key: str) -> Optional[str]:
        if key in self._api_key_map:
            return self._api_key_map[key]
        if key in self._default_api_keys:
            return ""  # default profile
        return None

    def get_admin_user_id(self) -> str:
        """default profile（""）就是事实上的 admin。命名 profile 里有 is_admin 的也返回其 id。"""
        return ""  # default profile 隐式为 admin

    def all_user_ids(self) -> list[str]:
        """所有 profile id，default（""）始终首位。"""
        ids = [u.id for u in self._users]
        return [""] + ids

    def get_user(self, user_id: str) -> Optional[UserConfig]:
        if user_id == "":
            return None  # default profile 无 config 条目
        return self._by_id.get(user_id)


# ── 单例 ─────────────────────────────────────────────────────────
_user_store: Optional[UserStore] = None
_user_store_mtime_ns: int = 0
_last_stat_check: float = 0.0
# 热路径节流：get_user_store 在每次 API 请求鉴权时调用，
# 距上次 stat 超过该间隔才真正发 stat 系统调用，避免高并发下频繁磁盘 I/O
_STAT_THROTTLE_SEC = 2.0


def _config_file_mtime_ns() -> int:
    try:
        from ethan.core.config import CONFIG_FILE
        return CONFIG_FILE.stat().st_mtime_ns
    except OSError:
        return 0


def set_user_store(store: UserStore) -> None:
    global _user_store, _user_store_mtime_ns
    _user_store = store
    # 记录构建时 config.yaml 的 mtime，供 get_user_store 检测外部编辑
    _user_store_mtime_ns = _config_file_mtime_ns()


def get_user_store() -> UserStore:
    """惰性初始化：从 get_config() 读取 users 构建 UserStore，并注入 default tokens。

    config.yaml 被外部直接编辑（如 docker 挂载手工加用户）后无需重启：
    鉴权时检查文件 mtime（2s 节流），变了就 reload_config 重建 store；
    重建失败（如文件写入中途）保留旧 store，下次检查再试。
    """
    global _user_store, _last_stat_check
    if _user_store is None:
        from ethan.core.config import get_config
        config = get_config()
        store = UserStore(config.users)
        store.set_default_tokens(
            web_token=config.network.auth_token,
            api_keys=config.network.api_keys,
        )
        set_user_store(store)
    else:
        import time
        now = time.monotonic()
        if now - _last_stat_check >= _STAT_THROTTLE_SEC:
            _last_stat_check = now
            mtime_ns = _config_file_mtime_ns()
            if mtime_ns and mtime_ns != _user_store_mtime_ns:
                try:
                    from ethan.core.config import reload_config
                    reload_config()  # load_config 内部会 set_user_store 重建并刷新 mtime
                except Exception:
                    pass  # 保留旧 store
    return _user_store


def reset_user_store() -> None:
    """reload_config 后调用，强制重建。"""
    global _user_store, _user_store_mtime_ns, _last_stat_check
    _user_store = None
    _user_store_mtime_ns = 0
    _last_stat_check = 0.0


def ensure_admin_user_exists(users: list[UserConfig], fallback_token: str = "") -> list[UserConfig]:
    """default profile 隐式存在，无需为它创建 config 条目。直接返回原列表。"""
    return users
