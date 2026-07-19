"""Background tasks fired after a generation completes: title, memory consolidation, skill gen."""
from __future__ import annotations

import logging

from ethan.memory.session import SessionStore

logger = logging.getLogger("ethan.tasks")


async def _maybe_regen_title(session_id: str) -> str | None:
    """尝试生成/更新标题，返回新标题或 None（无变化/失败）。"""
    try:
        from ethan.core.paths import user_sessions_db_path
        from ethan.memory.session import decide_title
        store = SessionStore(db_path=user_sessions_db_path())
        await store.init()
        try:
            session = await store.load(session_id)
            if not session:
                logger.warning("_maybe_regen_title: session %s not found", session_id)
                return None
            title = await decide_title(session.messages, session.title)
            if title and title != session.title:
                await store.update_title(session_id, title)
                logger.debug("_maybe_regen_title: updated %s -> %s", session_id, title)
                return title
        finally:
            await store.close()
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
                                     store=None) -> None:
    """Every five turns (or on correction keywords), extract source-backed memories.

    5 轮基线触发 + 关键词触发：检测到否定/修正类关键词时立即触发，
    避免跨轮次修正无法及时更新记忆。job_key 基于 message_id 保证幂等。
    store 可注入(测试/评测用);不传则按当前用户路径创建 MemoryStore。
    """
    if user_turns % 5 != 0 and not _has_correction_keyword(session):
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
    memory_store = MemoryStore()
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
    try:
        # 心理画像是否额外抽取：由当前 mode 自身声明，不在此硬编码模式名
        from ethan.core.modes import resolve_mode
        from ethan.core.paths import user_episodes_path, user_sessions_db_path
        from ethan.memory.episodic import EpisodeStore
        resolve_mode(mode)  # validate mode exists

        store = SessionStore(db_path=user_sessions_db_path())
        await store.init()
        session = await store.load(session_id)
        await store.close()
        if not session:
            return

        # 脱敏：在喂给 consolidator/episode 前，把消息正文里的 secret 真值替换为引用
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
        # rolling-summary path and runs at the approved five-turn cadence.
        await _run_structured_extraction(session, model, user_id, user_turns)

        # ── Episode 写入（每次对话都记，不等门槛）──────────────────────
        # 原 repl.py 退出时才写 episode，Web/Lark/WeChat 渠道完全没写。
        # 挪到这里让所有渠道自动生效，新渠道接入 _maybe_consolidate 即可获得 episode。
        if user_turns >= 2:
            try:
                from ethan.memory.signals import extract_keywords
                all_text = " ".join(m.content for m in session.messages if m.role == "user" and m.content)
                summary = " ".join(
                    m.content[:50] for m in session.messages if m.role == "user" and m.content
                )[:200]
                keywords = extract_keywords(all_text, max_keywords=10)
                ep_store = EpisodeStore(path=user_episodes_path())
                ep_store.add(
                    session_id=session_id,
                    summary=summary,
                    model=model,
                    turn_count=user_turns,
                    keywords=keywords,
                )
            except Exception:
                logger.warning("episode write failed for session %s", session_id, exc_info=True)

        # 注：老 Consolidator.extract_cold + collect_signals 链路已退役。
        # extract_cold 写 facts.json、collect_signals 写 daily/*.jsonl 都已被
        # _run_structured_extraction（5 轮实时抽取写 memory.db）+ 12 点做梦
        # （_read_day_memories 直接读 memory.db）替代，此处不再有沉淀逻辑。
    except Exception:
        logger.exception("_maybe_consolidate failed for session=%s", session_id)


async def _maybe_generate_skill(session_id: str, model: str, user_id: str = "") -> None:
    try:
        from ethan.core.paths import user_sessions_db_path
        from ethan.skills.generator import MIN_TURNS, SkillGenerator
        store = SessionStore(db_path=user_sessions_db_path())
        await store.init()
        session = await store.load(session_id)
        await store.close()
        if not session:
            return
        user_turns = sum(1 for m in session.messages if m.role == "user")
        if user_turns < MIN_TURNS or user_turns % 5 != 0:
            return
        generator = SkillGenerator(model=model, user_id=user_id)
        await generator.maybe_generate(session.messages)
    except Exception:
        logger.exception("_maybe_generate_skill failed for session=%s", session_id)
