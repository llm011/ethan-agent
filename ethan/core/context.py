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

# 当前对话的 session_id（browser 工具用来把 browser session 绑到对话，做会话级隔离/授权）。
# 与 user_id 一样用 ContextVar，保证并发请求各自隔离。
ETHAN_SESSION_ID: ContextVar[str] = ContextVar("ETHAN_SESSION_ID", default="")


def set_session_id(sid: str) -> None:
    """设置当前上下文的对话 session_id。"""
    ETHAN_SESSION_ID.set(sid or "")


def get_session_id() -> str:
    """读取当前上下文的对话 session_id。无会话返回 ""。"""
    return ETHAN_SESSION_ID.get()


def set_user_id(uid: str) -> None:
    """设置当前上下文的 user_id。空串或 None 都归一为 default profile。"""
    ETHAN_USER_ID.set(uid or "")


def get_user_id() -> str:
    """读取当前上下文的 user_id。default profile 返回 ""。"""
    return ETHAN_USER_ID.get()


# ── 请求级"激活工具集" ──────────────────────────────────────────
# Fast 档只广播 fast_path 工具白名单；模型用 find_tools 检索并激活长尾工具后，
# 工具名进入此 set，agent 主循环下一轮把它们补进广播清单。
# 与 user_id 一样用 ContextVar，保证 web 并发请求各自隔离。
ACTIVE_TOOLS: ContextVar[frozenset] = ContextVar("ACTIVE_TOOLS", default=frozenset())


def reset_active_tools() -> set:
    """每个请求开头调一次，清空激活集并返回新的可变 set。"""
    s: set = set()
    ACTIVE_TOOLS.set(s)
    return s


def activate_tools(names: list[str]) -> None:
    """把工具名加入当前请求的激活集（find_tools 调用）。"""
    cur = ACTIVE_TOOLS.get()
    if isinstance(cur, frozenset):  # 还没 reset 过，兜底成可变 set
        cur = set()
        ACTIVE_TOOLS.set(cur)
    cur.update(names)


def get_active_tools() -> set:
    """读取当前请求已激活的工具名集合。"""
    return set(ACTIVE_TOOLS.get())
