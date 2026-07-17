"""facts.json → memory.db 一次性迁移（新旧记忆系统融合，facts.json 退役）。

旧 flat-facts 系统的 active fact 迁移为 memories 表的 active 记录：
- 每条带一条 legacy 证据行（source_quote = fact 正文，extractor_version="legacy"）
- 直写 store 绕过 admission（迁移的是已确立事实，无需再过准入；store 层只要求
  ACTIVE 有证据行，不校验 quote 子串——白名单校验在 extractor 层）
- 幂等：memory id 由内容 sha256 决定，重跑跳过已存在记录
- 完成后 facts.json 归档为 facts.json.migrated，并写 meta marker 防止重复归档
- 归档文件永不删除，superseded 的历史 fact 只保留在归档里

入口：
- `ethan serve` 启动时自动对全部用户执行（interface/api.py lifespan）
- 手动：`uv run python scripts/migrate_facts_to_memories.py [--dry-run]`
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ethan.memory.store import MemoryStore

logger = logging.getLogger(__name__)

_MARKER_KEY = "facts_json_migrated_at"

# category → (memory_type, 兜底 dimension)
_CATEGORY_MAP = {
    "preference": ("preference", "preference.communication"),
    "decision": ("decision", "decision.chosen"),
    "correction": ("decision", "decision.correction"),
    "knowledge": ("personal_information", "identity.professional_background"),
}

# 内容关键词 → 更精确的维度（先到先得；猜错只是标签偏差，正文才是召回本体）
_KEYWORD_RULES: tuple[tuple[str, ...], str, str] = (
    (("中文", "英文", "日语", "外语", "语言"), "preference", "preference.language"),
    (("称呼", "叫我", "名字叫"), "personal_information", "identity.preferred_name"),
    (("住在", "定居", "深圳", "北京", "上海", "广州", "杭州"), "personal_information", "identity.location"),
    (("公司", "入职", "腾讯", "字节", "阿里", "华为", "美团"), "personal_information", "identity.organization"),
    (("工程师", "产品经理", "设计师", "岗位", "职位"), "personal_information", "identity.occupation"),
    (("大学", "毕业", "专业是", "学历"), "personal_information", "identity.education"),
    (("编辑器", "IDE", "浏览器", "工具偏好"), "preference", "preference.tools"),
    (("作息", "早上", "晚上", "深夜", "工作时间"), "preference", "preference.schedule"),
    (("沟通", "回复风格", "语气"), "preference", "preference.communication"),
)


def _classify(content: str, category: str) -> tuple[str, str]:
    """(content, 旧 category) → (memory_type, dimension)。"""
    for keywords, memory_type, dimension in _KEYWORD_RULES:
        if any(k in content for k in keywords):
            return memory_type, dimension
    return _CATEGORY_MAP.get(category, ("personal_information", "identity.professional_background"))


def _legacy_id(content: str) -> str:
    digest = hashlib.sha256(f"legacy\x1f{content.strip()}".encode()).hexdigest()[:24]
    return f"mem_legacy_{digest}"


def _legacy_key(content: str) -> str:
    return "legacy_" + hashlib.sha1(content.strip().encode()).hexdigest()[:16]


def migrate_facts_file(facts_path: Path, store: "MemoryStore", *, dry_run: bool = False) -> dict[str, Any]:
    """把单个 facts.json 迁移进指定 MemoryStore。返回统计 dict。"""
    from ethan.memory.records import EvidenceLevel, MemoryDomain, MemoryEvidence, MemoryRecord, MemoryStatus

    stats: dict[str, Any] = {"migrated": 0, "skipped_existing": 0, "skipped_superseded": 0, "archived": False}
    if not facts_path.exists():
        return stats
    if store.get_meta(_MARKER_KEY):
        logger.info("[Migrate] facts.json already migrated (marker present), skip %s", facts_path)
        return stats

    try:
        raw = json.loads(facts_path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("[Migrate] facts.json unparsable, skip: %s", facts_path, exc_info=True)
        return stats
    # 兼容两种历史格式：纯数组 / {"facts": [...]}
    facts = raw if isinstance(raw, list) else raw.get("facts", []) if isinstance(raw, dict) else []

    for fact in facts:
        if not isinstance(fact, dict):
            continue
        content = (fact.get("content") or "").strip()
        if not content:
            continue
        if fact.get("superseded"):
            stats["skipped_superseded"] += 1
            continue
        memory_id = _legacy_id(content)
        if store.get_memory(memory_id):
            stats["skipped_existing"] += 1
            continue
        if dry_run:
            stats["migrated"] += 1
            continue

        memory_type, dimension = _classify(content, fact.get("category", "knowledge"))
        source = str(fact.get("source") or "legacy")
        now = time.time()
        record = MemoryRecord(
            id=memory_id,
            memory_type=memory_type,
            dimension=dimension,
            memory_key=_legacy_key(content),
            content=content,
            memory_domain=MemoryDomain.GENERAL.value,
            status=MemoryStatus.ACTIVE.value,
            evidence_level=EvidenceLevel.INFERRED.value,
            confidence=float(fact.get("confidence", 0.8)),
            importance=0.6,
            source_session_id=source if source != "legacy" else "",
            created_at=float(fact.get("created_at") or now),
            last_recalled_at=fact.get("last_accessed") or None,
        )
        evidence = MemoryEvidence(
            memory_id=memory_id,
            evidence_level=EvidenceLevel.INFERRED.value,
            source_session_id=source,
            source_message_id="",
            source_role="user",
            source_quote=content[:1000],
            extractor_version="legacy",
        )
        store.create_memory_with_evidence(record, [evidence])
        stats["migrated"] += 1

    if not dry_run and stats["migrated"] + stats["skipped_existing"] > 0 or not dry_run and facts:
        store.set_meta(_MARKER_KEY, datetime.now().isoformat(timespec="seconds"))
        archive = facts_path.with_suffix(".json.migrated")
        facts_path.rename(archive)
        stats["archived"] = True
        logger.info("[Migrate] %s: migrated=%d archived → %s", facts_path, stats["migrated"], archive)
    return stats


def migrate_current_user(*, dry_run: bool = False) -> dict[str, Any]:
    """按当前 user context 迁移该用户的 facts.json。"""
    from ethan.core.paths import user_facts_path
    from ethan.memory.store import MemoryStore

    store = MemoryStore()
    try:
        return migrate_facts_file(user_facts_path(), store, dry_run=dry_run)
    finally:
        store.close()


def migrate_all_users(*, dry_run: bool = False) -> dict[str, dict[str, Any]]:
    """遍历全部 profile 逐个迁移（serve 启动钩子用）。"""
    from ethan.core.context import ETHAN_USER_ID
    from ethan.core.users import get_user_store

    results: dict[str, dict[str, Any]] = {}
    for uid in get_user_store().all_user_ids():
        token = ETHAN_USER_ID.set(uid)
        try:
            results[uid] = migrate_current_user(dry_run=dry_run)
        except Exception:
            logger.exception("[Migrate] failed for user %s", uid)
            results[uid] = {"error": True}
        finally:
            ETHAN_USER_ID.reset(token)
    return results
