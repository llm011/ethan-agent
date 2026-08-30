"""Producer tasks: background generation functions that emit events into a ChatRun."""

from __future__ import annotations

import asyncio
import logging

from ethan.memory.session import SessionStore, get_session_store, retry_on_db_locked
from ethan.providers.base import Message

from .helpers import _friendly_error
from .tasks import _maybe_consolidate, _maybe_generate_skill, _maybe_regen_title

logger = logging.getLogger(__name__)


def _RunManager_schedule_removal(session_id: str) -> None:
    from ethan.core.run_manager import RunManager

    RunManager.instance().schedule_removal(session_id)


async def _save_progress(
    store: SessionStore,
    session_id: str,
    progress_msg_id: int | None,
    tool_steps: list,
    a2ui: list | None,
    mcp_apps: list | None = None,
    cards: list | None = None,
) -> int:
    """工具过程实时落库：把当前 tool_steps 快照写进一条 assistant 消息。

    首次（progress_msg_id is None）：INSERT 一条占位行（content 空、tool_steps 为当前步骤），
    返回新行 id；后续：UPDATE 同一行覆盖 tool_steps/a2ui/mcp_apps/cards，复用 id 返回。

    这样整轮只占一条 assistant 行，工具步骤随完成实时留存，进程崩溃/用户关页面也不丢过程。
    """
    msg = Message(
        role="assistant",
        content="",
        tool_steps=tool_steps,
        a2ui=a2ui,
        mcp_apps=mcp_apps,
        cards=cards,
        status="running",
    )
    if progress_msg_id is None:
        return await store.save_message(session_id, msg)
    await store.update_message(progress_msg_id, session_id, msg)
    return progress_msg_id


async def _close_browser_sessions(session_id: str | None, run=None) -> None:
    """清理当前 ethan 会话创建的所有 browser session（tab group）。

    对话结束后调用。keep_alive 的 session 直接 release（保留 tab）。
    其余 session 弹卡片让用户确认是「关闭」还是「保留」，超时默认保留。
    """
    if not session_id:
        return
    try:
        from ethan.browser.hub import get_hub
        from ethan.browser.protocol import METHODS
        from ethan.browser.session_map import get_session_map

        smap = get_session_map()
        hub = get_hub()
        if not hub.connected:
            return

        bsids = smap.list_for(session_id)
        if not bsids:
            return

        # keep_alive 的直接 release，不弹卡片
        to_confirm: list[dict] = []
        for bsid in bsids:
            client_name = smap.get_client(bsid)
            if not client_name:
                smap.unbind(bsid)
                continue
            if smap.is_keep_alive(bsid):
                try:
                    await hub.call(
                        METHODS["session_release"],
                        {"sessionId": bsid},
                        client_name=client_name,
                        browser_session_id=bsid,
                    )
                except Exception:
                    logger.warning("browser: release keep_alive session failed for %s", bsid)
                finally:
                    smap.unbind(bsid)
            else:
                to_confirm.append({"sessionId": bsid, "title": "", "tabCount": 0, "_client": client_name})

        if not to_confirm:
            return

        # 弹卡片让用户确认
        from ethan.browser.cleanup_confirm import TIMEOUT_SECONDS, await_confirm, create_confirm

        # 尝试获取 session 标题信息（用第一个 client 查询即可）
        try:
            first_client = to_confirm[0]["_client"]
            list_result = await hub.call(METHODS["session_list"], {}, client_name=first_client)
            sessions_info = {
                s.get("sessionId"): s for s in (list_result or {}).get("sessions", []) if isinstance(s, dict)
            }
            for item in to_confirm:
                info = sessions_info.get(item["sessionId"])
                if info:
                    item["title"] = info.get("title", "")
                    item["tabCount"] = info.get("tabCount", 0)
        except Exception:
            pass

        confirm_req = create_confirm(session_id, to_confirm)
        if run is not None:
            run.emit(
                {
                    "confirm_browser_cleanup": True,
                    "request_id": confirm_req.request_id,
                    "sessions": [
                        {"sessionId": s["sessionId"], "title": s["title"], "tabCount": s["tabCount"]}
                        for s in to_confirm
                    ],
                    "timeout": TIMEOUT_SECONDS,
                }
            )

        action = await await_confirm(confirm_req)

        # 根据用户选择执行
        for item in to_confirm:
            bsid = item["sessionId"]
            cname = item.get("_client", "")
            if not cname:
                smap.unbind(bsid)
                continue
            try:
                if action == "close":
                    await hub.call(
                        METHODS["session_close"], {"sessionId": bsid}, client_name=cname, browser_session_id=bsid
                    )
                # "keep" 只解绑后端映射，不调 session_release：
                # 扩展继续追踪该 session，下次对话可通过 list + attach 复用。
            except Exception:
                logger.warning("browser: cleanup action '%s' failed for %s", action, bsid)
            finally:
                smap.unbind(bsid)
    except Exception:
        logger.debug("browser cleanup skipped: %s", session_id)


