"""Background tasks fired after a generation completes: title, memory consolidation, skill gen."""
from __future__ import annotations

import logging

from ethan.memory.session import SessionStore

logger = logging.getLogger("ethan.tasks")


async def _maybe_regen_title(session_id: str) -> None:
    try:
        from ethan.core.paths import user_sessions_db_path
        from ethan.memory.session import decide_title
        store = SessionStore(db_path=user_sessions_db_path())
        await store.init()
        try:
            session = await store.load(session_id)
            if not session:
                logger.warning("_maybe_regen_title: session %s not found", session_id)
                return
            title = await decide_title(session.messages, session.title)
            if title and title != session.title:
                await store.update_title(session_id, title)
                logger.debug("_maybe_regen_title: updated %s -> %s", session_id, title)
        finally:
            await store.close()
    except Exception:
        logger.exception("_maybe_regen_title failed for session=%s", session_id)


async def _maybe_consolidate(session_id: str, model: str, user_id: str = "", mode: str = "") -> None:
    try:
        # 心理画像是否额外抽取：由当前 mode 自身声明，不在此硬编码模式名
        from ethan.core.modes import resolve_mode
        from ethan.core.paths import user_facts_path, user_sessions_db_path
        from ethan.memory.consolidator import Consolidator
        from ethan.memory.facts import FactStore
        from ethan.memory.working import MemoryConfig, WorkingMemory
        resolve_mode(mode)  # validate mode exists

        store = SessionStore(db_path=user_sessions_db_path())
        await store.init()
        session = await store.load(session_id)
        await store.close()
        if not session:
            return

        user_turns = sum(1 for m in session.messages if m.role == "user")
        if user_turns == 0 or user_turns % 10 != 0:
            return

        memory = WorkingMemory(config=MemoryConfig(hot_size=10))
        fact_store = FactStore(path=user_facts_path())
        memory.cold_facts = fact_store.build_context()

        history = list(session.messages)
        pairs = []
        i = 0
        while i < len(history) - 1:
            if history[i].role == "user" and history[i + 1].role == "assistant":
                pairs.append((history[i], history[i + 1]))
                i += 2
            else:
                i += 1
        for u, a in pairs:
            memory.add_turn(u, a)

        consolidator = Consolidator(main_model=model)
        while memory.needs_compression():
            batch = memory.get_compress_batch()
            summary = await consolidator.compress(batch, memory.warm_summary)
            memory.apply_summary(summary)

        if memory.needs_cold_extraction():
            result = await consolidator.extract_cold(
                memory.warm_summary, memory.cold_facts
            )
            for fact in result["key_facts"]:
                fact_store.add(fact, confidence=0.8, source=session_id)
            from ethan.core.profile import apply_extraction
            apply_extraction(result)
            memory.apply_cold_extraction(fact_store.build_context(), result["condensed"])
    except Exception:
        pass


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
        await generator.maybe_generate(session)
    except Exception:
        pass
