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
_lark_chat_map: dict[str, str] = {}  # chat_id -> session_id, in-memory cache

def _lark_map_file():
    from pathlib import Path
    from ethan.core.config import CONFIG_DIR
    return CONFIG_DIR / "memory" / "lark_sessions.json"

def _load_lark_map():
    import json
    f = _lark_map_file()
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return {}

def _save_lark_map(mapping: dict):
    import json
    f = _lark_map_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(mapping, ensure_ascii=False))


async def _send_reaction(message_id: str) -> str | None:
    """给消息添加 THINKING 表情，返回 reaction_id 以便后续删除。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "im", "reactions", "create",
            "--as", "bot",
            "--params", json.dumps({"message_id": message_id}),
            "--data", json.dumps({"reaction_type": {"emoji_type": "THINKING"}}),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        data = json.loads(stdout.decode(errors="replace"))
        return data.get("data", {}).get("reaction_id")
    except Exception:
        logger.debug("Failed to add reaction to %s", message_id, exc_info=True)
        return None


async def _remove_reaction(message_id: str, reaction_id: str) -> None:
    """删除之前添加的 THINKING 表情。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "im", "reactions", "delete",
            "--as", "bot",
            "--params", json.dumps({"message_id": message_id, "reaction_id": reaction_id}),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=5)
    except Exception:
        pass


async def _patch_message(message_id: str, text: str) -> bool:
    """用 lark_oapi SDK 更新已发送的消息内容（追加流式效果）。"""
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody
    from ethan.core.config import get_config
    import json as _json

    cfg = get_config()
    lark_cfg = getattr(cfg, "lark", None)
    if not lark_cfg or not lark_cfg.app_id:
        return False

    client = (
        lark.Client.builder()
        .app_id(lark_cfg.app_id)
        .app_secret(lark_cfg.app_secret)
        .build()
    )

    content = _json.dumps({"text": text}, ensure_ascii=False)
    req = (
        PatchMessageRequest.builder()
        .message_id(message_id)
        .request_body(
            PatchMessageRequestBody.builder()
            .content(content)
            .build()
        )
        .build()
    )

    try:
        import asyncio
        resp = await asyncio.to_thread(client.im.v1.message.patch, req)
        return resp.success()
    except Exception:
        return False