async def _run_delegate_generation(
    run,
    prompt: str,
    agent_name: str,
    cwd: str,
    store: SessionStore,
    session_id: str,
    user_id: str = "",
) -> None:
    """Producer：在镜像会话里直接发消息时，把消息当新 prompt 续接对应 coding agent。

    走 acp.delegate(prefer=agent, resume=True)，过程中的 step/text 经 on_event 实时
    emit 进这条会话的 ChatRun；结束后把回复+步骤落成 assistant 消息。
    mirror=False：避免 delegate 内部再为同一 session 注册一个 ChatRun（双 writer）。
    """
    import os as _os

    from ethan.acp import delegate

    emitted_text = False

    def _emit(etype, data):
        nonlocal emitted_text
        if etype == "text":
            emitted_text = True
            run.emit({"content": data})
        elif etype == "step" and isinstance(data, dict):
            run.emit(
                {
                    "tool": data.get("tool", ""),
                    "args": data.get("args", ""),
                    "state": data.get("state", "done"),
                    "id": f"mirror-{id(data)}",
                    "duration_ms": data.get("duration_ms"),
                    "result_preview": data.get("result_preview", ""),
                }
            )

    # cwd 可能已被删除（临时目录、项目移动等）。提前给出清晰提示，
    # 避免 codex/claude 子进程抛出晦涩的 "[Errno 2] No such file or directory"。
    if not cwd or not _os.path.isdir(cwd):
        msg = f"该会话对应的工作目录已不存在：{cwd or '(空)'}\n无法继续在此目录续接 {agent_name}。"
        run.emit({"content": msg})
        try:
            await store.save_message(session_id, Message(role="assistant", content=msg))
            await store.touch(session_id)
        except Exception:
            pass
        run.emit({"done": True, "usage": {}})
        run.finish()
        _RunManager_schedule_removal(run.session_id)
        return

    result = None
    try:
        result = await delegate(
            prompt=prompt,
            cwd=cwd,
            prefer=agent_name,
            timeout=240,
            resume=True,
            user_id=user_id,
            mirror=False,
            on_event=_emit,
        )
    except asyncio.CancelledError:
        run.emit({"stopped": True, "usage": {}})
        run.finish()
        _RunManager_schedule_removal(run.session_id)
        raise
    except Exception as e:
        err_text = _friendly_error(e, None)
        if err_text:
            run.emit({"error": err_text})
        else:
            logger.warning("Suppressed transient error in delegate: %s", e)

    try:
        if result is not None:
            content = result.output or ("(委派失败，无输出)" if not result.success else "(无输出)")
            # 子进程层失败时 on_event 不会触发，没有任何 text 推过；
            # 把最终结果作为 content 补推一次，避免 live 流空返回（刷新才看到）。
            if not emitted_text:
                run.emit({"content": content})
            await store.save_message(
                session_id,
                Message(
                    role="assistant",
                    content=content,
                    tool_steps=result.sub_steps or [],
                ),
            )
            await store.touch(session_id)
    except Exception:
        logger.exception("保存委派续接结果失败 session=%s", session_id)

    run.emit({"done": True, "usage": {}})
    run.finish()
    _RunManager_schedule_removal(run.session_id)


