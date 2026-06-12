"""飞书 WebSocket 事件监听器。

通过 `lark-cli event consume im.message.receive_v1` 建立长连接，
无需公网 IP 和 Webhook 配置，ethan serve 启动时自动开始监听。
"""
import asyncio
import json
import logging
import shutil

logger = logging.getLogger(__name__)

_listener_task: asyncio.Task | None = None


async def _send_reaction(message_id: str) -> None:
    """给消息添加思考表情，告知用户已收到。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "im", "reactions", "create",
            "--as", "bot",
            "--params", json.dumps({"message_id": message_id}),
            "--data", json.dumps({"reaction_type": {"emoji_type": "THINKING_FACE"}}),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        if stderr:
            logger.debug("reaction stderr: %s", stderr.decode(errors="replace").strip())
    except Exception:
        logger.debug("Failed to add reaction to %s", message_id, exc_info=True)


async def _send_reply(chat_id: str, text: str) -> None:
    """通过 lark-cli 回复消息。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "im", "+messages-send",
            "--chat-id", chat_id,
            "--text", text,
            "--as", "bot",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=15)
    except Exception:
        logger.exception("Failed to send Lark reply to chat %s", chat_id)


async def _handle_message(event_data: dict) -> None:
    """处理收到的消息事件，调用 Agent 并回复。

    lark-cli event consume 输出的是扁平结构：
    {"chat_id": "oc_xxx", "content": "text", "message_id": "om_xxx",
     "message_type": "text", "sender_id": "ou_xxx", ...}
    """
    from ethan.core.agent import Agent
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message
    from ethan.skills.registry import SkillRegistry
    from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
    from ethan.tools.builtin.shell import ShellTool
    from ethan.tools.builtin.web import WebFetchTool
    from ethan.tools.builtin.web_search import WebSearchTool
    from ethan.tools.registry import ToolRegistry

    # lark-cli 已经把 event 字段展平，直接从顶层读取
    if event_data.get("message_type") != "text":
        return

    # lark-cli 对 text 消息的 content 是预渲染的可读文本，直接用
    text = event_data.get("content", "").strip()
    if not text:
        return

    chat_id = event_data.get("chat_id", "")
    message_id = event_data.get("message_id", "")

    if not chat_id:
        return

    # 立刻加思考表情（不等 Agent 响应）
    asyncio.create_task(_send_reaction(message_id))

    # 查找或创建对应的 Session
    store = SessionStore()
    await store.init()

    try:
        from ethan.core.config import get_config
        prefix = f"lark:{chat_id}:"
        sessions = await store.list_recent(limit=100)
        session_id = None
        for s in sessions:
            if s.title and s.title.startswith(prefix):
                session_id = s.id
                break

        if not session_id:
            cfg = get_config()
            session = await store.create(cfg.defaults.model)
            await store.update_title(session.id, f"{prefix}{session.id[:8]}")
            session_id = session.id

        user_msg = Message(role="user", content=text)
        await store.save_message(session_id, user_msg)

        registry = ToolRegistry()
        for tool in [ShellTool(), WebSearchTool(), WebFetchTool(),
                     FileReadTool(), FileWriteTool(), FileListTool()]:
            registry.register(tool)
        skills = SkillRegistry()
        skills.load()
        agent = Agent(tool_registry=registry, skill_registry=skills)

        response = await agent.chat([user_msg])

        await store.save_message(session_id, response)
        await store.touch(session_id)
    except Exception:
        logger.exception("Agent error handling Lark message")
        await store.close()
        return

    await store.close()

    if response.content:
        await _send_reply(chat_id, response.content)


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
