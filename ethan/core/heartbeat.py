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
    from ethan.core.config import get_config
    from ethan.core.context import ETHAN_USER_ID
    from ethan.core.paths import user_facts_path
    from ethan.memory.facts import FactStore
    from ethan.providers.base import Message
    from ethan.providers.manager import create_provider

    # user_*_path() 走 ETHAN_USER_ID ContextVar 解析分库；心跳循环里必须显式 set，
    # 否则所有用户都会落到 default profile（user_id 参数本身不参与路径解析）。
    token = ETHAN_USER_ID.set(user_id)
    try:
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
    finally:
        ETHAN_USER_ID.reset(token)


# ── 画像每日 consolidation（A 方案：平铺 bullet + 分区差异化压缩）──────
PROFILE_SECTION_MIN_BULLETS = 4           # section bullet < 4 跳过（没东西可去重，强模型重写反增幻觉风险）

# 三组各自的压缩策略（system role + 用户 prompt 取向），制造层次感
_PROFILE_STRATEGIES = {
    "identity": (
        "你是一个用户画像整理助手，负责对身份与背景类信息去重、归纳、层次化，同时保留所有独立有价值的事实。",
        "整理这些关于用户的画像条目，让它更有层次、更精炼：\n"
        "1. 把相关的事实聚到一起、归纳成更概括的一条（例如多条具体技能/经历 → 一条概括的能力或背景描述）；\n"
        "2. 合并重复或表达相同信息的条目、修正矛盾（保留更新的一条）、删除明显过时的；\n"
        "3. 保留所有独立有价值的事实，不要丢信息也不要编造。\n"
        "目标是从「零散罗列」升华为「有结构的概括」，但任何独特的事实都不能丢。",
    ),
    "emotion": (
        "你是一个用户心理画像整理助手，负责把零散重复的情绪记录聚类、高度压缩、归纳成稳定的情绪模式。",
        "把这些情绪与心理类条目整理成更有层次的心理画像：\n"
        "1. 把指向同一问题/同一触发源的具体情绪事件聚到一起，高度压缩、归纳成一条概括性的模式"
        "（例如多条「这次汇报很焦虑」「上次评审也紧张」→「在公开表达/被评审的场景下容易焦虑」）；\n"
        "2. 保留稳定的情绪模式、压力源、什么能安抚 ta、重要价值观；\n"
        "3. 偶发的、一次性的、已不再重复的具体情绪事件可以并入概括或删除。\n"
        "目标是从「流水账式的具体事件」升华为「概括性的稳定心理特征」。不要编造。",
    ),
    "agreement": (
        "你是一个用户偏好整理助手，负责整理用户与 AI 助手之间的约定，每条指令都要保留。",
        "整理这些用户与助手的约定/指令：仅合并表达完全相同的条目，每条独立的指令或偏好都必须保留，不要删减、不要编造。",
    ),
}


async def _compress_section(provider, section: str, bullets: list[str], strategy: str) -> list[str] | None:
    """用主力模型压缩单个 section 的 bullet 列表。失败/空结果返回 None（调用方保留原内容）。"""
    from ethan.providers.base import Message

    sys_role, instruction = _PROFILE_STRATEGIES[strategy]
    bullets_text = "\n".join(f"- {b}" for b in bullets)
    prompt = (
        f"以下是用户画像中「{section}」这一节的 {len(bullets)} 条记录：\n{bullets_text}\n\n"
        f"{instruction}\n\n"
        "每行一条，以 '- ' 开头。只输出整理后的列表，不要解释、不要加标题。"
    )
    try:
        resp = await provider.chat([Message(role="user", content=prompt)], system=sys_role)
        lines = [
            ln.strip().lstrip("-").strip()
            for ln in resp.content.strip().split("\n")
            if ln.strip() and not ln.strip().startswith("#")
        ]
        return lines or None
    except Exception:
        logger.exception("[Heartbeat] Profile section '%s' compression failed", section)
        return None


async def _consolidate_profiles() -> None:
    """对每个用户的 user_profile.md 做每日分区压缩。"""
    from ethan.core.users import get_user_store
    for uid in get_user_store().all_user_ids():
        try:
            await _consolidate_profile_for_user(uid)
        except Exception:
            logger.exception("[Heartbeat] Profile consolidation failed for user %s", uid)


