"""飞书 WebSocket 事件监听器（入口 + 生命周期）。

通过 `lark-cli event consume im.message.receive_v1` 建立长连接，
无需公网 IP 和 Webhook 配置，ethan serve 启动时自动开始监听。

实现已拆分到同目录的子模块：
- lark_render：消息渲染（post / 卡片 content JSON）
- lark_send：收发 IO（client / 发送/编辑/删除/通知/图片）
- lark_stream：消息处理（命令路由 + Agent 流式回复）
本模块只保留事件消费循环和 start/stop，并 re-export 外部用到的符号
（api.py 用 start/stop_lark_listener，browser 模块用 send_lark_image 等）。
"""
import asyncio
import json
import logging
import shutil

from ethan.interface.lark_send import (  # re-export: 外部（browser/定时任务）依赖这些
    send_lark_image,
    send_lark_notification,
)
from ethan.interface.lark_stream import _handle_message

__all__ = [
    "start_lark_listener",
    "stop_lark_listener",
    "send_lark_notification",
    "send_lark_image",
]

logger = logging.getLogger(__name__)

_listener_task: asyncio.Task | None = None


async def _event_loop() -> None:
    """持续运行 lark-cli event consume，断线自动重连。"""
    lark_cli = shutil.which("lark-cli")
    if not lark_cli:
        logger.warning("[Lark] lark-cli not found — event listener not started")
        return

    from ethan.core.config import get_config
    cfg = get_config()
    lark_cfg = getattr(cfg, "lark", None)
    if not lark_cfg or not lark_cfg.app_id or not lark_cfg.app_secret:
        logger.info("[Lark] app_id/app_secret not configured — skipping event listener")
        return

    logger.info("[Lark] Starting WebSocket event listener via lark-cli...")

    backoff = 5
    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                lark_cli, "event", "consume", "im.message.receive_v1",
                "--as", "bot", "--quiet",
                stdin=asyncio.subprocess.PIPE,  # keep stdin open so lark-cli doesn't exit on EOF
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            logger.info("[Lark] Connected to Feishu event bus (pid=%s)", proc.pid)
            backoff = 5  # reset backoff on successful connect

            async for line in proc.stdout:
                raw = line.decode(errors="replace").strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                # Events have nested structure: data.event.message
                event = data.get("event", data)
                asyncio.create_task(_handle_message(event))

            await proc.wait()
            logger.warning("[Lark] Event stream ended, reconnecting in %ss...", backoff)

        except asyncio.CancelledError:
            logger.info("[Lark] Event listener cancelled.")
            return
        except Exception:
            logger.exception("[Lark] Event listener crashed, reconnecting in %ss...", backoff)

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)


def start_lark_listener() -> None:
    """在当前 event loop 中启动飞书事件监听器（FastAPI startup 时调用）。"""
    global _listener_task
    if _listener_task and not _listener_task.done():
        return
    _listener_task = asyncio.create_task(_event_loop())
    logger.info("[Lark] Event listener task created.")


def stop_lark_listener() -> None:
    """停止飞书事件监听器（FastAPI shutdown 时调用）。"""
    global _listener_task
    if _listener_task and not _listener_task.done():
        _listener_task.cancel()
