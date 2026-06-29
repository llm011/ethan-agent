"""会话级 browser 授权(方案 Q6)。

一个 ethan 会话内第一次调用任意 browser 工具时触发一次 consent;
用户批准后,该 session 内后续所有 browser 操作(含 eval)放行,不再询问。

实现方式不改 agent 循环:
  - 工具 consent_check() 读当前 session,未授权则返回描述字符串 → 触发 consent。
  - consent 通过后 agent 才调 run();run() 开头 mark_authorized 记下该 session。
  - 同 session 下次 consent_check 看到已授权 → 返回 None → 跳过询问。
"""
from __future__ import annotations

_authorized: set[str] = set()


def is_authorized(session_id: str) -> bool:
    # 无 session_id(如 REPL/无会话场景)不做会话级门禁,交给渠道硬策略
    return not session_id or session_id in _authorized


def mark_authorized(session_id: str) -> None:
    if session_id:
        _authorized.add(session_id)


def revoke(session_id: str) -> None:
    _authorized.discard(session_id)
