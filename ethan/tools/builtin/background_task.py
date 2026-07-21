"""Background Task Tool — 即时长任务后台异步执行 + 完成回灌。

与 schedule（定时任务，未来某时刻触发）的区别：background_task 是「现在就发起、立刻
后台跑、不阻塞当前对话」。模型判断某个请求会跑很久（深度调研、批量处理、长网页操作等）
时主动调用，主对话立即返回「已在后台开始」，用户可继续聊别的；任务跑完结果回灌：
  - lark 渠道：把结果推回发起任务的那个 chat；
  - web 渠道：结果落在该任务的独立 session，侧边栏经 /poll 浮现。

实现：在 daemon 线程里对一个独立 session 发起 **streaming** /chat。走流式是为了让
RunManager 持有一个可停止的 run——终止功能（background_task_stop）即调 /chat/{id}/stop。
线程顺带 drain SSE：自动批准 consent（后台无 UI，发起即视为已授权）、累计正文、
结束后按渠道回灌并更新任务状态。

任务状态登记在模块级 _REGISTRY（本进程内）。后台任务是一次性的，进程重启即失效——
重启本就会杀掉 daemon 线程，无需持久化。
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field

from ethan.tools.base import BaseTool

# 发起任务时记录的飞书 chat_id（lark webhook 设置），用于完成后把结果推回原 chat。
lark_chat_id_var: ContextVar[str] = ContextVar("bg_lark_chat_id", default="")


def _base_url() -> str:
    """后台任务回调本机 server 的 base url。端口从 run_server 设置的环境变量读取，
    回退 8900——避免服务跑在非默认端口时后台任务连不上、静默失败。"""
    port = os.environ.get("ETHAN_SERVER_PORT", "8900")
    return f"http://127.0.0.1:{port}"


@dataclass
class _BgTask:
    session_id: str
    title: str
    started_at: float
    status: str = "running"   # running | done | error | stopped
    channel: str = "web"
    thread: threading.Thread | None = field(default=None, repr=False)


# session_id → _BgTask（本进程内的活跃/历史后台任务）
_REGISTRY: dict[str, _BgTask] = {}


def list_tasks() -> list[dict]:
    """序列化当前进程内的后台任务，供 API/任务中心轮询。按发起时间倒序。"""
    now = time.time()
    items = []
    for sid, t in _REGISTRY.items():
        items.append({
            "id": sid,
            "title": t.title,
            "status": t.status,
            "channel": t.channel,
            "started_at": t.started_at,
            "elapsed_seconds": int(now - t.started_at),
        })
    items.sort(key=lambda x: x["started_at"], reverse=True)
    return items


def stop_task(session_id: str, user_id: str = "") -> tuple[bool, str]:
    """终止后台任务（供 API 调用）。返回 (是否找到并处理, 提示文案)。"""
    task = _REGISTRY.get(session_id)
    if task is None:
        return False, "任务不存在"
    if task.status != "running":
        return False, f"任务当前状态为 {task.status}，无需终止"
    from ethan.core.run_manager import RunManager
    RunManager.instance().stop(session_id, user_id=user_id or None)
    task.status = "stopped"
    return True, "已终止"


def _auth_headers(user_id: str = "") -> dict:
    """取该用户的 web_token（落到其会话/记忆），无则回退全局 auth_token。"""
    from ethan.core.config import get_config
    token = ""
    if user_id:
        from ethan.core.users import get_user_store
        user = get_user_store().get_user(user_id)
        if user:
            token = user.web_token
    if not token:
        token = get_config().network.auth_token
    return {"Authorization": f"Bearer {token}"} if token else {}


def _run_background(task: _BgTask, prompt: str, channel: str, channel_context: str, user_id: str) -> None:
    """daemon 线程主体：流式跑任务、自动批准低风险 consent（高危挂起）、回灌结果、更新状态。"""
    import requests
    base = _base_url()
    headers = {**_auth_headers(user_id), "Content-Type": "application/json"}

    def _approve(request_id: str) -> None:
        try:
            requests.post(f"{base}/api/consent/{request_id}",
                          json={"allowed": True}, headers=headers, timeout=10)
        except Exception:
            pass

    def _deny(request_id: str) -> None:
        try:
            requests.post(f"{base}/api/consent/{request_id}",
                          json={"allowed": False}, headers=headers, timeout=10)
        except Exception:
            pass

    pending_high_risk: list[str] = []  # 后台中被拒的高危操作描述，回灌时提示用户
    result_text = ""
    try:
        body = {
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "session_id": task.session_id,
            "channel": "web",  # 后台始终走 web 流式管线（lark 回灌另行处理）
        }
        with requests.post(f"{base}/api/chat", json=body, headers=headers,
                           stream=True, timeout=3600) as res:
            res.raise_for_status()
            for raw in res.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data:"):
                    continue
                try:
                    evt = json.loads(raw[5:].strip())
                except Exception:
                    continue
                if evt.get("consent_request"):
                    rid = evt.get("request_id")
                    if rid:
                        # 高危调用（always=True，如 rm -rf）：后台无人确认，一律拒绝、记录，
                        # 回灌时提示用户去前台确认；低风险才自动批准。避免长任务里模型「自作主张」删东西。
                        if evt.get("always"):
                            desc = evt.get("description") or evt.get("tool") or "高风险操作"
                            pending_high_risk.append(desc)
                            threading.Thread(target=_deny, args=(rid,), daemon=True).start()
                        else:
                            threading.Thread(target=_approve, args=(rid,), daemon=True).start()
                elif "content" in evt:
                    result_text += evt["content"]
                elif evt.get("stopped"):
                    task.status = "stopped"
                elif evt.get("error"):
                    task.status = "error"
                    result_text += f"\n⚠️ {evt['error']}"
                elif evt.get("done"):
                    pass
        if task.status == "running":
            task.status = "done"
    except Exception as e:
        task.status = "error"
        result_text = result_text or f"⚠️ 后台任务执行失败: {e}"

    # 后台中被拦下的高危操作：回灌时明确提示用户去前台确认，避免「静默没做」
    if pending_high_risk:
        note = "\n\n⚠️ 以下高风险操作在后台被跳过（需你在前台确认后手动执行）：\n" + \
               "\n".join(f"- {d}" for d in pending_high_risk)
        result_text += note

    # lark 渠道：把最终结果推回发起任务的 chat
    if channel == "lark" and result_text.strip():
        try:
            ctx = json.loads(channel_context)
            chat_id = ctx.get("chat_id", "")
            if chat_id:
                import asyncio

                from ethan.interface.lark import _get_lark_client, _send_lark_reply
                client = _get_lark_client()
                if client:
                    prefix = f"【后台任务完成】{task.title}\n\n"
                    asyncio.run(_send_lark_reply(client, chat_id, prefix + result_text))
        except Exception:
            pass


class BackgroundTaskTool(BaseTool):
    fast_path = False
    side_effect = True
    name = "background_task"
    description = (
        "把一个会跑很久的任务丢到后台异步执行，不阻塞当前对话。"
        "适用：深度调研、批量处理、长网页自动化、多步骤长任务等预计耗时较久的活儿。"
        "调用后立即返回，任务在独立会话里后台跑；完成后结果会回灌（飞书推回当前会话，"
        "web 在侧边栏新会话里浮现）。不要用于能立刻答完的简单请求。"
        "可用 background_task_list 查看、background_task_stop 终止。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "任务简短标题（给用户看，如『调研 X 行业』）"},
            "prompt": {"type": "string", "description": "交给后台执行的完整任务描述（会作为新会话的首条用户消息）"},
        },
        "required": ["title", "prompt"],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, title: str, prompt: str) -> str:
        from ethan.core.config import get_config
        from ethan.memory.session import get_session_store

        chat_id = lark_chat_id_var.get("")
        channel = "lark" if chat_id else "web"
        channel_context = json.dumps({"chat_id": chat_id}) if chat_id else "{}"

        # 为该任务建一个独立 session（per-user），结果落在这里
        store = await get_session_store()
        session = await store.create(get_config().defaults.model)
        await store.update_title(session.id, f"[后台] {title}")
        # 首条用户消息入库，刷新后台会话能看到任务内容
        from ethan.providers.base import Message
        await store.save_message(session.id, Message(role="user", content=prompt))

        task = _BgTask(session_id=session.id, title=title, started_at=time.time(), channel=channel)
        t = threading.Thread(
            target=_run_background,
            args=(task, prompt, channel, channel_context, self._user_id),
            daemon=True,
        )
        task.thread = t
        _REGISTRY[session.id] = task
        t.start()

        return (
            f"已在后台开始：「{title}」。我会继续处理你的其它请求，"
            f"任务完成后结果会通知你。（任务 ID：{session.id}）"
        )


class BackgroundTaskListTool(BaseTool):
    fast_path = False
    name = "background_task_list"
    description = "列出本会话进程内的后台任务及其状态（running/done/error/stopped）。"
    parameters = {"type": "object", "properties": {}}

    async def run(self) -> str:
        if not _REGISTRY:
            return "当前没有后台任务。"
        lines = []
        now = time.time()
        for sid, t in _REGISTRY.items():
            mins = int((now - t.started_at) // 60)
            lines.append(f"- {t.title} [{t.status}] 已运行 {mins} 分钟（ID: {sid}）")
        return "后台任务：\n" + "\n".join(lines)


class BackgroundTaskStopTool(BaseTool):
    fast_path = False
    side_effect = True
    name = "background_task_stop"
    description = "终止一个正在运行的后台任务。需提供任务 ID（background_task 返回的或 list 里列出的）。"
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "要终止的后台任务 ID（即其 session_id）"},
        },
        "required": ["task_id"],
    }

    def __init__(self, user_id: str = ""):
        self._user_id = user_id

    async def run(self, task_id: str) -> str:
        task = _REGISTRY.get(task_id)
        if task is None:
            return f"没有找到后台任务 {task_id}。"
        if task.status != "running":
            return f"任务「{task.title}」当前状态为 {task.status}，无需终止。"
        # 复用 streaming 生成的停止语义：标记 stop_requested + 取消 producer，已生成部分会入库
        ok, _ = stop_task(task_id, user_id=self._user_id)
        if ok:
            return f"已终止后台任务「{task.title}」，已生成的部分内容已保存。"
        return f"后台任务「{task.title}」已标记终止（可能刚好已结束）。"
