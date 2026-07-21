"""chat 路由：/health, /poll, /chat, /reconnect, /stop。"""
from __future__ import annotations

import asyncio
import ipaddress
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ethan import __version__
from ethan.memory.session import get_session_store
from ethan.providers.base import Message

from .deps import create_agent, verify_token
from .helpers import (
    _friendly_error,
    _setup_error_stream,
    _status_for_setup_error,
    _with_quote,
)
from .producers import _run_delegate_generation, _run_generation
from .schemas import ChatRequest, ChatResponse
from .sse import _sse_from_run

router = APIRouter()

logger = logging.getLogger(__name__)

# 本地/私有网络来源：auto_consent 仅允许来自这些地址的请求生效。
# 回环：直连宿主机（127.0.0.1）；私有网段：docker 网桥（172.16/12）、局域网（192.168/16、10/8）。
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

# 仅放行 RFC1918 三段，不用 ip.is_private（后者还含 CGNAT 100.64/10、链路本地 169.254/16 等）
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]


def _is_local(request: Request) -> bool:
    """请求是否来自本地回环或 RFC1918 私有网段。

    docker 部署下容器看到的 client.host 是网桥 IP（如 172.17.0.1），不是 127.0.0.1，
    单纯检查回环会误伤合法的本地访问。加入三段私有网段后，公网来源仍被挡住。
    用 TCP 直连地址（request.client.host），不信任 X-Forwarded-For —— 后者可被
    客户端伪造。client 为 None（异常情况）时按非本地处理（更安全）。
    """
    client = request.client
    if client is None:
        return False
    host = client.host
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or any(ip in net for net in _PRIVATE_NETWORKS)


# ── Health / Poll ────────────────────────────────────────────────


@router.get("/health")
async def health():
    # 前端用于存活检测 + 获取版本号 + agent_name（左上角标题）。
    # 无需 auth：前端在登录前也要能检测服务是否存活。
    from ethan.core.config import get_config
    cfg = get_config()
    return {
        "status": "ok",
        "version": __version__,
        "agent_name": cfg.defaults.agent_name or "Ethan",
    }


@router.get("/poll")
async def poll(hide_heartbeat: bool = False, hide_scheduled: bool = False,
               user_id: str = Depends(verify_token)):
    store = await get_session_store()
    exclude_prefixes = []
    if hide_heartbeat:
        exclude_prefixes.append("[心跳]")
    if hide_scheduled:
        exclude_prefixes.append("[定时]")
    sessions = await store.list_recent(50, exclude_title_prefixes=exclude_prefixes or None)
    return {
        "sessions": [
            {
                "id": s.id,
                "title": s.title,
                "model": s.model,
                "updated_at": s.updated_at,
                "source": getattr(s, "source", "web"),
                "mode": getattr(s, "mode", "") or "",
            }
            for s in sessions
        ]
    }


# ── Chat ─────────────────────────────────────────────────────────


