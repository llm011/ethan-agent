"""chat 路由：/health, /poll, /chat, /reconnect, /stop。"""
from __future__ import annotations

import asyncio
import ipaddress
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ethan import __version__
from ethan.core.run_manager import RunManager
from ethan.memory.session import get_session_store
from ethan.providers.base import Message

from .deps import create_agent, verify_token
from .helpers import (
    _friendly_error,
    _persist_images_to_disk,
    _resolve_images_for_llm,
    _setup_error_stream,
    _status_for_setup_error,
    _with_quote,
)
from .producers import _run_delegate_generation, _run_generation
from .schemas import ChatRequest, ChatResponse, InjectRequest
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


async def _direct_stream(agent, messages: list, *,
                        save_user=None, save_assistant=None):
    """Direct LLM streaming: skip agent loop, no tools, no skills. Fastest path.

    save_user / save_assistant 可选：传入 coroutine 工厂（零参数返回 Awaitable）
    后会在首块前落用户消息、done 时落助手消息。给 direct=true + session_id 场景
    提供与正常 chat 一致的落库行为（会话列表能看到摘要/翻译的内容）。

    TODO(绕过抽象层): 这里直接访问 agent._provider 私有属性，跳过了 agent.stream_chat 包装的
    图片剥离、工具注入、指数退避错误重试等兜底。翻译/摘要场景不涉及多模态/重试故暂可接受；
    如后续 direct 也需要多模态或稳定重试，应改调用 agent 层公开方法。
    """
    import json

    if save_user:
        try:
            await save_user()
        except Exception as e:  # noqa: BLE001
            # 用户消息落库失败不该中断生成
            import logging as _log
            _log.getLogger(__name__).warning("direct save_user failed: %s", e)

    full = ""
    saw_error = False
    try:
        async for chunk in agent._provider.stream_chat(messages, tools=None, system=None):
            if chunk.content:
                full += chunk.content
                yield f"data: {json.dumps({'content': chunk.content})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"
    except Exception as e:
        saw_error = True
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

    if save_assistant and (not saw_error) and full:
        try:
            await save_assistant(full)
        except Exception as e:  # noqa: BLE001
            import logging as _log
            _log.getLogger(__name__).warning("direct save_assistant failed: %s", e)


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
    rm = RunManager.instance()
    return {
        "sessions": [
            {
                "id": s.id,
                "title": s.title,
                "model": s.model,
                "updated_at": s.updated_at,
                "source": getattr(s, "source", "web"),
                "mode": getattr(s, "mode", "") or "",
                "pinned_at": getattr(s, "pinned_at", 0) or 0,
            }
            for s in sessions
        ],
        "active_sessions": [s.id for s in sessions if rm.has_active(s.id, user_id)],
    }


# ── Chat ─────────────────────────────────────────────────────────


