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


def _render_post_content(text: str) -> str:
    """把多行文本/markdown 渲染成飞书 post 消息的 content JSON 字符串。

    post 格式：每行一个段落（content 数组的一个元素），行内不做 markdown 解析，
    直接当纯文本——飞书 post 的 text 标签会保留换行和原始字符。
    流式编辑时整条消息用同一个 post，patch 时整体替换 content。
    """
    import json as _json
    lines = text.split("\n")
    content = [[{"tag": "text", "text": line}] for line in lines]
    return _json.dumps({"zh_cn": {"content": content}}, ensure_ascii=False)


async def _send_post_message(chat_id: str, text: str) -> str | None:
    """用 lark_oapi SDK 发一条 post（富文本）消息，返回 message_id。

    post 类型可被 patch 更新（text 类型不行），用于流式编辑同一条消息。
    """
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
    from ethan.core.config import get_config
    import json as _json

    cfg = get_config()
    lark_cfg = getattr(cfg, "lark", None)
    if not lark_cfg or not lark_cfg.app_id:
        return None
    client = (
        lark.Client.builder()
        .app_id(lark_cfg.app_id)
        .app_secret(lark_cfg.app_secret)
        .build()
    )
    content = _render_post_content(text)
    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("post")
            .content(content)
            .build()
        )
        .build()
    )
    try:
        resp = await asyncio.to_thread(client.im.v1.message.create, req)
        if resp.success() and resp.data:
            return resp.data.message_id
        return None
    except Exception:
        logger.exception("Failed to send post message to chat %s", chat_id)
        return None


