"""请求级 user_id 上下文。

用 ContextVar 携带当前请求的 profile/user_id，避免在所有 path 函数和工具
构造函数里串参。verify_token / _build_agent / lark 在 resolve 出 user_id
后调用 set_user_id()，之后所有 user_*_path() 自动读到正确的 profile。

ContextVar 在 asyncio.create_task 和 asyncio.to_thread 下都会正确继承，
所以后台任务（_maybe_consolidate 等）也能读到触发请求的 user_id。

默认值 "" 表示 default profile（~/.ethan 本身）。
"""
from contextvars import ContextVar

ETHAN_USER_ID: ContextVar[str] = ContextVar("ETHAN_USER_ID", default="")


def set_user_id(uid: str) -> None:
    """设置当前上下文的 user_id。空串或 None 都归一为 default profile。"""
    ETHAN_USER_ID.set(uid or "")


def get_user_id() -> str:
    """读取当前上下文的 user_id。default profile 返回 ""。"""
    return ETHAN_USER_ID.get()