@router.post("/chat")
async def chat(req: ChatRequest, request: Request, user_id: str = Depends(verify_token)):
    from ethan.core.context import set_session_id

    # 未传 session_id 时自动生成，确保所有对话都持久化到会话列表
    if not req.session_id:
        from ethan.core.config import get_config as _get_config
        from ethan.memory.session import _generate_id
        req.session_id = _generate_id()
        # 立即在 DB 创建 session 记录，避免后续 save_message 外键约束失败
        store = await get_session_store()
        await store.create_with_id(req.session_id, req.model or _get_config().defaults.model,
                                   source=req.channel or "web", mode=req.mode or "")

    set_session_id(req.session_id)  # browser 工具按对话隔离/授权

    # 请求建立阶段（建 agent / 开会话库 / 持久化用户消息 / 拼历史上下文）整体兜底。
    # 这段过去裸奔，任一步抛错都会冒泡成 FastAPI 默认 500，前端只显示生硬的
    # "Chat failed: 500"。首次使用时最容易在这里踩坑（如 ~/.ethan 目录/DB 初始化、
    # provider 未配置导致 create_agent 失败等）。这里统一转成友好错误：
    #   stream 模式 → 返回一个只含 error 事件的 SSE 流，前端按普通错误气泡渲染；
    #   非 stream 模式 → 返回带 friendly detail 的 500。
    try:
        agent = create_agent(req.model, channel=req.channel, user_id=user_id, mode=req.mode)
        if req.session_id:
            agent.session_id = req.session_id
        if req.runtime_context:
            if agent.runtime_context:
                agent.runtime_context = agent.runtime_context + "\n\n" + req.runtime_context
            else:
                agent.runtime_context = req.runtime_context
        messages = [
            Message(
                role=m["role"],
                content=m.get("content", ""),
                images=m.get("images") or [],
                cards=m.get("cards"),
                quote=m.get("quote"),
            )
            for m in req.messages
        ]

        store = await get_session_store()

        if req.session_id:
            # 确保 session 记录存在（防止前端竞态或外部入口直接带 id 进来）
            existing = await store.load(req.session_id)
            if not existing:
                from ethan.core.config import get_config as _gc
                await store.create_with_id(req.session_id, req.model or _gc().defaults.model,
                                           source=req.channel or "web", mode=req.mode or "")
            session_obj = existing or await store.load(req.session_id)
            for m in messages[-1:]:
                if m.role == "user":
                    # 图片持久化到本地文件，DB 只存路径
                    if m.images:
                        _persist_images_to_disk(m, req.session_id)
                    # 把引用信息附到消息上一起持久化，刷新后仍能渲染引用气泡
                    if req.quote and req.quote.get("content"):
                        m.quote = req.quote
                    # save_message 持久化 path 格式图片（含切分分段）；
                    # 不再恢复原始 base64 —— 切分后的分段需原样流入 _resolve_images_for_llm
                    await store.save_message(req.session_id, m)
            # 首轮对话立即写标题：避免"新对话"残留很久，也避免前端本地 placeholderTitle
            # 被 3s 会话列表轮询覆盖回"新对话"。与 completions.py / repl_stream.py 初始化思路对齐。
            # 策略（仅首轮生效，且当前标题仍是默认"新对话"才写）：
            #   - /review 命令：从 URL 解析 "PR #xx owner/repo"，写标题。
            #   - 普通首条 query：内容量足够（≥10 中文等价字、或英文单词≥6）→ 立即用
            #     _auto_title（清洗 + 40 字截断）写 DB 标题，不等模型智能标题；
            #     若太短（你好/hi/测试）则保留"新对话"，等第二轮智能标题，避免把毫无
            #     信息的"你好"作为永久标题。
            #   - 只有纯图片等零文本场景才不写（保持"新对话"，等后续消息或模型标题）。
            user_text = (req.messages[-1].get("content", "") if req.messages else "").strip()
            early_title = None
            if user_text:
                from ethan.memory.session import _review_title
                early_title = _review_title(user_text)
            from ethan.memory.session import _PROTECTED_PREFIXES
            if (not any(getattr(session_obj, "title", "").startswith(p) for p in _PROTECTED_PREFIXES)) and (
                (not getattr(session_obj, "title", "")) or getattr(session_obj, "title", "") == "新对话"
            ):
                if early_title:
                    await store.update_title(req.session_id, early_title)
                elif user_text:
                    from ethan.memory.session import _auto_title, _count_content
                    # 阈值：中文等价字≥10 或 英文单词≥6 视为有信息量。
                    # 阈值为什么不是 3/4？因为用户明确反馈"先发了 query 很久标题还是新对话"，
                    # 说明用户不想等模型智能标题；但太短的问候语直接当标题又很丑（"你好"/"hi"），
                    # 所以只提前写"看起来能当标题"的长度。
                    cjk = len(__import__("re").findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', user_text))
                    non_cjk = __import__("re").sub(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', ' ', user_text)
                    en_words = len([w for w in non_cjk.split() if w and any(c.isalnum() for c in w)])
                    if cjk >= 10 or en_words >= 6 or _count_content(user_text) >= 10:
                        init = _auto_title([Message(role="user", content=user_text)])
                        if init and init != "新对话":
                            await store.update_title(req.session_id, init)
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
            # 历史消息中的图片从 {path} 格式解析为 {data} base64（LLM 需要）
            _resolve_images_for_llm(messages)
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
        # (0) Direct 模式：跳过 agent loop，直调 LLM 流式输出。
        #     适用于浏览器扩展的翻译、摘要等无需工具/技能的轻量请求。
        #     当请求带 session_id 时，消息要落库（会话列表里能看到），
        #     所以在 _direct_stream 里挂一对 save_user/save_assistant 回调。
        if req.direct:
            save_user_cb = None
            save_assistant_cb = None
            if req.session_id:
                _local_store = await get_session_store()
                _user_msgs = [
                    Message(role=m["role"], content=m.get("content", ""),
                            images=m.get("images") or [])
                    for m in req.messages if m.get("role") == "user"
                ]
                if _user_msgs:
                    async def _save_user():
                        s = _local_store
                        sid = req.session_id
                        for _m in _user_msgs:
                            if _m.images:
                                _persist_images_to_disk(_m, sid)
                            if req.quote and req.quote.get("content"):
                                _m.quote = req.quote
                            await s.save_message(sid, _m)
                    save_user_cb = _save_user
                async def _save_assistant(full_text: str):
                    s = _local_store
                    m = Message(role="assistant", content=full_text)
                    await s.save_message(req.session_id, m)
                    await s.touch(req.session_id)
                save_assistant_cb = _save_assistant
            return StreamingResponse(
                _direct_stream(agent, messages,
                               save_user=save_user_cb,
                               save_assistant=save_assistant_cb),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

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


@router.post("/chat/{session_id}/tool/{tool_call_id}/cancel")
async def cancel_tool(session_id: str, tool_call_id: str, user_id: str = Depends(verify_token)):
    """取消单个工具调用（不影响整轮生成）。

    被取消的工具结果回灌为「用户已取消」，由 LLM 决定下一步（重试/换工具/直接回答）。
    返回 {ok, cancelled}：cancelled=True 表示找到了正在执行的工具 task 并已取消。
    user_id 校验归属，防跨用户取消别人的工具。
    """
    from ethan.core.run_manager import RunManager
    cancelled = RunManager.instance().cancel_tool(session_id, tool_call_id, user_id=user_id)
    return {"ok": True, "cancelled": cancelled}


@router.post("/chat/{session_id}/inject")
async def inject_message(session_id: str, req: InjectRequest, user_id: str = Depends(verify_token)):
    """运行中向当前 session 的 Agent 上下文「补充信息」。

    信息会塞入 ChatRun 的 inbox，agent loop 下一轮调模型前会 append 到 working 末尾
    （即 prompt 结尾处），以 `[用户运行中补充]：...` 形式呈现给模型。
    仅当该 session 有活跃 run（未 done）时生效；run 已结束返回 409。
    user_id 校验归属，防跨用户注入。
    """
    from ethan.core.run_manager import RunManager
    run = RunManager.instance().get(session_id, user_id=user_id)
    if run is None or run.done:
        raise HTTPException(status_code=409, detail="当前没有进行中的任务，无法补充信息")
    content = (req.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="补充信息不能为空")
    run.inject(content)
    return {"ok": True, "queued": True}


@router.post("/chat/{session_id}/resume/{message_id}")
async def resume_from_message(session_id: str, message_id: int, request: Request,
                              user_id: str = Depends(verify_token)):
    """从一条中断的消息继续执行。

    读取该消息的过程记录（intermediate blob 或从 tool_steps 重建），构造续接 prompt，
    把原消息标记为 completed，然后走正常 chat 流程。前端点击「继续」按钮时调用。
    """
    store = await get_session_store()
    session = await store.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    target = None
    for m in session.messages:
        if getattr(m, "id", None) == message_id:
            target = m
            break
    if not target:
        raise HTTPException(status_code=404, detail="Message not found in this session")

    # 原子 CAS：仅当状态仍为 interrupted 时才标记为 completed，防止并发重复触发
    claimed = await store.update_message_status(message_id, "completed", expected="interrupted")
    if not claimed:
        raise HTTPException(status_code=409, detail="该消息已不处于中断状态，可能已被其他请求处理")

    # 读取过程记录
    process_md = ""
    blob = await store.load_intermediate_blob(message_id)
    if blob and not blob.get("missing"):
        process_md = blob.get("content", "")
    elif target.tool_steps:
        from ethan.memory.session import _build_intermediate_markdown
        process_md = _build_intermediate_markdown(target)

    resume_context = (
        "上面的任务因服务重启而中断。以下是中断前已完成的进度记录：\n\n"
        + (process_md or "（无过程记录）")
        + "\n\n请基于以上进度继续完成任务。注意：进度记录是工具调用的摘要，"
        "可能缺少部分细节，请根据情况判断是否需要重新执行某些步骤。"
    )

    # 用 runtime_context 传递续跑上下文，避免污染用户消息历史
    req = ChatRequest(
        messages=[{"role": "user", "content": "继续执行"}],
        session_id=session_id,
        stream=True,
        channel="web",
        mode=session.mode,
        auto_consent=_is_local(request),
        runtime_context=resume_context,
    )
    try:
        return await chat(req, request, user_id)
    except Exception:
        # chat 失败时回滚状态，让用户可以重试
        await store.update_message_status(message_id, "interrupted")
        raise