async def _send_reply(chat_id: str, text: str) -> str | None:
    """通过 lark-cli 回复消息，使用 --markdown 以正确渲染格式。
    返回发出的消息 message_id（从 JSON stdout 解析），失败时返回 None。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "im", "+messages-send",
            "--chat-id", chat_id,
            "--markdown", text,
            "--as", "bot",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        data = json.loads(stdout.decode(errors="replace"))
        return data.get("data", {}).get("message_id")
    except Exception:
        logger.exception("Failed to send Lark reply to chat %s", chat_id)
        return None


async def _handle_message(event_data: dict) -> None:
    """处理收到的消息事件，调用 Agent 并流式回复。

    lark-cli event consume 输出的是扁平结构：
    {"chat_id": "oc_xxx", "content": "text", "message_id": "om_xxx",
     "message_type": "text", "sender_id": "ou_xxx", ...}

    流式策略：
    - 积累 chunk 直到 ≥80 字符或距上次发送 ≥2 秒
    - 首次 flush：移除 THINKING 表情后发送第一条消息
    - 后续 flush：lark-cli 不支持 patch，直接追加新消息
    - 最终确保完整内容已发出
    """
    from ethan.core.agent import Agent
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message, ToolEvent
    from ethan.skills.registry import SkillRegistry
    from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
    from ethan.tools.builtin.shell import ShellTool
    from ethan.tools.builtin.web import WebFetchTool
    from ethan.tools.builtin.web_search import WebSearchTool
    from ethan.tools.builtin.search import RipgrepTool, FdTool
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

    # 立刻加思考表情，保存 reaction_id 以便回复后删除
    reaction_id = await _send_reaction(message_id)

    # 查找或创建对应的 Session
    store = SessionStore()
    await store.init()

    try:
        from ethan.core.config import get_config
        prefix = f"lark:{chat_id}:"
        # Fast lookup: in-memory cache first, then persistent file
        if not _lark_chat_map:
            _lark_chat_map.update(_load_lark_map())
        session_id = _lark_chat_map.get(chat_id)

        if not session_id:
            cfg = get_config()
            session = await store.create(cfg.defaults.model, source="lark")
            # Set a clean title from the first user message
            from ethan.memory.session import _auto_title
            from ethan.providers.base import Message as _Msg
            auto = _auto_title([_Msg(role="user", content=text)])
            await store.update_title(session.id, auto)
            session_id = session.id
            _lark_chat_map[chat_id] = session.id
            _save_lark_map(_lark_chat_map)
            # New user first contact — send a welcome
            welcome = "嘿！我是 Ethan，你的私人 AI 助手 👋\n\n我已经在这台 Mac mini 上常驻了，有任何事直接找我就行——写代码、查信息、控制设备、管理日程都行。\n\n你叫什么名字？让我记住你~"
            await _send_reply(chat_id, welcome)
            # Let reaction stay visible while user reads welcome, then process their actual message

        # 加载完整历史，让 Agent 拥有上下文
        session_obj = await store.load(session_id)
        session_messages = session_obj.messages if session_obj else []

        user_msg = Message(role="user", content=text)
        await store.save_message(session_id, user_msg)

        registry = ToolRegistry()
        for tool in [ShellTool(), WebSearchTool(), WebFetchTool(),
                     FileReadTool(), FileWriteTool(), FileListTool()]:
            registry.register(tool)
        skills = SkillRegistry()
        skills.load()
        agent = Agent(tool_registry=registry, skill_registry=skills)

        # --- 流式回复（单消息追加模式）---
        FLUSH_CHARS = 80
        FLUSH_SECS = 2.0

        buffer = ""
        full_content = ""
        reaction_removed = False
        reply_message_id: str | None = None  # 第一条回复消息的 ID
        last_flush_time = asyncio.get_event_loop().time()

        async def flush(is_final: bool = False) -> None:
            nonlocal buffer, reaction_removed, last_flush_time, reply_message_id
            if not buffer:
                return
            # 首次发送前先移除 THINKING 表情
            if not reaction_removed:
                if reaction_id and message_id:
                    await _remove_reaction(message_id, reaction_id)
                reaction_removed = True

            if reply_message_id is None:
                # 第一次：新建消息
                reply_message_id = await _send_reply(chat_id, buffer)
            else:
                # 后续：patch 同一条消息（追加内容），实现流式效果
                patched = await _patch_message(reply_message_id, full_content)
                if not patched:
                    # patch 失败则降级为发新消息
                    await _send_reply(chat_id, buffer)

            buffer = ""
            last_flush_time = asyncio.get_event_loop().time()

        async for chunk in agent.stream_chat(session_messages + [user_msg]):
            if isinstance(chunk, ToolEvent):
                continue  # 工具调用事件不发给 Lark

            buffer += chunk
            full_content += chunk

            now = asyncio.get_event_loop().time()
            if len(buffer) >= FLUSH_CHARS or (buffer and now - last_flush_time >= FLUSH_SECS):
                await flush()

        # 发送剩余内容
        await flush(is_final=True)

        # 如果整个流没有触发过任何 flush（空响应），还没移除表情
        if not reaction_removed and reaction_id and message_id:
            await _remove_reaction(message_id, reaction_id)

        # 工具调用完成但没有文字回复时，发一条默认提示
        if not full_content:
            full_content = "（没有找到相关内容）"
            await _send_reply(chat_id, full_content)

        # 保存完整 assistant 消息到 session
        response = Message(role="assistant", content=full_content)
        await store.save_message(session_id, response)
        await store.touch(session_id)

    except Exception:
        logger.exception("Agent error handling Lark message")
        # 确保表情被清理
        if reaction_id and message_id:
            await _remove_reaction(message_id, reaction_id)
        await store.close()
        return

    await store.close()


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
