"""Schedule Tool — 让 agent 通过 tool call 创建和管理定时任务。"""
import asyncio
import json
import os
import threading
from contextvars import ContextVar

import httpx

from ethan.tools.base import BaseTool

# 存储当前请求的飞书 chat_id，在 lark webhook 里设置，ScheduleCreateTool 里读取
lark_chat_id_var: ContextVar[str] = ContextVar("lark_chat_id", default="")
wechat_chat_id_var: ContextVar[str] = ContextVar("wechat_chat_id", default="")

# 主 server event loop 引用，在 lifespan startup 时设置
_server_loop: asyncio.AbstractEventLoop | None = None


def set_server_loop(loop: asyncio.AbstractEventLoop) -> None:
    """在 server startup 时调用，保存主 event loop 引用供定时任务回调使用。"""
    global _server_loop
    _server_loop = loop


def get_server_loop() -> asyncio.AbstractEventLoop | None:
    """供 agenda 等其他调度回调模块读取主 event loop。"""
    return _server_loop


def _try_strptime(s: str, fmt: str) -> bool:
    from datetime import datetime
    try:
        datetime.strptime(s, fmt)
        return True
    except ValueError:
        return False


def _base_url() -> str:
    """返回本地 serve 的 base URL（读取 ETHAN_SERVER_PORT，默认 8900）。"""
    port = os.environ.get("ETHAN_SERVER_PORT", "8900")
    return f"http://127.0.0.1:{port}"


def _http_client(**kwargs) -> httpx.AsyncClient:
    """创建 httpx 客户端，强制不读代理环境变量（避免容器内 HTTP_PROXY 导致本机回环 502）。"""
    kwargs.setdefault("trust_env", False)
    return httpx.AsyncClient(**kwargs)


def _make_fallback_title(prompt: str) -> str:
    """无 title 时从 prompt 生成短标题：中文取前 15 字，英文取前 5 个单词。"""
    text = prompt.replace("\n", " ").strip()
    if not text:
        return "未命名任务"
    words = text.split()
    # 含中文字符 → 按字数截取
    if any('\u4e00' <= c <= '\u9fff' for c in text[:20]):
        return text[:15] + ("…" if len(text) > 15 else "")
    # 纯英文 → 按单词截取
    if len(words) <= 5:
        return text
    return " ".join(words[:5]) + "…"


def _is_pure_send_confirmation(data: dict) -> bool:
    """判断 JSON 对象是否仅是消息发送的确认结果。

    仅当 JSON 结构满足以下任一"纯发送确认"形态时返回 True：
    - {"message_id": "om_xxx"}（顶层只有 message_id 字符串）
    - {"ok": true, "code": 0, "msg": "...", "data": {"message_id": "om_xxx"}}
      （顶层 keys 限定为 ok/code/msg/data，且 data 子对象只有 message_id 字符串）

    任何包含其他业务字段的 JSON 都会返回 False，不会误杀合法结果。
    """
    top_keys = set(data.keys())

    # 形态1: 仅含 message_id
    if top_keys == {"message_id"} and isinstance(data.get("message_id"), str):
        return True

    # 形态2: API 风格包装——顶层 keys 必须是 {ok, code, msg, data} 的子集，
    # 且 data 必须是仅含 message_id 的 dict，不能携带其他业务数据
    if not top_keys <= {"ok", "code", "msg", "data"}:
        return False
    nested = data.get("data")
    if not isinstance(nested, dict):
        return False
    if set(nested.keys()) != {"message_id"}:
        return False
    if not isinstance(nested.get("message_id"), str):
        return False
    # ok 字段若存在须为 true（成功发送）；失败响应不应被静默吞掉
    if "ok" in data and data["ok"] is not True:
        return False
    return True


