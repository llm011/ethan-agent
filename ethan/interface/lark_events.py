"""飞书 WebSocket 事件监听器（入口 + 生命周期）。

通过 `lark-cli event consume <EventKey>` 建立长连接，
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

__all__ = [
    "start_lark_listener",
    "stop_lark_listener",
    "send_lark_notification",
    "send_lark_image",
]

logger = logging.getLogger(__name__)

_listeners: list[asyncio.Task] = []

# EventKey 常量：通过 lark-cli event list 获取
# 注意：card.action.trigger 需 lark-cli ≥ 1.0.58（PR #1528）且在飞书开发者后台开启该 Console Event。
_EVENT_KEYS = [
    "im.message.receive_v1",          # 收消息
    "im.message.reaction.created_v1", # 消息被加 reaction
    "card.action.trigger",            # 交互卡片按钮/表单回调（lark-cli ≥ 1.0.58）
    # "im.message.message_read_v1",   # 需在飞书开发者后台订阅后才能启用
    # "im.message.reaction.deleted_v1", # reaction 被删（可后续添加）
]


async def _event_loop(event_key: str) -> None:
    """持续运行 lark-cli event consume <event_key>，断线自动重连。

    每个 EventKey 各跑一个本函数（在独立的 task 里），子进程挂了只重启自己，不影响其他 key。
    """
    import os

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

    logger.info("[Lark] Starting WebSocket event listener for %s via lark-cli...", event_key)

    # 确保 lark-cli 已绑定正确的 app（容器重启后 ~/.lark-cli/ 丢失时自动重建）
    from ethan.interface.lark_deps import _lark_cli_current_app, _sync_lark_cli_app
    current_app = _lark_cli_current_app()
    if current_app != lark_cfg.app_id:
        logger.info("[Lark] Syncing lark-cli app config (current=%s, expected=%s)...",
                    current_app, lark_cfg.app_id)
        ok, err = _sync_lark_cli_app(lark_cfg.app_id, lark_cfg.app_secret)
        if not ok:
            logger.error("[Lark] Failed to sync lark-cli app: %s — event listener not started", err)
            return

    # 延迟导入 _dispatch，避免模块加载时拉起 lark_oapi（与原实现一致：lark_oapi 留给子进程）。
    from ethan.interface.lark_stream import _dispatch

    backoff = 5
    while True:
        # lark-cli 把 stdin EOF 当退出信号。DEVNULL=/dev/null 立即 EOF；PIPE 在父端关闭时 EOF。
        # 正确做法：用 os.pipe()，把读端给子进程，写端留在父进程不关，子进程永远拿不到 EOF。
        r_fd, w_fd = os.pipe()
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                lark_cli, "event", "consume", event_key,
                "--as", "bot",
                stdin=r_fd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            os.close(r_fd)  # 子进程已继承读端，父进程关掉自己的副本
            r_fd = -1
            logger.info("[Lark] Connected to Feishu event bus for %s (pid=%s)", event_key, proc.pid)
            backoff = 5  # reset backoff on successful connect

            async for line in proc.stdout:
                raw = line.decode(errors="replace").strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                # lark-cli 报 validation 错误（未在后台订阅该事件）→ 停止重连
                if data.get("ok") is False and data.get("error", {}).get("type") == "validation":
                    logger.warning(
                        "[Lark] EventKey %s not subscribed in Feishu console, stopping listener. "
                        "Error: %s", event_key, data["error"].get("message", "")
                    )
                    proc.terminate()
                    return

                # Events have nested structure: data.event.message
                event = data.get("event", data)
                try:
                    await _dispatch(event_key, event)
                except Exception:
                    logger.exception("[Lark] _dispatch failed for %s", event_key)

            await proc.wait()
            # 读取 stderr 帮助诊断 lark-cli 退出原因
            stderr_out = ""
            if proc.stderr:
                stderr_bytes = await proc.stderr.read()
                stderr_out = stderr_bytes.decode(errors="replace").strip()
            if stderr_out:
                logger.warning("[Lark] Event stream for %s ended (exit=%s), stderr: %s",
                               event_key, proc.returncode, stderr_out[:500])
            else:
                logger.warning("[Lark] Event stream for %s ended (exit=%s), reconnecting in %ss...",
                               event_key, proc.returncode, backoff)

        except asyncio.CancelledError:
            logger.info("[Lark] Event listener for %s cancelled.", event_key)
            # 必须等子进程真正退出，否则 lark-cli 孤儿进程继续占着飞书 WebSocket 连接，
            # 重启后新进程无法连接（或被飞书踢掉）。
            if proc is not None and proc.returncode is None:
                try:
                    proc.terminate()
                    await proc.wait()
                except Exception:
                    pass
            return
        except Exception:
            logger.exception("[Lark] Event listener for %s crashed, reconnecting in %ss...", event_key, backoff)
        finally:
            # 关闭写端（向子进程发 EOF），确保子进程能退出
            if r_fd != -1:
                try:
                    os.close(r_fd)
                except OSError:
                    pass
            try:
                os.close(w_fd)
            except OSError:
                pass

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)


def start_lark_listener() -> None:
    """在当前 event loop 中启动飞书事件监听器（FastAPI startup 时调用）。

    为 _EVENT_KEYS 里每个 EventKey 各起一个 _event_loop task，独立断线重连、互不影响。
    多次调用幂等：已有 task 在跑则直接返回。
    """
    global _listeners
    if _listeners and any(not t.done() for t in _listeners):
        return
    _listeners = [asyncio.create_task(_event_loop(key)) for key in _EVENT_KEYS]
    logger.info("[Lark] Event listener tasks created: %s", ", ".join(_EVENT_KEYS))


def stop_lark_listener() -> None:
    """停止飞书事件监听器（FastAPI shutdown 时调用）。取消所有子 task。
    注意：此函数只发取消信号。调用方须 await _wait_lark_listener_stopped() 等子进程真正退出，
    否则 lark-cli 孤儿进程会继续占着飞书 WebSocket，重启后新进程无法连接。"""
    global _listeners
    for t in _listeners:
        if not t.done():
            t.cancel()


async def _wait_lark_listener_stopped() -> None:
    """等待所有 _event_loop task 完成（含子进程退出）。在 stop_lark_listener 之后调用。"""
    global _listeners
    if _listeners:
        await asyncio.gather(*_listeners, return_exceptions=True)
    _listeners = []
