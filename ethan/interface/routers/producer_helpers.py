"""producer helpers responsibilities; imported via producers facade."""
from __future__ import annotations

from ethan.memory.session import SessionStore
from ethan.providers.base import Message


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


def _infer_task_kind(messages: list) -> str:
    """粗粒度任务类型推断，供 `kernel.task_rules` 的按任务选内核使用。

    刻意保持极简：只区分 coding / research / chat 三类，且只做关键词判断——
    真正的意图理解由模型自己做（有个 `classify.py` 在 acp 里，但那是为委派服务的，
    代价太大，不适合每轮都跑）。猜错的代价很小：回退到 `kernel.default`。
    """
    text = ""
    for m in reversed(messages or []):
        if getattr(m, "role", "") == "user":
            text = (getattr(m, "content", "") or "")[:500].lower()
            break
    if not text:
        return "chat"

    coding_kw = (
        "代码", "重构", "实现", "修复", "bug", "debug", "测试", "编译",
        "函数", "类", "接口", "api", "commit", "pr ", "merge",
        "refactor", "implement", "fix", "test", "python", "typescript",
    )
    research_kw = ("调研", "分析", "对比", "论文", "研究", "report", "research", "survey")

    if any(k in text for k in coding_kw):
        return "coding"
    if any(k in text for k in research_kw):
        return "research"
    return "chat"


def _kernel_working_dir(agent) -> str:
    """外部内核的工作目录。

    **绝不能返回空串让 ACP 落到进程 cwd**：`ethan serve` 被人为以 `/` 为 cwd 启动
    （launchd/watchdog 拉起时的常见情况），外部 CLI 在根目录下跑会立刻失败——
    实测 codex 报 `Not inside a trusted directory`，claude 的行为也不可预期。

    优先级：
      1. 会话级 working_dir（ACP client / 渠道层显式设置）
      2. agent 上记录的值
      3. 用户 workspace（`~/.ethan`）—— 一个确定可写、非根的位置
    """
    try:
        from ethan.core.context import get_working_dir

        wd = get_working_dir()
        if wd:
            return wd
    except Exception:
        pass

    wd = getattr(agent, "_working_dir", "") or ""
    if wd:
        return wd

    # 兜底到 workspace：外部 CLI 需要一个真实目录，而不是 "/" 或安装目录
    try:
        from ethan.core.config import get_config

        ws = get_config().defaults.workspace
        if ws:
            import os

            return os.path.expanduser(ws)
    except Exception:
        pass
    return ""