@router.post("/chat")
async def chat(req: ChatRequest, request: Request, user_id: str = Depends(verify_token)):
    from ethan.core.context import set_session_id

    # 未传 session_id 时自动生成，确保所有对话都持久化到会话列表
    if not req.session_id:
        from ethan.memory.session import _generate_id
        req.session_id = _generate_id()

    set_session_id(req.session_id)  # browser 工具按对话隔离/授权

    # 请求建立阶段（建 agent / 开会话库 / 持久化用户消息 / 拼历史上下文）整体兜底。
    # 这段过去裸奔，任一步抛错都会冒泡成 FastAPI 默认 500，前端只显示生硬的
    # "Chat failed: 500"。首次使用时最容易在这里踩坑（如 ~/.ethan 目录/DB 初始化、
    # provider 未配置导致 create_agent 失败等）。这里统一转成友好错误：
    #   stream 模式 → 返回一个只含 error 事件的 SSE 流，前端按普通错误气泡渲染；
    #   非 stream 模式 → 返回带 friendly detail 的 500。
    try:
        agent = create_agent(req.model, channel=req.channel, user_id=user_id, mode=req.mode)
        messages = [
            Message(role=m["role"], content=m.get("content", ""), images=m.get("images") or [])
            for m in req.messages
        ]

        store = await get_session_store()

        if req.session_id:
            for m in messages[-1:]:
                if m.role == "user":
                    # 把引用信息附到消息上一起持久化，刷新后仍能渲染引用气泡
                    if req.quote and req.quote.get("content"):
                        m.quote = req.quote
                    await store.save_message(req.session_id, m)
            # /review 命令：立即从 URL 解析出 PR 标题并更新，不等 review 跑完
            user_text = (req.messages[-1].get("content", "") if req.messages else "").strip()
            if user_text:
                from ethan.memory.session import _review_title
                early_title = _review_title(user_text)
                if early_title:
                    await store.update_title(req.session_id, early_title)
            # 持久化对话模式：退出再进入保持当前模式
            if req.mode:
                await store.update_mode(req.session_id, req.mode)

        if req.session_id and not req.btw:
            from ethan.memory.working import WorkingMemory

            session = await store.load(req.session_id)
            history = session.messages if session else []

            # 长期记忆由 agent system prompt 的 <memory_context> 统一注入，
            # 这里只保留会话内 hot 滑窗，不再重复注入 cold facts 伪消息对
            memory = WorkingMemory.from_history(history, hot_size=10)

            current_user = _with_quote(messages[-1], req.quote)
            messages = memory.build_context() + [current_user]
        elif req.btw and messages:
            # /btw：只带本条消息，不带任何历史
            messages = [_with_quote(messages[-1], req.quote)]
        elif req.quote and messages and messages[-1].role == "user":
            messages[-1] = _with_quote(messages[-1], req.quote)
    except Exception as e:
        friendly = _friendly_error(e, None)
        logger.exception("chat 请求建立失败 session=%s: %s", req.session_id, e)
        if req.stream:
            return StreamingResponse(
                _setup_error_stream(friendly, req.session_id or ""),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        # 客户端类错误（配置缺失 / 参数非法）映射为 4xx，让 client 能精准区分，
        # 其余按 500 处理。
        raise HTTPException(status_code=_status_for_setup_error(e), detail=friendly)

    if req.stream:
        # (1) 沉浸式工具模式：会话 mode 解析出 delegate_agent 时，整条会话的每句话都
        #     直接续接该 coding agent（同一工具 session），不走 Ethan chat 模型。
        #     工作目录按会话隔离（~/.ethan/agent-sessions/<会话id>）。
        from ethan.core.modes import resolve_mode
        from ethan.core.paths import user_agent_session_dir
        from ethan.core.run_manager import RunManager
        _mode = resolve_mode(req.mode)
        if _mode.delegate_agent and req.session_id:
            import os as _os
            cwd = str(user_agent_session_dir(req.session_id))
            _os.makedirs(cwd, exist_ok=True)
            prompt = (req.messages[-1].get("content", "") if req.messages else "").strip()
            run = RunManager.instance().create(req.session_id, user_id=user_id)
            run.task = asyncio.create_task(
                _run_delegate_generation(run, prompt, _mode.delegate_agent, cwd,
                                         store, req.session_id, user_id)
            )
            return StreamingResponse(
                _sse_from_run(run),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # (2) 镜像会话续接：source=codex/claude/opencode 的临时委派会话，用户直接发消息
        #     时把消息当新 prompt 续接对应 coding agent（resume），过程实时推回该会话。
        from ethan.acp import get_mirror_info
        minfo = get_mirror_info(req.session_id or "", user_id=user_id)
        if minfo and req.session_id:
            prompt = (req.messages[-1].get("content", "") if req.messages else "").strip()
            run = RunManager.instance().create(req.session_id, user_id=user_id)
            run.task = asyncio.create_task(
                _run_delegate_generation(run, prompt, minfo["agent"], minfo["cwd"],
                                         store, req.session_id, user_id)
            )
            return StreamingResponse(
                _sse_from_run(run),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # (3) 普通 chat：生成与连接解耦——把 agent.stream_chat 放进后台 producer 任务，
        # 事件写入 ChatRun 缓冲并扇出给订阅者。SSE 响应只是一个订阅者，断开（刷新）只退订，
        # 不影响 producer——生成照常跑完并入库。刷新后可经 GET /chat/{id}/stream 重连回放。
        from ethan.core.consent import AutoConsentProvider, WebConsentProvider

        # 安全约束：auto_consent 会自动批准所有工具授权（含 shell 执行），相当于在
        # 用户主机上放开任意命令执行。绝不能单方面信任请求体里的 auto_consent 字段——
        # 否则 token 一旦泄露（XSS / 日志 / 配置文件），远程攻击者即可构造请求静默
        # 执行任意脚本（RCE）。因此强制限定：仅当请求来自本地回环或 RFC1918 私有网段
        # 时才允许生效，公网来源一律降级为 WebConsentProvider（逐项弹窗确认）。
        # 注：私有网段放行是为了支持 docker 部署（容器内看到的 client 是网桥 IP）。
        consent = None
        if req.auto_consent and _is_local(request):
            consent = AutoConsentProvider(session_id=req.session_id or "")
        else:
            consent = WebConsentProvider(session_id=req.session_id or "")
        manager = RunManager.instance()
        run = manager.create(req.session_id or "", consent=consent, user_id=user_id)
        run.task = asyncio.create_task(
            _run_generation(run, agent, messages, store, req.session_id, user_id, consent, mode=req.mode)
        )
        return StreamingResponse(
            _sse_from_run(run),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "X-Session-Id": req.session_id or "",
            },
        )

    response = await agent.chat(messages)

    if req.session_id:
        await store.save_message(req.session_id, response)
        await store.touch(req.session_id)

    # 浏览器 session 清理：关闭本次对话创建的所有 browser tab group
    from .producers import _close_browser_sessions
    await _close_browser_sessions(req.session_id)

    # 非流式路径也要触发记忆沉淀/技能生成，与 stream 分支(producers)行为对齐——
    # 否则走非流式 API 的客户端永远不会产生记忆和 episode。
    if req.session_id:
        from .tasks import _maybe_consolidate, _maybe_generate_skill
        asyncio.create_task(_maybe_consolidate(req.session_id, agent._provider.model, user_id, mode=req.mode))
        asyncio.create_task(_maybe_generate_skill(req.session_id, agent._provider.model, user_id))

    return ChatResponse(
        content=response.content,
        model=agent._provider.model,
        usage={
            "input": agent.usage.input_tokens,
            "output": agent.usage.output_tokens,
            "cache": agent.usage.cache_tokens,
        },
        session_id=req.session_id,
    )


@router.get("/chat/{session_id}/stream")
async def reconnect_stream(session_id: str, user_id: str = Depends(verify_token)):
    """重连一个仍在进行的生成：刷新页面后前端调此端点，回放缓冲 + 继续实时推送。

    无活跃 run（已结束或从未开始）返回 204，前端据此走普通 fetchSession 拿落库结果。
    传 user_id 校验会话归属——不属于当前用户的 session_id 一律当作不存在（204），
    防止任意已登录用户凭 session_id attach 到他人正在生成的实时流（IDOR）。
    """
    from fastapi import Response

    from ethan.core.run_manager import RunManager
    run = RunManager.instance().get(session_id, user_id=user_id)
    if run is None:
        return Response(status_code=204)
    return StreamingResponse(
        _sse_from_run(run),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/{session_id}/stop")
async def stop_generation(session_id: str, user_id: str = Depends(verify_token)):
    """停止某 session 进行中的生成。已生成的部分内容会被保存并标记 [已停止]。

    返回 {ok, stopped}：stopped=True 表示确实停了一个进行中的 run；
    False 表示没有进行中的 run（可能刚好结束）。user_id 校验归属，防跨用户停别人的任务。
    """
    from ethan.core.run_manager import RunManager
    stopped = RunManager.instance().stop(session_id, user_id=user_id)
    return {"ok": True, "stopped": stopped}
