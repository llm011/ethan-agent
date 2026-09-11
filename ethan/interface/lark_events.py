"""兼容 façade：旧路径 `ethan.interface.lark_events` 的弃用转发。

飞书逻辑已迁移到 `ethan.interface.channels.lark` 包（见 #313）。此模块保留旧的
导入路径，避免升级后已有用户脚本（尤其是发布文档里的定时任务回调示例
`from ethan.interface.lark_events import send_lark_notification`）直接
`ModuleNotFoundError`。

新代码请直接从 `ethan.interface.channels.lark.events` 导入。此 façade 会在未来
版本移除。
"""

import warnings

from ethan.interface.channels.lark.events import (  # noqa: F401  re-export
    _wait_lark_listener_stopped,  # 内部符号，api.py 旧引用兜底
    send_lark_image,
    send_lark_notification,
    start_lark_listener,
    stop_lark_listener,
)

warnings.warn(
    "ethan.interface.lark_events 已弃用，请改用 "
    "ethan.interface.channels.lark.events；此兼容路径将在未来版本移除。",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "send_lark_image",
    "send_lark_notification",
    "start_lark_listener",
    "stop_lark_listener",
]
