"""Background tasks fired after a generation completes: title, memory consolidation, skill gen."""
from __future__ import annotations

import logging

from ethan.memory.session import get_session_store

logger = logging.getLogger("ethan.tasks")


async def _maybe_regen_title(session_id: str) -> str | None:
    """尝试生成/更新标题，返回新标题或 None（无变化/失败）。"""
    try:
        from ethan.memory.session import decide_title
        store = await get_session_store()
        session = await store.load(session_id)
        if not session:
            logger.warning("_maybe_regen_title: session %s not found", session_id)
            return None
        title = await decide_title(session.messages, session.title)
        if title and title != session.title:
            await store.update_title(session_id, title)
            logger.debug("_maybe_regen_title: updated %s -> %s", session_id, title)
            return title
    except Exception:
        logger.exception("_maybe_regen_title failed for session=%s", session_id)
    return None


_CORRECTION_KEYWORDS = (
    "不是", "其实", "纠正", "不对", "更正", "应该是", "说错了",
    "更准确地说", "不是这样", "错了", "搞错了", "不对，",
)


def _has_correction_keyword(session) -> bool:
    """检查最近一条 user 消息是否包含否定/修正类关键词。

    用于在 5 轮基线之外提前触发抽取，及时修正已有记忆。
    """
    for msg in reversed(session.messages):
        if msg.role == "user" and msg.content:
            return any(kw in msg.content for kw in _CORRECTION_KEYWORDS)
    return False


async def _run_structured_extraction(session, model: str, user_id: str, user_turns: int,
                                     store=None, force: bool = False) -> None:
    """Every three turns (or on correction keywords), extract source-backed memories.

    3 轮基线触发 + 关键词触发：检测到否定/修正类关键词时立即触发，
    避免跨轮次修正无法及时更新记忆。job_key 基于 message_id 保证幂等。
    store 可注入(测试/评测用);不传则按当前用户路径创建 MemoryStore。
    force=True 时跳过门槛检查（12 点兜底扫描用，已在外层过滤过短会话）。
    """
    if not force and user_turns % 3 != 0 and not _has_correction_keyword(session):
        return

    from ethan.memory.admission import (
        complete_incremental,
        fail_incremental,
        incremental_job_key,
        run_incremental_admission,
    )
    from ethan.memory.extractors import SourceMessage, StructuredMemoryExtractor
    from ethan.memory.records import ConsolidationJob
    from ethan.memory.store import MemoryStore

    source_messages = [
        SourceMessage.from_message(message, session.id)
        for message in session.messages
        if message.role in ("user", "assistant") and message.content and message.id is not None
    ]
    if not source_messages:
        return

    last_message = source_messages[-1]
    job_key = incremental_job_key(user_id, session.id, last_message.message_id)
    memory_store = store or MemoryStore()
    try:
        boundary = memory_store.last_completed_incremental_boundary(session.id)
        pending_messages = [
            message for message in source_messages
            if boundary is None or (message.created_at or 0) > boundary
        ]
        if not pending_messages:
            return
        job = ConsolidationJob(
            user_id=user_id,
            job_type="incremental_extraction",
            job_key=job_key,
            pipeline_version="v1",
            source_from=boundary,
            source_until=last_message.created_at or 0,
        )
        if not memory_store.claim_job(job):
            return

        extractor = StructuredMemoryExtractor(model=model)
        candidates = await extractor.extract(
            pending_messages,
            session_id=session.id,
            user_id=user_id,
            mode=session.mode,
            job_key=job_key,
        )
        if candidates is None:
            # LLM 调用失败(瞬时):标 failed 让下轮重试,不能让 boundary 前进,
            # 否则这批消息的提取永久丢失。
            raise RuntimeError("structured extraction LLM call failed")
        inserted_ids = {candidate_id for candidate_id in memory_store.create_candidate_batch(candidates)}
        inserted = [candidate for candidate in candidates if candidate.id in inserted_ids]
        result = run_incremental_admission(memory_store, inserted)
        complete_incremental(
            memory_store,
            user_id=user_id,
            session_id=session.id,
            message_id=last_message.message_id,
            result={
                "candidates": len(inserted),
                "admitted": len(result.admitted),
                "merged": len(result.merged),
                "rejected": len(result.rejected),
            },
        )
    except Exception as exc:
        logger.exception("structured memory extraction failed for session=%s", session.id)
        try:
            fail_incremental(
                memory_store,
                user_id=user_id,
                session_id=session.id,
                message_id=last_message.message_id,
                error=str(exc),
            )
        except Exception:
            logger.exception("failed to record extraction error for session=%s", session.id)
    finally:
        memory_store.close()


async def _maybe_consolidate(session_id: str, model: str, user_id: str = "", mode: str = "") -> None:
    # 对话结束 → 触发 sessions.db 防抖备份
    from ethan.memory.session_backup import schedule_backup
    schedule_backup()

    try:
        # 心理画像是否额外抽取：由当前 mode 自身声明，不在此硬编码模式名
        from ethan.core.modes import resolve_mode
        resolve_mode(mode)  # validate mode exists

        store = await get_session_store()
        session = await store.load(session_id)
        if not session:
            return

        # 脱敏：在喂给 consolidator 前，把消息正文里的 secret 真值替换为引用
        from ethan.core.secrets_store import mask_text
        for m in session.messages:
            if m.content:
                m.content = mask_text(m.content)

        # Persisted session mode is authoritative. Older sessions may have no mode;
        # only then fall back to the caller-provided value.
        session.mode = session.mode or mode
        resolve_mode(session.mode)

        user_turns = sum(1 for m in session.messages if m.role == "user")
        if user_turns == 0:
            return

        # Structured Person/Methodology extraction is independent from the legacy
        # rolling-summary path and runs at the approved three-turn cadence.
        await _run_structured_extraction(session, model, user_id, user_turns)

    except Exception:
        logger.exception("_maybe_consolidate failed for session=%s", session_id)


async def _maybe_generate_skill(session_id: str, model: str, user_id: str = "") -> None:
    try:
        from ethan.skills.generator import MIN_TURNS, SkillGenerator
        store = await get_session_store()
        session = await store.load(session_id)
        if not session:
            return
        user_turns = sum(1 for m in session.messages if m.role == "user")
        # skill 生成走完整 LLM prompt（比记忆提取重），保持 5 轮节流——
        # 比记忆提取 3 轮更克制（见 generator.py MIN_TURNS 注释）。
        # maybe_generate 内部对已存在的 skill 文件有去重，但 NO_SKILL 的判断
        # 每次都会重跑 LLM，故仍需外层节流。
        if user_turns < MIN_TURNS or user_turns % 5 != 0:
            return
        generator = SkillGenerator(model=model, user_id=user_id)
        await generator.maybe_generate(session.messages)
    except Exception:
        logger.exception("_maybe_generate_skill failed for session=%s", session_id)
