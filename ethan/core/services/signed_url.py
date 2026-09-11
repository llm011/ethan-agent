"""短期签名 URL —— 替代把长效 web_token 放在 ?token= 里。

浏览器直链（<img src> / <a download>）无法带 Authorization header，旧方案把
长效 token 拼进 URL，会留在服务端访问日志、浏览器历史和 Referer 里。
改为：前端先调 POST /api/files/sign（正常鉴权）换 path 级短期签名，
再把签名拼进 URL（?user=&exp=&sig= 形式，sig 参数值为 "exp.sighex"）。

签名设计：
  - HMAC key = 该用户的 web_token（无需新增服务端密钥配置；token 轮换即失效）
  - message = "{user_id}\n{path}\n{exp}" —— 绑定用户 + 路径 + 过期时间
  - 默认 10 分钟有效，过期/改路径/跨用户一律验签失败
注意：签名只替代「认证」，session 交付授权仍在路由内独立校验。
"""
from __future__ import annotations

import hashlib
import hmac
import time

TTL_SECONDS = 600


def _signing_keys(user_id: str) -> list[str]:
    from ethan.core.users import get_user_store

    return get_user_store().web_tokens_for(user_id)


def sign_path(user_id: str, path: str, now: int | None = None) -> str:
    """生成 path 的签名参数值 "exp.sighex"；用户无 token 时抛 ValueError。"""
    keys = _signing_keys(user_id)
    if not keys:
        raise ValueError(f"no web token configured for user {user_id!r}")
    exp = int(now if now is not None else time.time()) + TTL_SECONDS
    msg = f"{user_id}\n{path}\n{exp}".encode("utf-8")
    sig = hmac.new(keys[0].encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def verify_path_sig(user_id: str, path: str, token: str, now: int | None = None) -> bool:
    """校验 sign_path 产出的签名：格式、有效期、HMAC（多 key 候选逐一比对）。"""
    try:
        exp_s, sig = token.split(".", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    if not sig or exp < int(now if now is not None else time.time()):
        return False
    msg = f"{user_id}\n{path}\n{exp}".encode("utf-8")
    for key in _signing_keys(user_id):
        good = hmac.new(key.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        if hmac.compare_digest(good, sig):
            return True
    return False