def _is_tool_result_noise(text: str) -> bool:
    """检测 agent 的回复是否仅为消息发送工具的返回噪音。

    判断标准极其保守：**整个回复**必须只是一个发送确认 JSON（裸 JSON 或被单个
    markdown 代码块包裹），不能包含任何其他文字说明。只要回复中夹杂了任何人类可读
    的文本（如代码块外的"已发送"、结果摘要等），就返回 False，保证不会误杀合法结果。

    这是一层防御性兜底——主要修复依赖 runtime_context 从源头阻止 agent 自行发消息。
    """
    import re
    stripped = text.strip()
    if not stripped:
        return False

    inner = None  # 用于尝试 JSON 解析的内容

    # 用 fullmatch 严格检测：整个字符串是否只是一个 markdown 代码块
    fence_match = re.fullmatch(r"```(?:\w*\n)?(.+?)\n?```\s*", stripped, re.DOTALL)
    if fence_match:
        inner = fence_match.group(1).strip()
    elif stripped.startswith("{") and stripped.endswith("}"):
        # 整个字符串是裸 JSON 对象
        inner = stripped
    else:
        # 代码块外有额外文字，或不是 JSON → 不是纯噪音
        return False

    try:
        data = json.loads(inner)
    except (json.JSONDecodeError, ValueError):
        return False

    return isinstance(data, dict) and _is_pure_send_confirmation(data)


