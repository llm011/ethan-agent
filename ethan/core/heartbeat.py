"""系统级心跳 — 定期执行系统维护任务（facts 整理、heartbeat.md 任务）。

不暴露给用户管理，通过 config.defaults.heartbeat 配置。
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


async def _consolidate_facts() -> None:
    """用 LLM 对每个用户的 facts.json 做去重合并，只在 facts >= 10 条时触发。"""
    from ethan.core.users import get_user_store
    for uid in get_user_store().all_user_ids():
        try:
            await _consolidate_facts_for_user(uid)
        except Exception:
            logger.exception("[Heartbeat] Facts consolidation failed for user %s", uid)


async def _consolidate_facts_for_user(user_id: str) -> None:
    from ethan.memory.facts import FactStore
    from ethan.providers.manager import create_provider
    from ethan.providers.base import Message
    from ethan.core.config import get_config
    from ethan.core.paths import user_facts_path

    store = FactStore(path=user_facts_path())
    active = store.get_active()
    if len(active) < 10:
        return

    logger.info("[Heartbeat] Consolidating %d facts...", len(active))
    facts_text = "\n".join(f"- {f.content}" for f in active)
    prompt = (
        f"以下是关于用户的 {len(active)} 条记忆：\n{facts_text}\n\n"
        "请整理这些记忆：\n"
        "1. 合并重复或表达相同信息的条目\n"
        "2. 删除明显过时的（如果有更新版本）\n"
        "3. 修正矛盾（保留更新的一条）\n"
        "4. 保留所有独立有价值的信息\n\n"
        "每行一条，以 '- ' 开头。只输出整理后的列表，不要解释。"
    )

    cfg = get_config()
    from ethan.memory.consolidator import get_lite_model
    cheap_model = get_lite_model(cfg.defaults.model)
    try:
        provider = create_provider(cheap_model)
        resp = await provider.chat(
            [Message(role="user", content=prompt)],
            system="你是一个记忆管理助手，负责整理和去重用户记忆。",
        )
        lines = [
            line.strip().lstrip("- ").strip()
            for line in resp.content.strip().split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]
        if not lines:
            return

        # 重置 facts：先全部标为 superseded，再写入整理后的结果
        for f in store._facts:
            f.superseded = True
        store._save()
        for line in lines:
            store.add(line, confidence=0.85, source="heartbeat_consolidation")
        logger.info("[Heartbeat] Facts consolidated: %d → %d", len(active), len(lines))
    except Exception:
        logger.exception("[Heartbeat] Facts consolidation failed")


async def _run_heartbeat_md() -> None:
    """读取 heartbeat.md，若有内容则作为 agent 任务执行，结果保存到专属 session。"""
    from ethan.core.config import get_config
    from ethan.core.agent import Agent
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message
    from ethan.skills.registry import SkillRegistry
    from ethan.tools.builtin.file import FileListTool, FileReadTool, FileWriteTool
    from ethan.tools.builtin.knowledge import KnowledgeAddTool, KnowledgeSearchTool
    from ethan.tools.builtin.schedule import ScheduleCreateTool, ScheduleListTool, ScheduleRemoveTool
    from ethan.tools.builtin.shell import ShellTool
    from ethan.tools.builtin.web import WebFetchTool
    from ethan.tools.builtin.web_search import WebSearchTool
    from ethan.tools.registry import ToolRegistry

    cfg = get_config()
    workspace = cfg.defaults.workspace
    hb_path = Path(workspace) / "system" / "heartbeat.md"
    if not hb_path.exists():
        return

    content = hb_path.read_text(encoding="utf-8")
    if not content.strip():
        return

    # 心跳 MVP 归到 admin 用户
    from ethan.core.users import get_user_store
    from ethan.core.paths import ensure_user_dirs, user_sessions_db_path
    hb_user_id = get_user_store().get_admin_user_id()
    from ethan.core.agent_factory import create_agent as _create_agent
    agent = _create_agent(user_id=hb_user_id, toolset="heartbeat")

    logger.info("[Heartbeat] Running heartbeat.md tasks...")
    prompt = f"[Heartbeat] 正在执行系统心跳任务：heartbeat.md\n\n{content.strip()}"

    try:
        from ethan.providers.base import ToolEvent
        import time

        # 每次心跳创建一个全新的专属 session，便于在 Web 上独立查看
        store = SessionStore(db_path=user_sessions_db_path())
        await store.init()
        hb_session = await store.create(cfg.defaults.model, source="heartbeat")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        await store.update_title(hb_session.id, f"[心跳] {now_str}")

        user_msg = Message(role="user", content=prompt)
        await store.save_message(hb_session.id, user_msg)
        await store.touch(hb_session.id)

        # 用 stream_chat 执行，收集工具步骤 / 思考 / 正文
        tool_start_times: dict[str, float] = {}
        collected_tool_steps: list[dict] = []
        full = ""
        thought = ""

        async for item in agent.stream_chat([user_msg]):
            if isinstance(item, ToolEvent):
                if item.state == "start":
                    if full:
                        thought += ("\n\n" if thought else "") + full
                        full = ""
                    tool_start_times[item.tool_name] = time.time()
                    collected_tool_steps.append({
                        "tool": item.tool_name,
                        "args": item.args_summary,
                        "state": "running",
                        "duration_ms": None,
                        "result_preview": "",
                    })
                else:
                    duration_ms = int(
                        (time.time() - tool_start_times.pop(item.tool_name, time.time())) * 1000
                    )
                    for step in reversed(collected_tool_steps):
                        if step["tool"] == item.tool_name and step["state"] == "running":
                            step["state"] = item.state
                            step["duration_ms"] = duration_ms
                            step["result_preview"] = item.result_preview or ""
                            break
            else:
                full += item

        usage_dict = {
            "input": agent.usage.input_tokens,
            "output": agent.usage.output_tokens,
            "cache": agent.usage.cache_tokens,
        }
        asst_msg = Message(
            role="assistant",
            content=full,
            thought=thought,
            usage=usage_dict,
            tool_steps=collected_tool_steps,
        )
        await store.save_message(hb_session.id, asst_msg)
        await store.touch(hb_session.id)
        await store.close()
        logger.info("[Heartbeat] heartbeat.md task done")
    except Exception:
        logger.exception("[Heartbeat] heartbeat.md execution failed")


async def _tick() -> None:
    """执行一次心跳：facts 整理 + heartbeat.md 任务 + skill 进化。"""
    logger.info("[Heartbeat] tick")
    await _consolidate_facts()
    await _run_heartbeat_md()
    await _update_skills()


async def _update_skills() -> None:
    try:
        from ethan.skills.updater import update_skills_from_corrections
        n = await update_skills_from_corrections()
        if n:
            logger.info("[Heartbeat] Updated %d skill(s)", n)
    except Exception:
        logger.exception("[Heartbeat] Skill update failed")


_heartbeat_task: asyncio.Task | None = None


async def _loop() -> None:
    from ethan.core.config import get_config
    # 延迟 60 秒后才开始第一次，避免服务刚启动时立即触发
    await asyncio.sleep(60)
    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[Heartbeat] Unexpected error in tick")
        cfg = get_config()
        interval = cfg.defaults.heartbeat.interval_minutes * 60
        await asyncio.sleep(interval)


def start_heartbeat() -> None:
    global _heartbeat_task
    from ethan.core.config import get_config
    if not get_config().defaults.heartbeat.enabled:
        logger.info("[Heartbeat] Disabled by config")
        return
    if _heartbeat_task and not _heartbeat_task.done():
        return
    _heartbeat_task = asyncio.create_task(_loop())
    logger.info("[Heartbeat] Started (interval=%dm)", get_config().defaults.heartbeat.interval_minutes)


def stop_heartbeat() -> None:
    global _heartbeat_task
    if _heartbeat_task and not _heartbeat_task.done():
        _heartbeat_task.cancel()
