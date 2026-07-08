"""Producer tasks: background generation functions that emit events into a ChatRun."""
from __future__ import annotations

import asyncio
import logging

from ethan.memory.session import SessionStore
from ethan.providers.base import Message

from .helpers import _friendly_error
from .tasks import _maybe_consolidate, _maybe_generate_skill, _maybe_regen_title

logger = logging.getLogger(__name__)


def _RunManager_schedule_removal(session_id: str) -> None:
    from ethan.core.run_manager import RunManager
    RunManager.instance().schedule_removal(session_id)


async def _save_progress(store: SessionStore, session_id: str,
                         progress_msg_id: int | None,
                         tool_steps: list, a2ui: list | None) -> int:
    """工具过程实时落库：把当前 tool_steps 快照写进一条 assistant 消息。

    首次（progress_msg_id is None）：INSERT 一条占位行（content 空、tool_steps 为当前步骤），
    返回新行 id；后续：UPDATE 同一行覆盖 tool_steps/a2ui，复用 id 返回。

    这样整轮只占一条 assistant 行，工具步骤随完成实时留存，进程崩溃/用户关页面也不丢过程。
    """
    msg = Message(
        role="assistant",
        content="",
        tool_steps=tool_steps,
        a2ui=a2ui,
    )
    if progress_msg_id is None:
        return await store.save_message(session_id, msg)
    await store.update_message(progress_msg_id, session_id, msg)
    return progress_msg_id


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
            run.emit({
                "tool": data.get("tool", ""),
                "args": data.get("args", ""),
                "state": data.get("state", "done"),
                "id": f"mirror-{id(data)}",
                "duration_ms": data.get("duration_ms"),
                "result_preview": data.get("result_preview", ""),
            })

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
        finally:
            try:
                await store.close()
            except Exception:
                pass
        run.emit({"done": True, "usage": {}})
        run.finish()
        _RunManager_schedule_removal(run.session_id)
        return

    result = None
    try:
        result = await delegate(
            prompt=prompt, cwd=cwd, prefer=agent_name, timeout=240,
            resume=True, user_id=user_id, mirror=False, on_event=_emit,
        )
    except asyncio.CancelledError:
        run.emit({"stopped": True, "usage": {}})
        run.finish()
        try:
            await store.close()
        except Exception:
            pass
        _RunManager_schedule_removal(run.session_id)
        raise
    except Exception as e:
        run.emit({"error": _friendly_error(e, None)})

    try:
        if result is not None:
            content = result.output or ("(委派失败，无输出)" if not result.success else "(无输出)")
            # 子进程层失败时 on_event 不会触发，没有任何 text 推过；
            # 把最终结果作为 content 补推一次，避免 live 流空返回（刷新才看到）。
            if not emitted_text:
                run.emit({"content": content})
            await store.save_message(session_id, Message(
                role="assistant", content=content, tool_steps=result.sub_steps or [],
            ))
            await store.touch(session_id)
    except Exception:
        logger.exception("保存委派续接结果失败 session=%s", session_id)
    finally:
        try:
            await store.close()
        except Exception:
            pass

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
    from ethan.core.consent import ConsentEvent, set_consent_provider
    from ethan.core.stream_collector import StreamCollector
    from ethan.providers.base import ThinkingEvent, ToolEvent

    # consent provider 经 ContextVar 注入；本任务有独立 context，需在任务内设置。
    set_consent_provider(consent)

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
                run.emit({
                    "consent_request": True,
                    "request_id": item.request_id,
                    "tool": item.tool,
                    "description": item.description,
                    "detail": item.detail,
                    "always": item.always,
                })
            elif isinstance(item, ThinkingEvent):
                run.emit({"thinking": True})
            elif isinstance(item, ToolEvent):
                collector.feed(item)
                if item.state == "start":
                    run.emit({"tool": item.tool_name, "args": item.args_summary, "state": "start",
                              "id": item.tool_call_id, "intent": item.intent or ""})
                else:
                    step = collector.tool_steps[-1]
                    evt = {
                        "tool": item.tool_name,
                        "args": item.args_summary,
                        "state": item.state,
                        "id": item.tool_call_id,
                        "duration_ms": step.get("duration_ms"),
                        "result_preview": item.result_preview or "",
                        "result_detail": item.result_detail or "",
                        "sub_steps": item.sub_steps or [],
                    }
                    if item.ui:
                        evt["ui"] = item.ui
                    run.emit(evt)
                # 工具事件（start/done/error）后实时落库进度：把当前全部 tool_steps
                # 写到这条进度消息上。首次创建，后续 UPDATE 同一条（progress_msg_id 复用）。
                if session_id and consent is not None:
                    try:
                        progress_msg_id = await _save_progress(
                            store, session_id, progress_msg_id,
                            collector.tool_steps or [], collector.a2ui or None,
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
        if progress_msg_id and session_id:
            try:
                if getattr(run, "stop_requested", False):
                    stopped_content = (collector.full or "") + "\n\n_（已停止）_"
                    await store.update_message(progress_msg_id, session_id, Message(
                        role="assistant",
                        content=stopped_content,
                        thought=collector.thought,
                        usage=collector.usage_dict,
                        tool_steps=collector.tool_steps or [],
                        a2ui=collector.a2ui or None,
                    ))
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
                    usage=collector.usage_dict,
                    tool_steps=collector.tool_steps or [],
                    a2ui=collector.a2ui or None,
                )
                await store.save_message(session_id, stopped_msg)
                await store.touch(session_id)
            except Exception:
                logger.exception("保存已停止生成的部分内容失败 session=%s", session_id)
        run.emit({"stopped": True, "usage": collector.usage_dict})
        run.finish()
        try:
            await store.close()
        except Exception:
            pass
        _RunManager_schedule_removal(run.session_id)
        raise
    except Exception as e:
        err_text = _friendly_error(e, agent)
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
                usage=collector.usage_dict,
                tool_steps=collector.tool_steps or [],
                a2ui=collector.a2ui or None,
            )
            try:
                if progress_msg_id:
                    await store.update_message(progress_msg_id, session_id, err_msg)
                else:
                    await store.save_message(session_id, err_msg)
                await store.touch(session_id)
            except Exception:
                logger.exception("保存错误消息失败 session=%s", session_id)
    finally:
        # 流结束（正常/异常）时取消未决授权 Future，避免泄漏
        if consent is not None:
            consent.cancel_all()

    usage_dict = collector.usage_dict

    if session_id and (collector.full or collector.thought):
        asst_msg = Message(
            role="assistant",
            content=collector.full,
            thought=collector.thought,
            usage=usage_dict,
            tool_steps=collector.tool_steps or [],
            a2ui=collector.a2ui or None,
        )
        # 正常结束：把实时进度行就地更新为最终回复（content/usage/tool_steps/a2ui 全写全），
        # 复用同一行，避免「占位行 + 最终行」重复两条 assistant 消息。无进度行则照常新建。
        if progress_msg_id:
            await store.update_message(progress_msg_id, session_id, asst_msg)
        else:
            await store.save_message(session_id, asst_msg)
        await store.touch(session_id)
        if agent._skills and agent.last_matched_skills:
            for _name in agent.last_matched_skills:
                asyncio.create_task(asyncio.to_thread(agent._skills.record_hit, _name))
        asyncio.create_task(_maybe_consolidate(session_id, agent._provider.model, user_id, mode=mode))
        asyncio.create_task(_maybe_regen_title(session_id))
        asyncio.create_task(_maybe_generate_skill(session_id, agent._provider.model, user_id))

    await store.close()

    # 通知所有订阅者「流结束」并附最终 usage
    run.emit({"done": True, "usage": usage_dict})
    run.finish()
    _RunManager_schedule_removal(run.session_id)
