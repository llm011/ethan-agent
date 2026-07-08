"""Browser control JSON-RPC 协议常量。

method 命名空间对齐 Ethan 扩展(sessions.* / tabs.* / pages.*),
这样移植过来的扩展 rpc 分发逻辑几乎不用改。
"""
from __future__ import annotations

# ethan ←→ 扩展之间的 JSON-RPC method。值必须与扩展侧 dispatch 的字符串一致。
METHODS = {
    # session
    "session_create": "sessions.create",
    "session_attach_current": "sessions.attachCurrent",
    "session_list": "sessions.list",
    "session_rename": "sessions.rename",
    "session_release": "sessions.release",
    "session_close": "sessions.close",
    # tab
    "tab_open": "tabs.open",
    "tab_list": "tabs.list",
    "tab_user_list": "tabs.userList",
    "tab_attach": "tabs.attach",
    "tab_active": "tabs.active",
    "tab_activate": "tabs.activate",
    "tab_close": "tabs.close",
    # page
    "page_snapshot": "pages.snapshot",
    "page_click": "pages.click",
    "page_fill": "pages.fill",
    "page_type": "pages.type",
    "page_press": "pages.press",
    "page_hover": "pages.hover",
    "page_select": "pages.select",
    "page_scroll": "pages.scroll",
    "page_scroll_into_view": "pages.scrollIntoView",
    "page_screenshot": "pages.screenshot",
    "page_get": "pages.get",
    "page_mouse": "pages.mouse",
    "page_wait": "pages.wait",
    "page_eval": "pages.eval",
    "page_upload": "pages.upload",
    "page_save_pdf": "pages.savePdf",
}

# JSON-RPC error code(对齐 Ethan BROWSER_RPC_ERROR_CODE)
ERROR_CODE = {
    "invalid_request": -32600,
    "method_not_found": -32601,
    "invalid_params": -32602,
    "internal_error": -32603,
    "unauthorized": 4001,
    "extension_not_connected": 4101,
    "operation_failed": 4102,
    "session_required": 4103,
    "tab_not_found": 4104,
    "session_not_found": 4107,
    "page_ref_not_found": 4109,
    "page_operation_failed": 4110,
}

# 需要 per-session 串行锁的 method 前缀:页面操作必须在同一 session 内排队,
# 避免两个对话的 CDP 命令交错踩页面状态。
SESSION_SCOPED_PREFIX = "pages."

RPC_VERSION = 1
DEFAULT_REQUEST_TIMEOUT = 30.0  # 秒,单个 RPC 请求超时(Q9)