async def _consolidate_profile_for_user(user_id: str) -> None:
    import time
    from datetime import datetime

    from ethan.core.config import get_config
    from ethan.core.context import ETHAN_USER_ID
    from ethan.core.paths import user_memory_dir, user_profile_path
    from ethan.core.profile import (
        PROFILE_GROUP_AGREEMENT,
        PROFILE_GROUP_EMOTION,
        PROFILE_GROUP_IDENTITY,
        section_bullets,
        set_section_bullets,
    )
    from ethan.providers.manager import create_provider

    token = ETHAN_USER_ID.set(user_id)
    try:
        profile_path = user_profile_path()
        if not profile_path.exists():
            return

        marker = user_memory_dir() / ".profile_consolidated_at"
        now = time.time()
        try:
            last = float(marker.read_text(encoding="utf-8").strip()) if marker.exists() else 0.0
        except Exception:
            last = 0.0

        # 触发钟点：按用户本地时区的配置小时之后、每天一次。
        cfg = get_config()
        from ethan.core.timezone import get_local_timezone
        local_tz = get_local_timezone()
        now_local = datetime.fromtimestamp(now, local_tz)
        target_hour = cfg.defaults.heartbeat.profile_consolidate_hour
        last_bj_date = datetime.fromtimestamp(last, local_tz).date() if last > 0 else None

        # 闸门①：还没到当天触发钟点 → 等。
        if now_local.hour < target_hour:
            return
        # 闸门②：今天已经压过 → 跳过（每天一次）。
        if last_bj_date is not None and last_bj_date >= now_local.date():
            return
        # 闸门③：画像自上次压缩后没改动 → 跳过，不空烧 token。
        if last > 0 and profile_path.stat().st_mtime <= last:
            # 仍记一次时间戳，避免今天反复进这里重判
            try:
                marker.write_text(str(profile_path.stat().st_mtime), encoding="utf-8")
            except Exception:
                pass
            return

        content = profile_path.read_text(encoding="utf-8")
        provider = create_provider(cfg.defaults.model)  # 用主力模型，一天一次成本可接受

        groups = [
            (PROFILE_GROUP_IDENTITY, "identity"),
            (PROFILE_GROUP_EMOTION, "emotion"),
            (PROFILE_GROUP_AGREEMENT, "agreement"),
        ]
        new_content = content
        changed = False
        for sections, strategy in groups:
            for section in sections:
                bullets = section_bullets(new_content, section)
                if len(bullets) < PROFILE_SECTION_MIN_BULLETS:
                    continue  # 逐 section 闸门：太少不压
                compressed = await _compress_section(provider, section, bullets, strategy)
                if compressed and compressed != bullets:
                    new_content = set_section_bullets(new_content, section, compressed)
                    changed = True

        if changed:
            # 覆盖前备份，lite/幻觉漏删可回溯
            try:
                profile_path.with_suffix(profile_path.suffix + ".bak").write_text(content, encoding="utf-8")
            except Exception:
                logger.exception("[Heartbeat] Profile backup failed for user %s", user_id)
            profile_path.write_text(new_content, encoding="utf-8")
            logger.info("[Heartbeat] Profile consolidated for user %s", user_id or "default")

        # 不论是否改动都记时间戳：标记今天已处理，避免当天反复触发。
        # 用文件实际 mtime（而非开头捕获的 now），避免 write_text 后 mtime 漂移导致
        # 第二天闸门③误判"画像又变了"白烧 token。
        try:
            actual_mtime = profile_path.stat().st_mtime
            marker.write_text(str(actual_mtime), encoding="utf-8")
        except Exception:
            logger.exception("[Heartbeat] Profile marker write failed for user %s", user_id)
    finally:
        ETHAN_USER_ID.reset(token)


async def _run_heartbeat_md() -> None:
    """读取 heartbeat.md，若有内容则作为 agent 任务执行，结果保存到专属 session。"""
    from ethan.core.config import get_config
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message

    cfg = get_config()
    workspace = cfg.defaults.workspace
    hb_path = Path(workspace) / "system" / "heartbeat.md"
    if not hb_path.exists():
        return

    content = hb_path.read_text(encoding="utf-8")
    # 过滤掉纯注释行（# 开头）和空行，没有实质任务就不执行
    effective_lines = [line for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
    if not effective_lines:
        return

    # 心跳 MVP 归到 admin 用户
    from ethan.core.paths import user_sessions_db_path
    from ethan.core.users import get_user_store
    hb_user_id = get_user_store().get_admin_user_id()
    from ethan.core.agent_factory import create_agent as _create_agent
    agent = _create_agent(user_id=hb_user_id, toolset="heartbeat")

    logger.info("[Heartbeat] Running heartbeat.md tasks...")
    prompt = f"[Heartbeat] 正在执行系统心跳任务：heartbeat.md\n\n{content.strip()}"

    try:
        import time

        from ethan.providers.base import ThinkingEvent, ToolEvent

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
            if isinstance(item, ThinkingEvent):
                continue  # 思考内容不计入 heartbeat 正文
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
    """执行一次心跳：facts 整理 + 画像每日压缩 + heartbeat.md 任务 + skill 进化。"""
    logger.info("[Heartbeat] tick")
    await _consolidate_facts()
    await _consolidate_profiles()
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
