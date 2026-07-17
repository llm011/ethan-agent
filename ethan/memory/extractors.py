"""Structured memory extractors — propose typed candidates from conversation.

Design: the LLM only *proposes* candidates as strict JSON. Deterministic code
in :mod:`ethan.memory.admission` decides whether a candidate becomes an active
memory. Every proposal must cite an exact quote that exists in the source
messages, or it is rejected.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from ethan.memory.records import (
    EvidenceLevel,
    MemoryCandidate,
    MemoryDomain,
    MemoryType,
    Sensitivity,
)

logger = logging.getLogger(__name__)

EXTRACTOR_VERSION = "v1"

# Dimensions allowed per memory_type. Anything outside these sets is rejected.
_PERSONAL_DIMENSIONS = {
    "identity.preferred_name", "identity.pronouns", "identity.language",
    "identity.location", "identity.timezone", "identity.occupation",
    "identity.role", "identity.organization", "identity.education",
    "identity.professional_background", "identity.expertise",
    "identity.relationship", "identity.accessibility", "identity.long_term_goal",
}
_PREFERENCE_DIMENSIONS = {
    "preference.communication", "preference.language", "preference.tone",
    "preference.tools", "preference.work_habits", "preference.schedule",
    "preference.content", "preference.decision_tradeoff", "preference.boundary",
    "preference.negative", "preference.response_verbosity",
}
_ACTIVITY_DIMENSIONS = {
    "activity.project", "activity.responsibility", "activity.goal",
    "activity.blocker", "activity.deadline", "activity.waiting",
    "activity.recent_completion",
}
_DECISION_DIMENSIONS = {
    "decision.chosen", "decision.rejected", "decision.rationale",
    "decision.constraint", "decision.commitment", "decision.agreement",
    "decision.deadline", "decision.correction",
}
_RELATIONSHIP_DIMENSIONS = {
    "relationship.role", "relationship.coordination", "relationship.relevance",
}
_METHODOLOGY_DIMENSIONS = {
    "methodology.goal_framing", "methodology.problem_decomposition",
    "methodology.information_gathering", "methodology.analysis_reasoning",
    "methodology.evaluation_criteria", "methodology.decision_style",
    "methodology.execution_workflow", "methodology.tool_usage",
    "methodology.communication_collaboration", "methodology.quality_control",
    "methodology.reflection_improvement",
}
_COMPANION_DIMENSIONS = {
    "companion.current_emotion", "companion.current_stressor",
    "companion.emotional_event", "companion.support_need",
    "companion.soothing_preference", "companion.support_boundary",
    "companion.important_inner_experience", "companion.explicit_value",
    "companion.relationship_context", "companion.requested_follow_up",
}

# 苏念陪伴模式情感提取的完整 system prompt(职责/边界/禁止项/状态机)。
# 维度详解与示例在 _build_prompt 的 companion_block;此处只放约束与规则。
_COMPANION_SYSTEM_PROMPT = (
    "你是苏念陪伴模式的情感记忆提取器。只输出严格 JSON,不要 markdown 代码块、不要解释文字。\n"
    "你只负责提议候选记忆,最终是否写入由系统代码决定。\n"
    "\n"
    "【职责】\n"
    "从陪伴对话中提取用户明确表达的情绪经历、压力源、支持需求和安抚偏好,让后续陪伴更连续。\n"
    "\n"
    "【提取边界】\n"
    "- 本会话是苏念陪伴(companion)模式,情感类记忆走 companion 维度。\n"
    "- 只从用户消息提取;assistant 的发言不能作为用户事实的证据。\n"
    "- 每条候选必须引用用户消息里的原文 quote,且 quote 必须是用户消息的精确子串;无法找到原文支撑就省略该条。\n"
    "- 不从措辞、语气或行为推断人格、心理疾病、依恋类型等标签。\n"
    "- 不把一次短暂情绪固化为稳定个人特征;当前情绪默认标 observed 并尽量给 valid_until。\n"
    "- 情感记忆独立存储、独立召回、独立授权、独立遗忘:memory_domain 一律为 companion,"
    "scope_type=mode,scope_id=companion,sensitivity=high。\n"
    "\n"
    "【禁止提取】\n"
    "- 心理疾病诊断、人格类型、依恋类型(抑郁/抑郁症/焦虑症/双相/强迫症/PTSD/创伤/回避型依恋等):"
    "不允许根据对话推断或贴标签。\n"
    "- 「用户是容易焦虑的人」等稳定人格概括:一次状态不能泛化为长期特征。\n"
    "- 非陪伴模式中的情绪猜测:没有相应用途和用户预期。\n"
    "- 助手提出、用户没有确认的内心动机:助手推测不能成为用户事实。\n"
    "- 与陪伴无关的第三方敏感信息:数据最小化,避免为他人建立不必要档案。\n"
    "- 全量保存陪伴原话:长期记忆只留必要摘要和证据引用。\n"
    "\n"
    "【evidence_level 标级】\n"
    "- observed:一次性情绪或行为(当前情绪默认)。\n"
    "- explicit:用户明确陈述。\n"
    "- corrected:用户明确纠正。\n"
    "- inferred:多个独立陪伴对话重复出现的同一模式。\n"
    "\n"
    "【情感记忆状态机】\n"
    "explicit 当前状态 → episode_emotion(带 valid_until);\n"
    "explicit 支持偏好/边界 → confirmed companion memory;\n"
    "单次 observed pattern → candidate(不默认召回);\n"
    "多个陪伴对话+一致证据 → inferred pattern;\n"
    "用户确认 → confirmed。"
)

# Companion safety: reject diagnostic / personality / clinical labels.
_COMPANION_DENIED_TERMS = {
    "抑郁", "抑郁症", "焦虑症", "人格", "依恋", "创伤", "创伤后", "心理疾病",
    "双相", "强迫症", "分裂", "心理障碍", "诊断", "病理",
    "depression", "anxiety disorder", "personality disorder", "attachment style",
    "trauma", "ptsd", "bipolar", "ocd", "diagnosis", "clinical", "pathological",
}

_VALID_EVIDENCE = {"observed", "inferred", "explicit", "corrected"}
_VALID_SCOPE_TYPES = {"user", "user_domain", "user_skill", "project", "mode"}


@dataclass
class SourceMessage:
    session_id: str
    message_id: int | str
    role: str
    content: str
    created_at: float | None = None

    @classmethod
    def from_message(cls, msg, session_id: str) -> "SourceMessage":
        return cls(
            session_id=session_id,
            message_id=getattr(msg, "id", None) or "",
            role=getattr(msg, "role", ""),
            content=getattr(msg, "content", "") or "",
            created_at=getattr(msg, "created_at", None),
        )


def _extract_json(text: str) -> str:
    """从模型输出里定位 JSON 载荷:容忍 markdown 代码围栏和前后散文。

    模型(尤其经代理转发时)经常无视「不要代码块」指令,用 ```json 包裹输出。
    硬拒绝会让整批候选丢失,所以这里宽松提取。
    """
    t = text.strip()
    if t.startswith("```"):
        lines = [line for line in t.splitlines() if not line.strip().startswith("```")]
        t = "\n".join(lines).strip()
    if t.startswith("{"):
        return t
    start, end = t.find("{"), t.rfind("}")
    if 0 <= start < end:
        return t[start:end + 1]
    return t


