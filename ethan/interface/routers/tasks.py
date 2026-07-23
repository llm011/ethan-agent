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

    用于在 3 轮基线之外提前触发抽取，及时修正已有记忆。
    """
    for msg in reversed(session.messages):
        if msg.role == "user" and msg.content:
            return any(kw in msg.content for kw in _CORRECTION_KEYWORDS)
    return False


# 短会话即时触发的 token 门槛：挡掉纯寒暄，避免为招呼语白跑一次付费 LLM 抽取。
# 注意本门槛卡的是线上 lite_model 的 chat 调用（要钱），不是本地模型——所以宁可
# 漏掉极短事实也不滥触发。定 5 而非 3/4：中文四字寒暄（早上好啊/好的收到/哈哈哈哈）
# 恰好都 =4 tok，门槛 ≤4 会把它们全放进去烧钱；实测 5 只误触发极少数边界短语。
# 代价：4 tok 的极短事实（"我叫李明"/"my name is Alex"）在 1-2 轮会话里说一次会漏，
# 但这类信息进 ≥3 轮会话会被 3 轮基线抓到，损失可接受。
_SHORT_SESSION_MIN_TOKENS = 5


def _session_user_tokens(session) -> int:
    """累计 session 内所有 user 消息的 token 数（寒暄过滤用）。"""
    from ethan.memory.embeddings import count_tokens
    return sum(
        count_tokens(msg.content)
        for msg in session.messages
        if msg.role == "user" and msg.content
    )


async def _run_structured_extraction(session, model: str, user_id: str, user_turns: int,
                                     store=None, force: bool = False) -> None:
    """Extract source-backed memories on short turns, then every three turns.

    触发条件（任一即跑）：
    - user_turns <= 2 且 user token >= _SHORT_SESSION_MIN_TOKENS：短会话即时触发。
      否则用户只说一两句就结束的会话（如"我最近在研究机器人"）永远等不到第 3 轮
      门槛，事实丢失；但纯寒暄（hi/hello/嗯）被 token 门槛挡下，不浪费 LLM 调用。
    - user_turns % 3 == 0：3 轮基线节流，长对话按此节奏增量提取。
    - 命中否定/修正关键词：跨轮次纠正及时更新记忆。
    job_key 基于 message_id、boundary 增量去重，保证幂等、不重复抽取。
    store 可注入(测试/评测用);不传则按当前用户路径创建 MemoryStore。
    force=True 时跳过门槛检查（12 点兜底扫描用，已在外层过滤过短会话）。
    """
    if not force and not _has_correction_keyword(session):
        if user_turns % 3 == 0:
            pass  # 3 轮基线节点，触发
        elif user_turns <= 2 and _session_user_tokens(session) >= _SHORT_SESSION_MIN_TOKENS:
            pass  # 短会话且有实质内容，即时触发
        else:
            # 长对话非 3 轮节点，或纯寒暄短会话 → 跳过
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
        # rolling-summary path. Short turns (<3) trigger immediately so a one-liner
        # like "我最近在研究机器人" is captured even if the session ends early;
        # longer sessions keep the three-turn cadence.
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
