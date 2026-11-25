"""Explicit interrupted-run recovery route and progress summary."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Query, Request

from ethan.memory.session import get_session_store

from .deps import verify_token
from .schemas import ChatRequest


def _build_resume_summary(target, process_md: str) -> str:
    """把中断前已执行的步骤压缩成「给用户看的反思摘要」，不超过 ~800 字。

    结构：
      🔄 中断恢复 · 进度回顾
      - 已完成 N 个步骤：
        1. 工具名（意图一句话）：结果一行摘要
        2. ...
      - 下一步建议：基于中间输出的 TODO 标题或最后未完成的步骤
    """
    lines = ["🔄 中断恢复 · 进度回顾"]
    steps = target.tool_steps or []
    if not steps and not process_md:
        return lines[0] + "\n\n（之前没有记录到具体执行步骤，直接继续即可。）"

    completed = sum(step.get("state") == "done" for step in steps)
    lines.append(f"\n记录了 {len(steps)} 个步骤，其中 {completed} 个已完成：")
    for idx, step in enumerate(steps, start=1):
        tool = step.get("tool") or f"step_{idx}"
        intent = step.get("intent") or ""
        preview = step.get("result_preview") or ""
        state = step.get("state") or "unknown"
        state_emoji = {"done": "✅", "error": "❌", "running": "⏳", "start": "⏳", "cancelled": "🚫"}.get(state, "⏸️")
        head = f"{idx}. {state_emoji} {tool}"
        if state not in ("done",):
            head += f"（{state}）"
        parts = [head]
        if intent and len(intent) < 120:
            parts.append(f"   意图：{intent.strip()}")
        elif intent:
            parts.append(f"   意图：{intent.strip()[:117]}…")
        if preview:
            one = preview.strip().splitlines()[0]
            if len(one) > 120:
                one = one[:117] + "…"
            parts.append(f"   结果：{one}")
        lines.append("\n".join(parts))

    # 从过程记录 markdown 里找「下一步 / TODO / 待办」字样，作为建议
    hint = ""
    if process_md:
        import re as _re
        for match in _re.finditer(r"(?im)^.*(下一步|TODO|待办|接着|然后|接下来).*$", process_md):
            s = match.group(0).lstrip("# ")
            if len(s) < 200:
                hint = s
                break
    if hint:
        lines.append(f"\n📝 之前记录的「下一步」提示：{hint}")

    lines.append("\n正在基于上述进度继续处理，以下是后续操作…")
    return "\n".join(lines)


async def resume_from_message(session_id: str, message_id: int, request: Request,
                              model: str | None = Query(None),
                              user_id: str = Depends(verify_token)):
    """从一条中断的消息继续执行。

    读取该消息的过程记录（intermediate blob 或从 tool_steps 重建），构造续接 prompt，
    把原消息标记为 completed，然后走正常 chat 流程。前端点击「继续」按钮时调用。
    """
    from .chat import _is_local, chat
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

    try:
        # 读取过程记录
        process_md = ""
        blob = await store.load_intermediate_blob(message_id)
        if blob and not blob.get("missing"):
            process_md = blob.get("content", "")
        elif target.tool_steps:
            from ethan.memory.session import _build_intermediate_markdown
            process_md = _build_intermediate_markdown(target)

        # 进度反思总结：面向用户输出（emit 到 SSE 流，占 assistant 消息首段），
        # 先写标题，再把步骤摘要按序号压缩（每个 step 取 tool + intent/result_preview 两行），
        # 避免把 完整 tool_steps markdown 全塞进去——过程记录本身已经在「过程记录」
        # 展开面板里，这里只需要"看起来有反思"的精简版。
        summary = _build_resume_summary(target, process_md)

        # 给模型的 runtime_context 保持短：只说继续，不给大段过程（模型 working 滑窗
        # 本身就能读到前面的 tool_steps assistant 行，重复塞会挤占窗口）。
        resume_context = (
            "这是一次「继续执行」续跑。上一轮任务在生成了若干工具步骤后被中断。"
            "对话历史里已经有完整的已执行步骤和结果，你可以直接读取它们。"
            "要求：\n"
            "1. 不要重述进度——你刚看到 assistant 第一条消息已经把进度摘要总结给了用户，"
            "那是系统提示，不用再重复；\n"
            "2. 基于对话历史里的步骤判断接下来该做什么，必要时复查上一步结果。"
        )
        # 运行检查点（条目 6）：中断时落库的结构化快照，告诉模型精确断点在哪，
        # 避免从零重新推理整条链路。
        ckpt = await store.load_run_checkpoint(message_id)
        if ckpt:
            from ethan.core.run_checkpoint import resume_context as checkpoint_context
            resume_context += checkpoint_context(ckpt)
            ckpt_bits = []
            if ckpt.get("iter"):
                ckpt_bits.append(f"中断于第 {ckpt['iter']} 轮（上限 {ckpt.get('max_iters', '?')}）")
            if ckpt.get("last_tools"):
                ckpt_bits.append("最后调用的工具：" + ", ".join(str(t) for t in ckpt["last_tools"][:5]))
            if ckpt.get("last_had_error"):
                ckpt_bits.append("最后一次工具调用失败了，先判断失败原因再决定是否重试")
            if ckpt_bits:
                resume_context += "\n\n运行检查点（据此判断断点位置，不要从头重做已完成的部分）：\n- " + "\n- ".join(ckpt_bits)

        req = ChatRequest(
            messages=[{"role": "user", "content": "继续执行"}],
            session_id=session_id,
            stream=True,
            channel="web",
            mode=session.mode,
            # 沿用当前窗口选中的模型（前端透传 selectedModel），不回退到默认模型
            model=model or None,
            auto_consent=_is_local(request),
            runtime_context=resume_context,
            resume_summary=summary,
        )
        return await chat(req, request, user_id)
    except BaseException:
        # A preparation failure or cancellation must release this request's claim.
        import asyncio
        await asyncio.shield(store.update_message_status(message_id, "interrupted", expected="completed"))
        raise