def fire_schedule_job(session_id: str, prompt: str, channel: str = "web", channel_context: str = "{}", user_id: str = "", title: str = "", **_extra):
    """定时任务触发时的回调。

    **_extra 接收并忽略 timeline / scene / source_timeline 等元数据字段，
    它们用于 UI 分类展示，不参与 fire 行为。

    执行流程与普通对话完全对齐：使用 stream_chat() + StreamCollector 实时
    持久化工具调用过程（tool_steps），便于事后排查问题。
    """
    import logging as _entry_log
    _entry_logger = _entry_log.getLogger("ethan.schedule")
    # job_id 由 cron.py 的 add_cron/add_interval/add_date 写入 kwargs，
    # 用于 session 轮转时回写新的 session_id 到 job
    job_id = _extra.get("job_id", "")
    _entry_logger.info("[Schedule] fire_schedule_job called: session=%s title=%r", session_id, title)

    async def _run_schedule_task(*, dedicated_store: bool = False):
        """在 server event loop 中跑完整 agent 流式循环，实时落库工具步骤。

        dedicated_store=True 时创建独立 SessionStore 连接（绑当前 loop），
        用于 fallback 线程路径——单例连接绑主 loop，跨 loop await 必崩
        （aiosqlite _tx 队列和 _session_store_lock 都绑主 loop）。
        """
        nonlocal session_id
        import logging as _log

        from ethan.core.agent_factory import create_agent
        from ethan.core.consent import AutoConsentProvider, set_consent_provider
        from ethan.core.context import set_session_id
        from ethan.core.stream_collector import StreamCollector
        from ethan.interface.routers.producers import _save_progress
        from ethan.memory.session import get_session_store
        from ethan.providers.base import Message, ToolEvent

        _logger = _log.getLogger("ethan.schedule")
        _logger.info("[Schedule] _run_schedule_task started: session=%s title=%r dedicated=%s",
                     session_id, title, dedicated_store)
        result_text = ""
        collector = None
        agent = None
        consent = None
        progress_msg_id: int | None = None
        store = None

        async def _open_store():
            """获取 store：dedicated 模式创建独立连接（绑当前 loop），否则用单例。"""
            if dedicated_store:
                from ethan.core.paths import user_sessions_db_path
                from ethan.memory.session import SessionStore
                s = SessionStore(db_path=user_sessions_db_path())
                await s.init()
                return s
            return await get_session_store()

        # 构造 runtime_context
        if channel in ("lark", "wechat"):
            channel_hint = "飞书对话" if channel == "lark" else "微信"
            schedule_ctx = (
                f"【定时任务执行环境】你正在执行一个定时任务（cron job）。\n"
                f"任务完成后，你的回复将被自动发送到创建该任务时的{channel_hint}中，用户会收到。\n"
                f"【重要】\n"
                f"1. 不要自己调用 shell/lark-cli 等工具来发消息——系统会自动把你的回复发给用户。\n"
                f"2. 直接输出任务结果文本即可，简洁明了。不要输出工具调用的返回值（如 JSON、message_id）。\n"
                f"3. 如果任务要求发送消息到某个聊天/群（而非本对话），仍需你输出内容（系统会发到目标），不要自己执行发送命令。"
            )
        else:
            schedule_ctx = (
                "【定时任务执行环境】你正在执行一个定时任务（cron job）。\n"
                "任务完成后，你的回复将保存到会话记录中，用户可在 Web 界面的定时任务详情里查看。\n"
                "直接输出任务结果文本即可，简洁明了。"
            )

        try:
            from ethan.core.config import get_config as _gc

            store = await _open_store()
            set_session_id(session_id)

            # 确保 session 记录存在
            existing = await store.load(session_id)
            if not existing:
                await store.create_with_id(session_id, _gc().defaults.model,
                                           source="schedule", mode="")

            # 防护：确保 session 标题保持 [定时] 前缀（防止被 regen-title 覆盖）
            if existing and not (existing.title or "").startswith("[定时]"):
                _expected_title = f"[定时] {title}" if title else "[定时] 未命名任务"
                try:
                    await store.update_title(session_id, _expected_title)
                except Exception:
                    pass

            # session 轮转：当天执行次数超阈值则新建对话，避免高频任务会话无限膨胀
            _rotate_threshold = _gc().defaults.schedule_session_rotate_threshold
            if _rotate_threshold > 0:
                _today_runs = await store.count_today_runs(session_id)
                if _today_runs >= _rotate_threshold:
                    _new_session = await store.create(_gc().defaults.model, source="schedule", mode="")
                    _new_title = f"[定时] {title}" if title else "[定时] 未命名任务"
                    await store.update_title(_new_session.id, _new_title)
                    # 更新 job 关联的 session_id，后续触发走新 session
                    if job_id:
                        from ethan.scheduler.cron import get_scheduler as _get_sched
                        try:
                            _get_sched().modify_kwargs(job_id, session_id=_new_session.id)
                        except Exception:
                            _logger.warning("[Schedule] failed to update job session_id: job=%s", job_id, exc_info=True)
                    session_id = _new_session.id
                    set_session_id(session_id)
                    _logger.info("[Schedule] session rotated to %s (today_runs=%d >= threshold %d)",
                                 session_id, _today_runs, _rotate_threshold)

            # 保存 user message
            user_msg = Message(role="user", content=prompt)
            await store.save_message(session_id, user_msg)

            # 创建 agent（与普通对话路径一致）
            schedule_model = _gc().defaults.schedule_model or None
            agent = create_agent(schedule_model, channel="schedule", user_id=user_id)
            agent.session_id = session_id
            if agent.runtime_context:
                agent.runtime_context = agent.runtime_context + "\n\n" + schedule_ctx
            else:
                agent.runtime_context = schedule_ctx

            # 加载历史上下文（让重复执行的任务能看到之前的结果）
            from ethan.memory.working import WorkingMemory
            session_obj = await store.load(session_id)
            history = session_obj.messages if session_obj else []
            memory = WorkingMemory.from_history(history, hot_size=10)
            messages = memory.build_context() + [Message(role="user", content=prompt)]

            # 定时任务无人值守，自动批准所有工具
            consent = AutoConsentProvider(session_id=session_id)
            set_consent_provider(consent)

            # 流式执行 + 实时落库
            collector = StreamCollector().bind(agent)

            async for item in agent.stream_chat(messages):
                if isinstance(item, ToolEvent):
                    collector.feed(item)
                    if item.state != "start":
                        try:
                            progress_msg_id = await _save_progress(
                                store, session_id, progress_msg_id,
                                collector.tool_steps or [], collector.a2ui or None,
                                collector.mcp_apps or None,
                                collector.cards or None,
                            )
                        except Exception:
                            _logger.exception("定时任务实时保存工具进度失败 session=%s", session_id)
                else:
                    collector.feed(item)

            # 流结束：保存最终 assistant 消息（含完整 tool_steps）
            collector.flush_pending_injected()
            result_text = collector.full or ""

            if result_text or collector.tool_steps:
                asst_msg = Message(
                    role="assistant",
                    content=result_text,
                    thought=collector.thought,
                    usage=collector.usage_dict,
                    tool_steps=collector.tool_steps or [],
                    a2ui=collector.a2ui or None,
                    mcp_apps=collector.mcp_apps or None,
                    cards=collector.cards or None,
                    matched_skills=collector.matched_skills or None,
                    ttfb_ms=collector.ttfb_ms,
                    total_ms=collector.total_ms,
                    model=agent._provider.model,
                )
                if progress_msg_id:
                    await store.update_message(progress_msg_id, session_id, asst_msg)
                else:
                    await store.save_message(session_id, asst_msg)
                await store.touch(session_id)

            # 触发记忆沉淀：仅在 server loop 上 fire（_maybe_consolidate 内部用单例
            # store，fallback 临时 loop 上单例连接绑主 loop 会崩；且 asyncio.run()
            # 退出即关 loop → create_task 被取消，记忆沉淀静默丢失）。
            if not dedicated_store:
                from ethan.interface.routers.tasks import _maybe_consolidate
                asyncio.create_task(_maybe_consolidate(session_id, agent.model, user_id))
            else:
                _logger.warning("[Schedule] fallback thread: skip memory consolidation (cross-loop)")

        except Exception as e:
            import traceback
            _logger.error("Schedule fire error: %s\n%s", e, traceback.format_exc())
            result_text = f"⚠️ 定时任务执行失败: {e}"
            try:
                # dedicated 模式复用已开连接（若已建立）；server 模式取单例
                err_store = store if (store and dedicated_store) else await get_session_store()
                err_content = ""
                if collector and collector.full:
                    err_content = collector.full + "\n\n"
                err_content += f"⚠️ 定时任务后台执行失败:\n```text\n{e}\n```"
                err_msg = Message(
                    role="assistant",
                    content=err_content,
                    tool_steps=collector.tool_steps if collector else [],
                    model=agent._provider.model if agent else None,
                )
                if progress_msg_id:
                    await err_store.update_message(progress_msg_id, session_id, err_msg)
                else:
                    await err_store.save_message(session_id, err_msg)
                await err_store.touch(session_id)
            except Exception as e2:
                _logger.error("Failed to log schedule error to session: %s", e2)
        finally:
            if consent:
                consent.cancel_all()
            if store and dedicated_store:
                try:
                    await store.close()
                except Exception:
                    pass

        # 把结果发回来源渠道（飞书/微信）
        if result_text and _is_tool_result_noise(result_text):
            _logger.info("Schedule job '%s' result looks like tool noise, skipping send.", title)
            result_text = ""

        if result_text:
            display_title = title or _make_fallback_title(prompt)
            formatted = f"【定时任务】{display_title}\n{result_text}"

            if channel == "lark":
                try:
                    ctx = json.loads(channel_context)
                    chat_id = ctx.get("chat_id", "")
                    if chat_id:
                        from ethan.interface.lark_send import send_lark_notification
                        await send_lark_notification(chat_id, formatted)
                except Exception as e3:
                    _logger.error("Schedule lark reply error: %s", e3)

            elif channel == "wechat":
                try:
                    ctx = json.loads(channel_context)
                    to_user_id = ctx.get("to_user_id", "")
                    if to_user_id:

                        from ethan.interface.wechat_ilink import load_credentials, send_text
                        creds = load_credentials()
                        if creds:
                            async with _http_client() as client:
                                await send_text(client, creds, to_user_id, "", formatted)
                except Exception as e4:
                    _logger.error("Schedule wechat reply error: %s", e4)

    loop = _server_loop
    if loop and loop.is_running():
        _entry_logger.info("[Schedule] dispatching to server loop (loop=%s)", loop)
        fut = asyncio.run_coroutine_threadsafe(_run_schedule_task(), loop)
        def _on_done(f):
            exc = f.exception()
            if exc:
                _entry_logger.error("[Schedule] _run_schedule_task failed: %s", exc, exc_info=exc)
            else:
                _entry_logger.info("[Schedule] _run_schedule_task completed for session=%s", session_id)
        fut.add_done_callback(_on_done)
    else:
        _entry_logger.warning("[Schedule] no server loop (loop=%s), using thread fallback", loop)
        def _thread_run():
            asyncio.run(_run_schedule_task(dedicated_store=True))
        threading.Thread(target=_thread_run, daemon=True).start()