def _safe_json_load(text: str) -> Any:
    return json.loads(_extract_json(text))


def _try_parse(raw: str, session_id: str) -> dict | list | None:
    """尝试解析模型输出为 JSON,失败返回 None(由调用方决定是否修复重试)。"""
    try:
        return _safe_json_load(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _validate_dimension(memory_type: str, dimension: str) -> None:
    table = {
        MemoryType.PERSONAL_INFORMATION.value: _PERSONAL_DIMENSIONS,
        MemoryType.PREFERENCE.value: _PREFERENCE_DIMENSIONS,
        MemoryType.ACTIVITY.value: _ACTIVITY_DIMENSIONS,
        MemoryType.DECISION.value: _DECISION_DIMENSIONS,
        MemoryType.RELATIONSHIP.value: _RELATIONSHIP_DIMENSIONS,
        MemoryType.METHODOLOGY.value: _METHODOLOGY_DIMENSIONS,
        MemoryType.COMPANION.value: _COMPANION_DIMENSIONS,
    }
    allowed = table.get(memory_type)
    if allowed is None:
        raise ValueError(f"unsupported memory_type: {memory_type}")
    if dimension not in allowed:
        raise ValueError(f"{memory_type} does not allow dimension: {dimension}")


def _validate_methodology_structured(structured: dict[str, Any]) -> None:
    for key in ("scenario", "trigger"):
        if not str(structured.get(key, "")).strip():
            raise ValueError("methodology requires scenario and trigger")
    for key in ("steps", "heuristics", "preferred_tools", "evaluation_criteria", "anti_patterns", "exceptions"):
        val = structured.get(key, [])
        if not isinstance(val, list):
            raise ValueError(f"methodology.{key} must be a list")


def _contains_denied_term(text: str) -> str | None:
    lowered = text.lower()
    for term in _COMPANION_DENIED_TERMS:
        if term.lower() in lowered:
            return term
    return None


class StructuredMemoryExtractor:
    """Proposes MemoryCandidate records from a batch of conversation messages."""

    def __init__(self, model: str | None = None, provider=None):
        self._model = model
        self._provider = provider

    async def _get_provider(self):
        if self._provider is not None:
            return self._provider
        from ethan.memory.consolidator import get_lite_model
        from ethan.providers.manager import create_provider
        model = self._model or get_lite_model()
        self._provider = create_provider(model)
        return self._provider

    async def extract(
        self,
        messages: list[SourceMessage],
        *,
        session_id: str,
        user_id: str = "",
        mode: str = "",
        job_key: str = "",
    ) -> list[MemoryCandidate]:
        if not messages:
            return []
        provider = await self._get_provider()
        from ethan.providers.base import Message

        is_companion = self._is_companion_mode(mode)
        prompt = self._build_prompt(messages, is_companion=is_companion)
        try:
            resp = await provider.chat(
                [Message(role="user", content=prompt)],
                system=self._system_prompt(is_companion=is_companion),
            )
        except Exception:
            logger.exception("structured extraction LLM call failed (session=%s)", session_id)
            return []

        raw = (resp.content or "").strip()
        if not raw:
            return []
        payload = _try_parse(raw, session_id)
        if payload is None:
            # 修复重试一次:模型偶发输出非法 JSON(未转义引号/尾逗号等),
            # 让它原样保留内容、只修语法。仍失败才放弃,避免整批静默丢失。
            logger.info("structured extraction non-JSON, attempting repair (session=%s)", session_id)
            try:
                repair = await provider.chat(
                    [Message(role="user", content=(
                        "以下文本不是合法 JSON。请原样保留其中全部内容和字段,"
                        "只把语法修正为合法 JSON 输出,不要 markdown 代码块、不要解释:\n\n"
                        f"{raw[:6000]}"
                    ))],
                    system="你是 JSON 修复器。只输出合法 JSON,不要输出任何其他内容。",
                )
                payload = _try_parse((repair.content or "").strip(), session_id)
            except Exception:
                logger.exception("structured extraction repair call failed (session=%s)", session_id)
        if payload is None:
            logger.warning("structured extraction returned non-JSON after repair (session=%s): %r",
                           session_id, raw[:200])
            return []
        if not isinstance(payload, dict):
            logger.warning("structured extraction top-level not object (session=%s)", session_id)
            return []

        return self._build_candidates(
            payload, messages=messages, session_id=session_id, user_id=user_id,
            job_key=job_key, is_companion=is_companion,
        )

    @staticmethod
    def _is_companion_mode(mode: str) -> bool:
        try:
            from ethan.core.modes import resolve_mode
            return resolve_mode(mode).key == "companion"
        except Exception:
            return mode in {"companion", "苏念", "陪伴"}

    @staticmethod
    def _system_prompt(*, is_companion: bool) -> str:
        if is_companion:
            return _COMPANION_SYSTEM_PROMPT
        return (
            "你是结构化记忆提取器。只输出严格 JSON，不要 markdown 代码块、不要解释文字。\n"
            "你只负责提议候选记忆，最终是否写入由系统代码决定。\n"
            "每条候选必须引用用户消息里的原文 quote，且 quote 必须是用户消息的精确子串；"
            "无法找到原文支撑就省略该条。\n"
            "assistant 的发言不能作为用户事实的证据。\n"
            "一次性行为标 observed；用户明确陈述标 explicit；用户明确纠正标 corrected。\n"
            "不要把单次行为泛化为稳定人格特征。\n"
            "scope_type 只能是 user/user_domain/user_skill/project/mode 之一。"
            "\n本会话不是陪伴模式，禁止输出 companion 维度的情感类记忆。"
        )

    @staticmethod
    def _build_prompt(messages: list[SourceMessage], *, is_companion: bool) -> str:
        lines = []
        for m in messages:
            role = "用户" if m.role == "user" else "助手" if m.role == "assistant" else m.role
            lines.append(f"[msg_id={m.message_id} role={role}] {m.content[:1200]}")
        transcript = "\n".join(lines)

        companion_block = (
            "\n【companion 维度(仅陪伴模式提取,共 10 类)】\n"
            "- companion.current_emotion 当前情绪:用户明确说出的当前感受、强度和时间。"
            "In-episode/带 TTL,默认不晋升稳定特征。示例:「最近因为发布延期感到焦虑」。\n"
            "- companion.emotional_event 情绪事件:引发感受的具体事件及必要上下文,"
            "作为历史情节保留、不泛化人格。示例:「评审中的否定让用户感到挫败」。\n"
            "- companion.current_stressor 压力源/困扰:明确、重复出现的压力源或担忧;"
            "用户明确说明长期存在或多次重复才晋升。示例:「不确定的截止时间会持续带来压力」。\n"
            "- companion.support_need 当下支持需求:用户当前希望被倾听、澄清、陪伴还是获得建议;"
            "仅用户明确说「以后这种情况……」才晋升。示例:「这次只想说说,不需要方案」。\n"
            "- companion.soothing_preference 安抚偏好:哪些回应方式确实有帮助或令人不适;"
            "用户明确评价或纠正才确认。示例:「先确认感受再讨论方案会更舒服」。\n"
            "- companion.support_boundary 情感边界:用户不希望讨论、追问或使用的表达方式;"
            "用户明确设定边界。示例:「不希望被追问家庭细节」。\n"
            "- companion.explicit_value 价值/意义:用户明确表达的重要价值、信念或内心意义;"
            "必须用户直接陈述,高敏感可要求确认。示例:「用户很看重自主选择」。\n"
            "- companion.important_inner_experience 重要内心经历:对用户有长期影响的内心经历或体验。"
            "示例:「第一次被裁让用户很久不敢放松」。\n"
            "- companion.relationship_context 关系上下文:与当前困扰长期相关的人和关系,"
            "仅保存服务所需最小信息。示例:「某位同事是当前项目合作方」。\n"
            "- companion.requested_follow_up 后续跟进请求:用户明确拜托后续记挂/回访的事。"
            "示例:「下周问问我发版顺不顺利」。\n"
        ) if is_companion else ""

        return (
            "从以下对话中提取值得长期记住的结构化记忆候选。严格按 JSON 输出：\n"
            '{"candidates":[{'
            '"memory_type":"personal_information|preference|activity|decision|relationship|methodology|companion",'
            '"dimension":"...","memory_key":"稳定标识","content":"自包含描述",'
            '"evidence_level":"observed|inferred|explicit|corrected",'
            '"scope_type":"user|user_domain|user_skill|project|mode","scope_id":"...",'
            '"message_id":<引用的 msg_id>,"quote":"用户原文精确子串",'
            '"confidence":0~1,"importance":0~1,"valid_until":<unix秒或null>,'
            '"structured":{...}'
            "}]}\n\n"
            "person 维度示例: identity.preferred_name / identity.occupation / identity.expertise / "
            "preference.communication / preference.negative / activity.project / activity.blocker / "
            "decision.chosen / decision.rationale\n"
            "methodology 维度限: methodology.goal_framing/methodology.problem_decomposition/methodology.information_gathering/"
            "methodology.analysis_reasoning/methodology.evaluation_criteria/methodology.decision_style/methodology.execution_workflow/methodology.tool_usage/"
            "methodology.communication_collaboration/methodology.quality_control/methodology.reflection_improvement；"
            "structured 必含 scenario,trigger,steps,heuristics,evaluation_criteria,anti_patterns。"
            "dimension 必须完整照抄上述维度名(含 memory_type 前缀),不得省略前缀、不得自造。\n"
            f"{companion_block}\n\n"
            f"对话：\n{transcript}"
        )

    def _build_candidates(
        self, payload: dict[str, Any], *, messages: list[SourceMessage],
        session_id: str, user_id: str, job_key: str, is_companion: bool,
    ) -> list[MemoryCandidate]:
        items = payload.get("candidates", [])
        if not isinstance(items, list):
            return []
        by_id = {str(m.message_id): m for m in messages if m.message_id != ""}
        candidates: list[MemoryCandidate] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                cand = self._build_one(
                    item, by_id=by_id, session_id=session_id, user_id=user_id,
                    job_key=job_key, is_companion=is_companion,
                )
            except ValueError as exc:
                logger.info("rejecting candidate (%s): %r", exc, item)
                continue
            if cand is not None:
                candidates.append(cand)
        return candidates

    def _build_one(
        self, item: dict[str, Any], *, by_id: dict[str, SourceMessage],
        session_id: str, user_id: str, job_key: str, is_companion: bool,
    ) -> MemoryCandidate | None:
        memory_type = str(item.get("memory_type", "")).strip()
        dimension = str(item.get("dimension", "")).strip()
        memory_key = str(item.get("memory_key", "")).strip()
        content = str(item.get("content", "")).strip()
        evidence_level = str(item.get("evidence_level", "observed")).strip()
        scope_type = str(item.get("scope_type", "user")).strip()
        scope_id = str(item.get("scope_id", "self")).strip()
        quote = str(item.get("quote", "")).strip()
        message_id = str(item.get("message_id", "")).strip()

        if not (memory_type and dimension and memory_key and content and quote):
            raise ValueError("missing required field")
        if evidence_level not in _VALID_EVIDENCE:
            raise ValueError(f"invalid evidence_level: {evidence_level}")
        if scope_type not in _VALID_SCOPE_TYPES:
            raise ValueError(f"invalid scope_type: {scope_type}")
        if scope_type == "user":
            scope_id = "self"
        elif not scope_id:
            raise ValueError(f"scope_id required for {scope_type}")

        # Companion domain/type coupling.
        is_companion_type = memory_type == MemoryType.COMPANION.value
        if is_companion_type and not is_companion:
            raise ValueError("companion memory_type outside companion mode")
        if is_companion_type:
            memory_domain = MemoryDomain.COMPANION.value
            sensitivity = Sensitivity.SENSITIVE.value
        else:
            memory_domain = MemoryDomain.GENERAL.value
            sensitivity = Sensitivity.NORMAL.value
            if memory_type == MemoryType.COMPANION.value:
                raise ValueError("companion type requires companion mode")

        _validate_dimension(memory_type, dimension)

        structured = item.get("structured", {})
        if not isinstance(structured, dict):
            raise ValueError("structured must be an object")
        if memory_type == MemoryType.METHODOLOGY.value:
            _validate_methodology_structured(structured)

        # Companion safety: reject diagnostic / personality labels anywhere in content.
        if is_companion_type:
            denied = _contains_denied_term(content) or _contains_denied_term(json.dumps(structured, ensure_ascii=False))
            if denied:
                raise ValueError(f"companion content contains denied term: {denied}")

        # Provenance + quote verification.
        source = by_id.get(message_id)
        if source is None:
            raise ValueError(f"message_id {message_id} not found in source batch")
        if quote not in source.content:
            raise ValueError("quote is not an exact substring of the source message")

        # Only user messages can evidence personal facts; corrections must come from user too.
        if source.role != "user" and memory_type in {
            MemoryType.PERSONAL_INFORMATION.value, MemoryType.PREFERENCE.value,
            MemoryType.ACTIVITY.value, MemoryType.DECISION.value,
            MemoryType.RELATIONSHIP.value, MemoryType.METHODOLOGY.value,
            MemoryType.COMPANION.value,
        }:
            raise ValueError(f"{memory_type} evidence must come from a user message")

        confidence = self._clamp(float(item.get("confidence", 0.6)))
        importance = self._clamp(float(item.get("importance", 0.5)))
        # Single behavioural observation must stay a low-confidence candidate.
        if evidence_level == EvidenceLevel.OBSERVED.value:
            confidence = min(confidence, 0.6)

        valid_until = item.get("valid_until")
        if valid_until not in (None, "", 0):
            try:
                valid_until = float(valid_until)
            except (TypeError, ValueError):
                valid_until = None
        else:
            valid_until = None

        return MemoryCandidate(
            memory_type=memory_type,
            dimension=dimension,
            memory_key=memory_key,
            content=content,
            structured_data=structured,
            scope_type=scope_type,
            scope_id=scope_id,
            memory_domain=memory_domain,
            evidence_level=evidence_level,
            source_session_id=session_id,
            source_message_id=message_id,
            source_role=source.role,
            source_quote=quote,
            confidence=confidence,
            importance=importance,
            sensitivity=sensitivity,
            valid_until=valid_until,
            extractor_name="structured_memory",
            extractor_version=EXTRACTOR_VERSION,
            extraction_job_key=job_key,
            user_id=user_id,
        )

    @staticmethod
    def _clamp(value: float) -> float:
        if value < 0:
            return 0.0
        if value > 1:
            return 1.0
        return value
