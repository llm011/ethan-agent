"""Schedule Tool — 让 agent 通过 tool call 创建和管理定时任务。"""
import json
import os
import threading
from contextvars import ContextVar

import httpx

from ethan.tools.base import BaseTool

# 存储当前请求的飞书 chat_id，在 lark webhook 里设置，ScheduleCreateTool 里读取
lark_chat_id_var: ContextVar[str] = ContextVar("lark_chat_id", default="")
wechat_chat_id_var: ContextVar[str] = ContextVar("wechat_chat_id", default="")


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
    """
    def _do_fire():
        import requests

        from ethan.core.config import get_config
        result_text = ""
        try:
            # 用该 job 所属用户的 web_token 调 /chat（落到该用户的会话/记忆）
            token = ""
            if user_id:
                from ethan.core.users import get_user_store
                user = get_user_store().get_user(user_id)
                if user:
                    token = user.web_token
            if not token:
                token = get_config().network.auth_token
            headers = {"Authorization": f"Bearer {token}"} if token else {}

            # 按 channel 构造 runtime_context：lark/wechat 会自动回发结果，web 仅存会话
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
                # web channel：结果保存到会话，用户在 Web 界面查看；不会自动外发
                schedule_ctx = (
                    "【定时任务执行环境】你正在执行一个定时任务（cron job）。\n"
                    "任务完成后，你的回复将保存到会话记录中，用户可在 Web 界面的定时任务详情里查看。\n"
                    "直接输出任务结果文本即可，简洁明了。"
                )

            res = requests.post(f"{_base_url()}/api/chat", json={
                "messages": [{"role": "user", "content": prompt}],
                "session_id": session_id,
                "channel": "schedule",
                "runtime_context": schedule_ctx,
            }, headers=headers, timeout=300)
            res.raise_for_status()
            result_text = res.json().get("content", "")
        except Exception as e:
            import traceback
            print(f"Schedule fire error: {e}\n{traceback.format_exc()}")
            result_text = f"⚠️ 定时任务执行失败: {e}"
            import asyncio

            # 本路径跑在 daemon 线程的 asyncio.run() 临时 loop 里，
            # 而 get_session_store() 的 _session_store_lock 是绑定到主
            # server loop 的模块级 asyncio.Lock（非线程安全）。跨 loop
            # await 会触发 "got Future attached to a different loop"。
            # 这里像 core/heartbeat.py:_rotate_session_dbs 那样开独立
            # 连接写错误日志，绕开单例。
            from ethan.core.paths import user_sessions_db_path
            from ethan.memory.session import SessionStore
            from ethan.providers.base import Message
            async def log_error():
                store = SessionStore(db_path=user_sessions_db_path())
                await store.init()
                try:
                    err_msg = Message(role="assistant", content=f"⚠️ 定时任务后台执行失败:\n```text\n{e}\n```")  # noqa: F821 — closure over except-var
                    await store.save_message(session_id, err_msg)
                    await store.touch(session_id)
                finally:
                    await store.close()
            try:
                asyncio.run(log_error())
            except Exception as e2:
                print(f"Failed to log error to session: {e2}")

        # 把结果发回来源渠道（飞书/微信）
        # 防御性检查：过滤掉工具返回的噪音（如 agent 错误地把 lark-cli 的 JSON 结果当回复）
        if result_text and _is_tool_result_noise(result_text):
            print(f"Schedule job '{title}' result looks like tool noise, skipping send. Content preview: {result_text[:200]}")
            result_text = ""

        if result_text:
            display_title = title or _make_fallback_title(prompt)
            formatted = f"【定时任务】{display_title}\n{result_text}"

            if channel == "lark":
                try:
                    ctx = json.loads(channel_context)
                    chat_id = ctx.get("chat_id", "")
                    if chat_id:
                        import asyncio

                        from ethan.interface.lark import _get_lark_client, _send_lark_reply
                        client = _get_lark_client()
                        if client:
                            try:
                                asyncio.run(_send_lark_reply(client, chat_id, formatted))
                            except RuntimeError:
                                # 当前处于 event loop 内时降级：用 create_task 异步发送
                                loop = asyncio.get_running_loop()
                                loop.create_task(_send_lark_reply(client, chat_id, formatted))
                except Exception as e3:
                    print(f"Schedule lark reply error: {e3}")

            elif channel == "wechat":
                try:
                    ctx = json.loads(channel_context)
                    to_user_id = ctx.get("to_user_id", "")
                    if to_user_id:
                        import asyncio

                        from ethan.interface.wechat_ilink import load_credentials, send_text
                        creds = load_credentials()
                        if creds:
                            async def _send_wechat():
                                async with _http_client() as client:
                                    await send_text(client, creds, to_user_id, "", formatted)
                            try:
                                asyncio.run(_send_wechat())
                            except RuntimeError:
                                # 当前处于 event loop 内时降级：用 create_task 异步发送
                                loop = asyncio.get_running_loop()
                                loop.create_task(_send_wechat())
                except Exception as e4:
                    print(f"Schedule wechat reply error: {e4}")

    # Run in a separate thread so we don't block the APScheduler worker pool!
    threading.Thread(target=_do_fire, daemon=True).start()

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
            "category": {"type": "string", "description": "Task category for UI grouping: 'one_off' (one-time reminder), 'recurring' (regular repeat), or 'timeline' (generated by schedule-manager timeline engine). Default 'one_off' for one-time tasks, 'recurring' for cron/interval."},
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

        # Create a dedicated session for this task (per-user)
        store = await get_session_store()
        session = await store.create(get_config().defaults.model, source="schedule")
        await store.update_title(session.id, f"[定时] {title}")

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