async def _run_generation(
    run,
    agent,
    messages: list[Message],
    store: SessionStore,
    session_id: str | None,
    user_id: str = "",
    consent=None,
    mode: str = "",
) -> None:
    """Producer：后台任务跑 Agent 生成，把事件 emit 进 run 缓冲并扇出给订阅者。

    与 HTTP 连接解耦——订阅者（SSE 响应）断开不会取消本任务，生成照常跑完并入库。
    所有原先 `yield` 的地方改为 `run.emit(...)`。
    """
    from ethan.core.ask_user import AskUserEvent
    from ethan.core.consent import ConsentEvent, set_consent_provider
    from ethan.core.stream_collector import StreamCollector
    from ethan.core.wait_for_user import WaitForUserEvent
    from ethan.providers.base import InjectEvent, SkillsMatchedEvent, ThinkingEvent, ToolEvent

    if session_id:
        agent.session_id = session_id
    # 关联 ChatRun 到 ToolExecutor：使外部可通过 run.cancel_tool(tool_call_id) 取消单个工具。
    agent._executor.current_run = run

    # consent provider 经 ContextVar 注入；本任务有独立 context，需在任务内设置。
    set_consent_provider(consent)
    # 「运行中补充信息」drainer 也经 ContextVar 注入：agent loop 每轮开头调它取走 inbox 内容。
    from ethan.core.context import set_inject_drainer

    set_inject_drainer(run.drain_injected)

    # 模型在回复一开始就已确定（agent 创建时即绑定 provider.model），尽早 emit 给前端，
    # 让气泡底部「开始时间」旁立即显示所用模型，而不是等到 done 事件才出现。
    # 前端会在收到该事件时把 model 写进当前 assistant 气泡并即时重渲染。
    try:
        run.emit({"model": agent._provider.model})
    except Exception:
        logger.debug("emit model event failed session=%s", session_id, exc_info=True)

    # 恢复 DB 中遗留的未消费「补充信息」：正常结束/停止会在 finally 清空镜像，
    # 这里只会在进程崩溃/重启残留时读到非空，交给本轮 agent loop 消费，避免用户补充静默丢失。
    if session_id:
        try:
            leftover = await retry_on_db_locked(store.load_pending_injected, session_id)
            if leftover:
                run.injected_messages.extend(leftover)
                logger.info("恢复 %d 条遗留补充信息进新 run session=%s", len(leftover), session_id)
        except Exception:
            logger.debug("恢复遗留补充信息失败 session=%s", session_id, exc_info=True)

    collector = StreamCollector().bind(agent)
    # 工具过程实时持久化：每条工具事件 emit 给前端的同时，也把步骤快照落库。
    # 这样即便后续 finalize 失败 / 进程崩溃 / 用户关页面，工具调用过程也留存，不会白干。
    # 落的是一条 role=assistant、content 为占位、tool_steps 为当前全部步骤的「进度消息」，
    # id 记在 progress_msg_id；每完成一个工具就 UPDATE 这条（覆盖式更新 tool_steps），
    # 流结束后把同一条更新为最终内容（content/usage/a2ui），避免「占位行 + 最终行」重复两条。
    progress_msg_id: int | None = None
    try:
        async for item in agent.stream_chat(messages):
            if isinstance(item, ConsentEvent):
                run.interaction_ids.add(item.request_id)
                evt = {
                    "consent_request": True,
                    "request_id": item.request_id,
                    "tool": item.tool,
                    "description": item.description,
                    "detail": item.detail,
                    "always": item.always,
                }
                run.emit(evt)
                # 同步广播给所有连接的浏览器扩展，让扩展发系统通知兜底，
                # 避免用户只开着浏览器没看聊天页面时错过授权。
                try:
                    from ethan.browser.hub import get_hub

                    hub = get_hub()
                    if hub.connected:
                        await hub.broadcast_notification(
                            "notify:consent_request",
                            {
                                "request_id": item.request_id,
                                "session_id": session_id or "",
                                "tool": item.tool,
                                "description": item.description,
                                "detail": item.detail,
                                "always": bool(item.always),
                                "server_url": "",  # 扩展侧自己从 storage 取 serverUrl 再转 http
                            },
                        )
                except Exception:
                    logger.exception("向浏览器扩展广播 consent 通知失败")
            elif isinstance(item, AskUserEvent):
                run.interaction_ids.add(item.request_id)
                run.emit(
                    {
                        "ask_user_request": True,
                        "request_id": item.request_id,
                        "question": item.question,
                        "options": item.options,
                        "default": item.default,
                        "timeout": item.timeout,
                    }
                )
            elif isinstance(item, WaitForUserEvent):
                run.interaction_ids.add(item.request_id)
                run.emit(
                    {
                        "wait_for_user_request": True,
                        "request_id": item.request_id,
                        "prompt": item.prompt,
                        "input_type": item.input_type,
                        "placeholder": item.placeholder,
                        "confirm_label": item.confirm_label,
                        "cancel_label": item.cancel_label,
                        "timeout": item.timeout,
                    }
                )
            elif isinstance(item, SkillsMatchedEvent):
                collector.feed(item)
                run.emit({"skills_matched": item.skills})
            elif isinstance(item, ThinkingEvent):
                run.emit({"thinking": True})
            elif isinstance(item, InjectEvent):
                collector.feed(item)
                run.emit({"injected": item.messages})
                # 已被模型消费：同步 DB 镜像（run.injected_messages 此刻为消费后剩余，
                # 通常是空；消费期间新注入的会保留）。
                if session_id:
                    try:
                        await retry_on_db_locked(
                            store.save_pending_injected, session_id, list(run.injected_messages)
                        )
                    except Exception:
                        logger.debug("同步补充信息消费失败 session=%s", session_id, exc_info=True)
            elif isinstance(item, ToolEvent):
                collector.feed(item)
                if item.state == "start":
                    step = collector.tool_steps[-1] if collector.tool_steps else {}
                    run.emit(
                        {
                            "tool": item.tool_name,
                            "args": item.args_summary,
                            "state": "start",
                            "id": item.tool_call_id,
                            "intent": item.intent or "",
                            "entity_type": item.entity_type or "",
                            "entity_id": item.entity_id or "",
                            "injected": step.get("injected", []),
                        }
                    )
                else:
                    step = collector.tool_steps[-1] if collector.tool_steps else {}
                    evt = {
                        "tool": item.tool_name,
                        "args": item.args_summary,
                        "state": item.state,
                        "id": item.tool_call_id,
                        "duration_ms": step.get("duration_ms"),
                        "result_preview": item.result_preview or "",
                        "result_detail": item.result_detail or "",
                        "sub_steps": item.sub_steps or [],
                        "entity_type": item.entity_type or "",
                        "entity_id": item.entity_id or "",
                    }
                    if item.ui:
                        evt["ui"] = item.ui
                    if item.mcp_app:
                        evt["mcp_app"] = item.mcp_app
                    if item.cards:
                        evt["cards"] = item.cards
                    if item.cards_meta:
                        evt["cards_meta"] = item.cards_meta
                    run.emit(evt)
                # 工具事件（start/done/error）后实时落库进度：把当前全部 tool_steps
                # 写到这条进度消息上。首次创建，后续 UPDATE 同一条（progress_msg_id 复用）。
                if session_id and consent is not None:
                    try:
                        progress_msg_id = await _save_progress(
                            store,
                            session_id,
                            progress_msg_id,
                            collector.tool_steps or [],
                            collector.a2ui or None,
                            collector.mcp_apps or None,
                            collector.cards or None,
                        )
                    except Exception:
                        logger.exception("实时保存工具进度失败 session=%s", session_id)
            else:
                collector.feed(item)
                run.emit({"content": item})
    except asyncio.CancelledError:
        # 被取消有两种情形：
        # (1) 用户主动 /stop（run.stop_requested=True）：保存已生成的部分内容，标记 [已停止]
        # (2) 新 run 替换旧 run：直接丢弃，不入库
        if consent is not None:
            consent.cancel_all()
        # 进度占位行：用户主动停止则就地更新成最终内容（含 tool_steps）+ [已停止] 标记，
        # 复用同一行；新 run 替换则删除占位行，不残留空壳。
        for step in collector.tool_steps or []:
            if step.get("state") == "running":
                step["state"] = "cancelled"
        if progress_msg_id and session_id:
            try:
                if getattr(run, "stop_requested", False):
                    stopped_content = (collector.full or "") + "\n\n_（已停止）_"
                    await store.update_message(
                        progress_msg_id,
                        session_id,
                        Message(
                            role="assistant",
                            content=stopped_content,
                            thought=collector.thought,
                            reasoning=collector.reasoning,
                            usage=collector.usage_dict,
                            tool_steps=collector.tool_steps or [],
                            a2ui=collector.a2ui or None,
                            mcp_apps=collector.mcp_apps or None,
                            cards=collector.cards or None,
                            matched_skills=collector.matched_skills or None,
                            ttfb_ms=collector.ttfb_ms,
                            total_ms=collector.total_ms,
                            status="stopped",
                            model=agent._provider.model,
                        ),
                    )
                    await store.touch(session_id)
                else:
                    await store.delete_message_by_id(progress_msg_id)
            except Exception:
                logger.exception("清理/定稿进度占位行失败 session=%s row=%s", session_id, progress_msg_id)
        elif getattr(run, "stop_requested", False) and session_id and (collector.full or collector.thought):
            # 没走过实时落库（如非 web 渠道）的兜底：直接新建一条
            try:
                stopped_msg = Message(
                    role="assistant",
                    content=(collector.full or "") + "\n\n_（已停止）_",
                    thought=collector.thought,
                    reasoning=collector.reasoning,
                    usage=collector.usage_dict,
                    tool_steps=collector.tool_steps or [],
                    a2ui=collector.a2ui or None,
                    mcp_apps=collector.mcp_apps or None,
                    cards=collector.cards or None,
                    matched_skills=collector.matched_skills or None,
                    ttfb_ms=collector.ttfb_ms,
                    total_ms=collector.total_ms,
                    status="stopped",
                    model=agent._provider.model,
                )
                await store.save_message(session_id, stopped_msg)
                await store.touch(session_id)
            except Exception:
                logger.exception("保存已停止生成的部分内容失败 session=%s", session_id)
        # 被 stop/watchdog cancel 时也尝试生成标题（新会话第一轮就被 cancel 则没有标题）
        stopped_title = None
        if session_id and getattr(run, "stop_requested", False):
            try:
                stopped_title = await _maybe_regen_title(session_id)
            except Exception:
                pass
        stopped_evt: dict = {"stopped": True, "usage": collector.usage_dict}
        if stopped_title:
            stopped_evt["title"] = stopped_title
        run.emit(stopped_evt)
        run.finish()
        _RunManager_schedule_removal(run.session_id)
        raise
    except Exception as e:
        logger.exception("Generation failed session=%s", session_id)
        err_text = _friendly_error(e, agent)
        if not err_text:
            # transient DB error (e.g. locked) — suppress, task already done
            logger.warning("Suppressed transient error in generation: %s", e)
            # 进度占位行可能还停在 running 态（本次异常没人定稿它），标记
            # interrupted，否则刷新后 UI 会无限转圈
            if progress_msg_id:
                try:
                    await retry_on_db_locked(store.update_message_status, progress_msg_id, "interrupted", "running")
                except Exception:
                    logger.exception("标记进度行 interrupted 失败 session=%s row=%s", session_id, progress_msg_id)
            run.emit({"done": True, "usage": collector.usage_dict})
            run.finish()
            _RunManager_schedule_removal(run.session_id)
            return
        run.emit({"error": err_text})
        # 异常中断：把错误信息持久化，保证刷新后用户仍能看到出了什么问题。
        # 已有进度行（有 tool_steps）则 UPDATE；否则新建一条 assistant 消息。
        # 两种情形都覆盖：(1) 工具调用中途报错 (2) provider 直接失败、无任何工具步骤。
        if session_id:
            error_content = (collector.full + "\n\n" if collector.full else "") + err_text
            err_msg = Message(
                role="assistant",
                content=error_content,
                thought=collector.thought,
                reasoning=collector.reasoning,
                usage=collector.usage_dict,
                tool_steps=collector.tool_steps or [],
                a2ui=collector.a2ui or None,
                mcp_apps=collector.mcp_apps or None,
                cards=collector.cards or None,
                matched_skills=collector.matched_skills or None,
                ttfb_ms=collector.ttfb_ms,
                total_ms=collector.total_ms,
                status="interrupted",
                model=agent._provider.model,
            )
            try:
                if progress_msg_id:
                    await store.update_message(progress_msg_id, session_id, err_msg)
                else:
                    await store.save_message(session_id, err_msg)
                await store.touch(session_id)
            except Exception:
                logger.exception("保存错误消息失败 session=%s", session_id)
        run.emit({"done": True, "usage": collector.usage_dict})
        run.finish()
        _RunManager_schedule_removal(run.session_id)
        return
    finally:
        # 流结束（正常/异常）时取消未决授权 Future，避免泄漏
        if consent is not None:
            consent.cancel_all()
        # ask_user / wait_for_user 的 Provider 在 agent loop 内局部创建，
        # producer 结束（stop/替换/异常）时按本 run 记录的 request_id 精确清理，
        # 避免未决 Future 泄漏到超时；不做全量清理，防止误杀其他并发 run 的等待。
        from ethan.core.ask_user import _REGISTRY as _ASK_REGISTRY
        from ethan.core.wait_for_user import _REGISTRY as _WFU_REGISTRY

        for req_id in run.interaction_ids:
            for registry in (_ASK_REGISTRY, _WFU_REGISTRY):
                provider = registry.get(req_id)
                if provider is not None:
                    provider.cancel(req_id)
        run.interaction_ids.clear()
        # run 结束（正常/停止/替换/异常）：清空 DB 中的「补充信息」待消费镜像。
        # 已消费的留在工具时间线的 injected 信息里；未消费的随 run 结束丢弃，不再展示。
        if session_id:
            try:
                await retry_on_db_locked(store.save_pending_injected, session_id, [])
            except Exception:
                logger.debug("清空补充信息镜像失败 session=%s", session_id, exc_info=True)
        # 浏览器 session 清理移至 done 事件之前（见下方），
        # 因为 finally 在 stop/error 路径已 run.finish() 之后才执行，
        # 此时 SSE 连接已断，无法送达 confirm 卡片。

    usage_dict = collector.usage_dict

    # inject 之后模型只回文本、没再调工具时，补充信息仍留在 _pending_injected 里，
    # 挂到最后一个工具步骤上一并持久化，避免静默丢失。
    collector.flush_pending_injected()

    # 兜底：agent 忘了调 deliver_file、直接把产物绝对路径写进正文时，扫正文补文件卡片。
    # 补进 cards 列 = 同时补下载授权（/files 路由授权源自持久化的 cards），卡片才点得动。
    final_cards = list(collector.cards or [])
    try:
        from ethan.core.file_jail import scan_file_cards_in_text

        existing_paths = {c.get("path") for c in final_cards if c.get("type") == "file"}
        fallback_cards = scan_file_cards_in_text(collector.full or "", existing_paths)
        if fallback_cards:
            final_cards.extend(fallback_cards)
            logger.info("正文兜底补文件卡片 %d 张 session=%s", len(fallback_cards), session_id)
            # 直播中也推给前端，让当前这轮就渲染出卡片（否则要刷新会话才出现）
            try:
                run.emit({"cards": fallback_cards})
            except Exception:
                logger.debug("兜底文件卡片 emit 失败 session=%s", session_id, exc_info=True)
    except Exception:
        logger.exception("正文兜底扫描文件卡片失败 session=%s", session_id)

    msg_id = None
    if session_id and (collector.full or collector.thought):
        asst_msg = Message(
            role="assistant",
            content=collector.full,
            thought=collector.thought,
            reasoning=collector.reasoning,  # DeepSeek/Anthropic reasoning 模型续轮回传用
            usage=usage_dict,
            tool_steps=collector.tool_steps or [],
            a2ui=collector.a2ui or None,
            mcp_apps=collector.mcp_apps or None,
            cards=final_cards or None,
            matched_skills=collector.matched_skills or None,
            ttfb_ms=collector.ttfb_ms,
            total_ms=collector.total_ms,
            model=agent._provider.model,
        )
        # 正常结束：把实时进度行就地更新为最终回复（content/usage/tool_steps/a2ui 全写全），
        # 复用同一行，避免「占位行 + 最终行」重复两条 assistant 消息。无进度行则照常新建。
        # 最终回复只存在于内存 collector.full，这里是唯一落库点：并发写库（定时任务、
        # heartbeat、其他会话）撞 database is locked 时，异常若裸冒出去会绕过上方所有
        # 兜底分支——run 不 finish、SSE 挂死、回复永久丢失、占位行永远停在 running。
        # 所以锁冲突退避重试；重试耗尽也不能崩溃：标记 interrupted 并 emit error，
        # 让 run 走正常收尾。
        try:
            if progress_msg_id:
                await retry_on_db_locked(store.update_message, progress_msg_id, session_id, asst_msg)
                msg_id = progress_msg_id
            else:
                msg_id = await retry_on_db_locked(store.save_message, session_id, asst_msg)
        except Exception:
            logger.exception("最终回复落库失败（重试耗尽）session=%s row=%s", session_id, progress_msg_id)
            if progress_msg_id:
                try:
                    await retry_on_db_locked(store.update_message_status, progress_msg_id, "interrupted", "running")
                except Exception:
                    logger.exception(
                        "落库失败后标记 interrupted 也失败 session=%s row=%s",
                        session_id,
                        progress_msg_id,
                    )
            run.emit({"error": "回复已生成，但写数据库时一直被锁，保存失败。请重发这条消息重试。"})
        else:
            if agent._skills and agent.last_matched_skills:
                for _name in agent.last_matched_skills:
                    asyncio.create_task(asyncio.to_thread(agent._skills.record_hit, _name))
            asyncio.create_task(_maybe_consolidate(session_id, agent._provider.model, user_id, mode=mode))
            asyncio.create_task(_maybe_generate_skill(session_id, agent._provider.model, user_id))

        # touch 只更新会话列表的 updated_at 排序时间戳，与主消息落库解耦：
        # 极端情况下主消息已保存成功、touch 撞锁重试耗尽时，不该给前端报
        # 「保存失败」，更不该把已成功的定稿误标 interrupted——单独容错，失败仅记日志。
        try:
            await retry_on_db_locked(store.touch, session_id)
        except Exception:
            logger.warning("touch 会话时间戳失败（重试耗尽）session=%s", session_id, exc_info=True)

    # --- Get笔记 异步任务后台轮询 ---
    # 从 agent 回复中提取 getnote task_id，后台轮询直到完成，
    # 完成后把笔记内容作为独立消息推送给前端（复用 SSE 流）。
    # 用独立变量引用 store 以保持语义清晰。
    from ethan.core.background_polling import extract_task_id, poll_getnote_task

    task_id = extract_task_id(collector.full or "")
    if task_id:
        bg_store = await get_session_store()
        run.emit({"background_polling": True, "polling_message": "\U0001f4e1 Get笔记正在提取视频内容，请稍候..."})
        try:

            async def _on_progress(status, note_id):
                if status in ("processing", "pending"):
                    run.emit({"background_polling": True, "polling_message": "\u23f3 仍在提取中..."})

            result = await poll_getnote_task(task_id, on_progress=_on_progress)
        except Exception as e:
            logger.exception("getnote 后台轮询异常: %s", e)
            result = None
        if result and result.get("content"):
            note_content = result["content"]
            note_title = result.get("title", "")
            header = "\U0001f4dd Get笔记提取完成" + (f"：{note_title}" if note_title else "")
            bg_msg = f"{header}\n\n{note_content}"
            # 用 new_message 事件推送独立消息（不拼到当前消息末尾）
            run.emit({"new_message": True, "content": bg_msg})
            try:
                await bg_store.save_message(
                    session_id,
                    Message(
                        role="assistant",
                        content=bg_msg,
                    ),
                )
                await bg_store.touch(session_id)
            except Exception:
                logger.exception("保存 getnote 后台结果失败 session=%s", session_id)
        elif result and result.get("detail_failed"):
            # 任务成功但 detail 拉取失败
            detail_msg = f"\u2705 Get笔记任务已完成（note_id: {result.get('note_id', '?')}, task_id: {result.get('task_id', '?')}），但内容拉取失败，请用「查一下笔记」重试。"
            run.emit({"new_message": True, "content": detail_msg})
            try:
                await bg_store.save_message(
                    session_id,
                    Message(
                        role="assistant",
                        content=detail_msg,
                    ),
                )
                await bg_store.touch(session_id)
            except Exception:
                logger.exception("保存 getnote detail 失败提示失败 session=%s", session_id)
        else:
            timeout_msg = "\u23f3 Get笔记提取超时，请稍后用「查一下笔记」重试。"
            run.emit({"new_message": True, "content": timeout_msg})
            try:
                await bg_store.save_message(
                    session_id,
                    Message(
                        role="assistant",
                        content=timeout_msg,
                    ),
                )
                await bg_store.touch(session_id)
            except Exception:
                logger.exception("保存 getnote 超时提示失败 session=%s", session_id)

    # 标题生成：await 以便把结果带进 done 事件，前端实时更新
    new_title = await _maybe_regen_title(session_id)

    # 浏览器 session 清理：必须在 done/finish 之前，否则 SSE 已断无法送达 confirm 卡片
    await _close_browser_sessions(session_id, run=run)

    # 通知所有订阅者「流结束」并附最终 usage
    done_evt: dict = {
        "done": True,
        "usage": usage_dict,
        "ttfb_ms": collector.ttfb_ms,
        "total_ms": collector.total_ms,
        "message_id": msg_id,
        "model": agent._provider.model,
    }
    if new_title:
        done_evt["title"] = new_title
    run.emit(done_evt)
    run.finish()
    _RunManager_schedule_removal(run.session_id)