async def _patch_message(message_id: str, text: str) -> bool:
    """用 lark_oapi SDK 更新已发送的 post 消息内容（流式追加效果）。

    飞书 patch 只支持 post/卡片，不支持 text。所以流式消息必须用 post 类型发出，
    之后用本函数整体替换 content。
    """
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody
    from ethan.core.config import get_config

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

    content = _render_post_content(text)
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
    from ethan.tools.builtin.knowledge import KnowledgeAddTool, KnowledgeSearchTool
    from ethan.tools.builtin.memory_write import MemoryWriteTool
    from ethan.tools.builtin.procedure_write import ProcedureWriteTool
    from ethan.tools.builtin.profile_update import ProfileUpdateTool
    from ethan.tools.builtin.schedule import ScheduleCreateTool, ScheduleListTool, ScheduleRemoveTool
    from ethan.tools.builtin.skill_create import SkillCreateTool
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

    # 查找或创建对应的 Session（lark 渠道归 admin）
    from ethan.core.users import get_user_store
    from ethan.core.paths import user_sessions_db_path
    lark_uid = get_user_store().get_admin_user_id()
    store = SessionStore(db_path=user_sessions_db_path())
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

        # 加载完整历史，用 WorkingMemory 重建热区（与 REPL/API 一致）
        session_obj = await store.load(session_id)
        history = session_obj.messages if session_obj else []

        user_msg = Message(role="user", content=text)
        await store.save_message(session_id, user_msg)

        # 重建 WorkingMemory：热区最近 10 轮 + cold facts（per-user）
        from ethan.memory.working import MemoryConfig, WorkingMemory
        from ethan.memory.facts import FactStore
        from ethan.core.paths import user_facts_path
        memory = WorkingMemory(config=MemoryConfig(hot_size=10))
        memory.cold_facts = FactStore(path=user_facts_path()).build_context()
        hist_ua = [m for m in history if m.role in ("user", "assistant")]
        pairs, i = [], 0
        while i < len(hist_ua) - 1:
            if hist_ua[i].role == "user" and hist_ua[i+1].role == "assistant":
                pairs.append((hist_ua[i], hist_ua[i+1]))
                i += 2
            else:
                i += 1
        for u, a in pairs[-memory.config.hot_size:]:
            memory.hot.append(u)
            memory.hot.append(a)
        context_messages = memory.build_context() + [user_msg]

        registry = ToolRegistry()
        for tool in [ShellTool(), WebSearchTool(), WebFetchTool(),
                     FileReadTool(), FileWriteTool(), FileListTool(),
                     RipgrepTool(), FdTool(),
                     ScheduleCreateTool(), ScheduleListTool(), ScheduleRemoveTool(),
                     KnowledgeSearchTool(), KnowledgeAddTool(),
                     MemoryWriteTool(), ProcedureWriteTool(), ProfileUpdateTool(), SkillCreateTool()]:
            registry.register(tool)
        skills = SkillRegistry()
        skills.load()
        agent = Agent(tool_registry=registry, skill_registry=skills, channel="lark")

        # --- 流式输出：一条 post 消息，靠 patch 不断追加 ---
        # 策略：
        # 1. 收到消息先发一条 "🤔 thinking..." 的 post（替代纯表情），拿到 msg_id 作为编辑目标
        # 2. stream_chat 过程中：
        #    - content 首块立即 patch 显示；之后每 ~2s 攒一批 patch 一次（节流，少调 API）
        #    - ToolEvent start：把工具叙述 + 🔧 工具(参数) 追加进消息
        #    - ToolEvent done：追加一行结果预览
        # 3. 全程只编辑这同一条消息；结束追加 token 统计
        import time as _lark_time

        post_msg_id = await _send_post_message(chat_id, "🤔 thinking...")
        # 发出首条后即可移除 THINKING 表情（消息本身已是处理中指示）
        if reaction_id and message_id:
            await _remove_reaction(message_id, reaction_id)
            reaction_id = None  # 标记已移除，后面不再处理

        # displayed = 已经 patch 进飞书消息的文本；pending = 还没 flush 的累积正文
        # "🤔 thinking..." 占位留在开头，首个真实内容出现后追加在其后
        displayed = "🤔 thinking..."
        pending = ""
        collected_tool_steps: list[dict] = []
        lark_tool_start_times: dict[str, float] = {}
        last_flush = _lark_time.time()
        first_chunk_flushed = False
        FLUSH_INTERVAL = 2.0  # 秒：首块后每 2s 攒一批 patch 一次

        async def _flush(force: bool = False) -> None:
            """把 pending 追加进 displayed 并 patch 消息。force=True 无视节流立即 flush。"""
            nonlocal displayed, pending, last_flush, first_chunk_flushed
            if not pending:
                return
            now = _lark_time.time()
            # 首块立即 flush；之后按 FLUSH_INTERVAL 节流
            if not force and first_chunk_flushed and (now - last_flush) < FLUSH_INTERVAL:
                return
            displayed = displayed + pending
            pending = ""
            last_flush = now
            first_chunk_flushed = True
            if post_msg_id:
                await _patch_message(post_msg_id, displayed)

        async for chunk in agent.stream_chat(context_messages):
            if isinstance(chunk, ToolEvent):
                # 工具事件：先把积压的正文 flush，再追加工具调用信息
                await _flush(force=True)
                if chunk.state == "start":
                    lark_tool_start_times[chunk.tool_name] = _lark_time.time()
                    collected_tool_steps.append({
                        "tool": chunk.tool_name,
                        "args": chunk.args_summary,
                        "state": "running",
                        "duration_ms": None,
                        "result_preview": "",
                    })
                    tool_line = f"🔧 {chunk.tool_name}"
                    if chunk.args_summary:
                        tool_line += f"({chunk.args_summary})"
                    displayed = displayed.rstrip() + "\n" + tool_line + "\n"
                    if post_msg_id:
                        await _patch_message(post_msg_id, displayed)
                else:  # done / error
                    duration_ms = int(
                        (_lark_time.time() - lark_tool_start_times.pop(chunk.tool_name, _lark_time.time())) * 1000
                    )
                    for step in reversed(collected_tool_steps):
                        if step["tool"] == chunk.tool_name and step["state"] == "running":
                            step["state"] = chunk.state
                            step["duration_ms"] = duration_ms
                            step["result_preview"] = chunk.result_preview or ""
                            break
                    # 工具结束：追加一行结果预览（截断到 ~80 字）
                    mark = "✓" if chunk.state == "done" else "✗"
                    preview = (chunk.result_preview or "").replace("\n", " ")[:80]
                    if preview:
                        displayed = displayed.rstrip() + f"\n  {mark} {preview}\n"
                    else:
                        displayed = displayed.rstrip() + f"\n  {mark} {duration_ms}ms\n"
                    if post_msg_id:
                        await _patch_message(post_msg_id, displayed)
                continue
            # 正文 chunk
            pending += chunk
            await _flush()

        # 流结束：把剩余 pending 全部 flush
        await _flush(force=True)

        # 如果整条消息还停在 thinking 占位（没产出任何内容/工具），给个兜底
        if displayed == "🤔 thinking...":
            displayed = "（没有找到相关内容）"

        # 末尾加分隔线 + token 消耗
        usage = agent.usage
        stats_parts = [f"↑{usage.input_tokens} ↓{usage.output_tokens}"]
        if usage.cache_tokens:
            stats_parts.append(f"⚡{usage.cache_tokens}")
        stats_line = "  ".join(stats_parts)
        final_text = displayed.rstrip() + f"\n\n---\n_{stats_line}_"
        if post_msg_id:
            await _patch_message(post_msg_id, final_text)
        else:
            # post 消息没发成功（如未配 lark app），兜底用 lark-cli text 发
            await _send_reply(chat_id, final_text)

        # full_content 存库：去掉 thinking 占位和工具调用行，只留正文（与最终回复一致）
        full_content = final_text

        # 保存完整 assistant 消息到 session（带 usage + tool_steps）
        usage_dict = {
            "input": agent.usage.input_tokens,
            "output": agent.usage.output_tokens,
            "cache": agent.usage.cache_tokens,
        }
        response = Message(role="assistant", content=full_content, usage=usage_dict, tool_steps=collected_tool_steps or [])
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