class ScheduleCreateTool(BaseTool):
    fast_path = False
    side_effect = True
    name = "schedule_create"
    description = "Create a scheduled task. Use for reminders, recurring checks, or timed automations. Cron expressions are interpreted in the user's local timezone."
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Unique job ID (e.g. 'morning-reminder')"},
            "title": {"type": "string", "description": "Short human-readable title for this task (e.g. '每日早报', 'Weekly report'). Shown in task list and notifications."},
            "prompt": {"type": "string", "description": "What to do when the task fires (a prompt or description)"},
            "cron": {"type": "string", "description": "Cron expression (5-part: min hour day month weekday). E.g. '0 9 * * *' for 9am daily. IMPORTANT: for weekday, always use names (mon-fri, sat, sun) not numbers — APScheduler's numeric weekday convention differs from standard cron (1-5 means Tue-Sat, not Mon-Fri)."},
            "interval_minutes": {"type": "integer", "description": "Alternative: run every N minutes."},
            "end_date": {"type": "string", "description": "Optional: date (YYYY-MM-DD) or datetime (YYYY-MM-DD HH:MM) when the job should stop firing. After this date the job is automatically removed."},
            "category": {"type": "string", "description": "Task category for UI grouping: 'one_off' (one-time reminder), 'recurring' (regular repeat), or 'timeline' (generated by task-and-schedule-manager timeline engine). Default 'one_off' for one-time tasks, 'recurring' for cron/interval."},
            "scene": {"type": "string", "description": "Scene/scope this task belongs to (e.g. 'work', 'life'). Tasks are isolated per scene for display and lifecycle. Default 'work'."},
        },
        "required": ["job_id", "prompt"],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, job_id: str, prompt: str, title: str = "", cron: str = "", interval_minutes: int = 0, end_date: str = "", category: str = "", scene: str = "") -> str:

        from ethan.core.config import get_config
        from ethan.memory.session import get_session_store

        if not cron and interval_minutes <= 0:
            return "Error: provide either 'cron' or 'interval_minutes'"

        # title 兜底：模型没给 title 时自动从 prompt 生成
        if not title:
            title = _make_fallback_title(prompt)

        # category 兜底：未显式指定时按 trigger 推断
        if not category:
            category = "recurring" if cron or interval_minutes > 0 else "one_off"

        # scene 兜底：默认 work
        if not scene:
            scene = "work"

        # 验证 end_date 格式（早于实际创建 session 前拦截，避免 job 创建成功但日期无效）
        if end_date and not any(_try_strptime(end_date, fmt) for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d")):
            return f"Error: invalid end_date '{end_date}'. Use YYYY-MM-DD or YYYY-MM-DD HH:MM format."

        # 读取当前请求上下文中的渠道信息
        chat_id = lark_chat_id_var.get("")
        wechat_id = wechat_chat_id_var.get("")
        if chat_id:
            channel = "lark"
            channel_context = json.dumps({"chat_id": chat_id})
        elif wechat_id:
            channel = "wechat"
            channel_context = json.dumps({"to_user_id": wechat_id})
        else:
            channel = "web"
            channel_context = "{}"

        # Create a dedicated session for this task (per-user).
        #
        # 注：把 create session 放在 /api/schedule 调用之后。之前在前面创建会
        # 导致 API 调用失败（500/400/422 等）时，会话库里留下一个"建了会话但
        # /api/schedule 实际没注册成功"的孤儿会话——标题是 [定时] xxx，里面
        # 一条消息都没有。
        store = await get_session_store()
        session = await store.create(get_config().defaults.model, source="schedule")
        try:
            await store.update_title(session.id, f"[定时] {title}")
        except Exception:
            # update_title 失败不会让整个任务失败
            pass

        # Send request to FastAPI backend
        token = get_config().network.auth_token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with _http_client() as client:
                res = await client.post(f"{_base_url()}/api/schedule", json={
                    "job_id": job_id,
                    "title": title,
                    "prompt": prompt,
                    "cron": cron,
                    "interval_minutes": interval_minutes,
                    "end_date": end_date,
                    "session_id": session.id,
                    "channel": channel,
                    "channel_context": channel_context,
                    "user_id": self._user_id,
                    "category": category,
                    "scene": scene,
                }, headers=headers)
                res.raise_for_status()
                msg = f"Scheduled '{job_id}' successfully."
                if end_date:
                    msg += f" Auto-expires on {end_date}."
                return msg + f" (Session: {session.id})"
        except Exception as e:
            # 失败时清理刚刚创建的孤儿会话（没写入任何消息），
            # 避免会话列表里出现空的 [定时] 项。
            try:
                existing = await store.load(session.id)
                if existing and len(getattr(existing, "messages", [])) == 0:
                    await store.delete(session.id)
            except Exception:
                pass
            return f"Failed to create job '{job_id}' via API: {e}"


class ScheduleListTool(BaseTool):
    fast_path = False
    name = "schedule_list"
    description = "List scheduled tasks, optionally filtered by scene or category."
    parameters = {
        "type": "object",
        "properties": {
            "scene": {"type": "string", "description": "Filter by scene (e.g. 'work', 'life'). Empty = all scenes."},
            "category": {"type": "string", "description": "Filter by category: 'one_off', 'recurring', or 'timeline'. Empty = all categories."},
        },
        "required": [],
    }

    async def run(self, scene: str = "", category: str = "") -> str:

        from ethan.core.config import get_config
        token = get_config().network.auth_token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with _http_client() as client:
                res = await client.get(f"{_base_url()}/api/schedule", headers=headers)
                res.raise_for_status()
                jobs = res.json().get("jobs", [])

            # 客户端筛选
            if scene:
                jobs = [j for j in jobs if (j.get("scene") or "work") == scene]
            if category:
                jobs = [j for j in jobs if (j.get("category") or "recurring") == category]

            if not jobs:
                hint_parts = []
                if scene:
                    hint_parts.append(f"scene='{scene}'")
                if category:
                    hint_parts.append(f"category='{category}'")
                hint = f" matching {', '.join(hint_parts)}" if hint_parts else ""
                return f"No scheduled tasks{hint}."

            lines = []
            for j in jobs:
                title = j.get("title", "") or j["id"]
                prompt = j.get("prompt", "")
                prompt_preview = (prompt[:80] + "…") if len(prompt) > 80 else prompt
                job_scene = j.get("scene", "work")
                job_cat = j.get("category", "recurring")
                line = f"- {j['id']}: {j['trigger']} (next: {j.get('next_run_time', 'None')}, status: {j.get('status', 'active')}, scene: {job_scene}, cat: {job_cat})"
                if title and title != j["id"]:
                    line += f"\n  title: {title}"
                if prompt_preview:
                    line += f"\n  prompt: {prompt_preview}"
                lines.append(line)
            return "\n".join(lines)
        except Exception as e:
            return f"Failed to list schedules: {e}"


class SchedulePauseTool(BaseTool):
    fast_path = False
    side_effect = True
    name = "schedule_pause"
    description = "Pause a scheduled task (stop firing, kept for future resume) or resume a paused one. Paused state persists across restarts."
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The job ID to pause/resume"},
            "state": {"type": "string", "enum": ["paused", "active"], "description": "'paused' to stop firing (task is kept, not deleted), 'active' to resume a paused task. Default 'paused'."},
        },
        "required": ["job_id"],
    }

    async def run(self, job_id: str, state: str = "paused") -> str:
        from ethan.core.config import get_config
        token = get_config().network.auth_token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with _http_client() as client:
                res = await client.patch(f"{_base_url()}/api/schedule/{job_id}", json={"state": state}, headers=headers)
                res.raise_for_status()
                return f"Job '{job_id}' is now {state}"
        except Exception as e:
            return f"Failed to update job '{job_id}' state to {state}: {e}"


class ScheduleRemoveTool(BaseTool):
    fast_path = False
    side_effect = True
    name = "schedule_remove"
    description = "Remove a scheduled task by its ID."
    parameters = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The job ID to remove"},
        },
        "required": ["job_id"],
    }

    async def run(self, job_id: str) -> str:

        from ethan.core.config import get_config
        token = get_config().network.auth_token
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with _http_client() as client:
                res = await client.delete(f"{_base_url()}/api/schedule/{job_id}", headers=headers)
                res.raise_for_status()
                return f"Removed '{job_id}'"
        except Exception as e:
            return f"Failed to remove job '{job_id}': {e}"
