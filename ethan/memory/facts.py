"""结构化持久记忆 — 跨 session 的 key facts 存储（Phase 2a）。

每个 fact 带有：
- content: 内容
- confidence: 置信度 (0.0-1.0)
- source: 来源 session ID
- created_at: 创建时间
- last_accessed: 最后访问时间
- category: 分类 (preference/decision/knowledge/correction)
- tags: 关键词标签列表，用于语义召回（A1）
"""
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from ethan.core.config import CONFIG_DIR

FACTS_FILE = CONFIG_DIR / "memory" / "facts.json"


@dataclass
class Fact:
    content: str
    confidence: float = 0.8
    source: str = ""
    category: str = "knowledge"  # preference | decision | knowledge | correction
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    superseded: bool = False
    tags: list[str] = field(default_factory=list)


class FactStore:
    def __init__(self, path: Path = FACTS_FILE):
        self._path = path
        self._facts: list[Fact] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._facts = [Fact(**f) for f in data]
            except (json.JSONDecodeError, TypeError):
                self._facts = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(f) for f in self._facts]
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, content: str, confidence: float = 0.8, source: str = "", category: str = "knowledge", tags: list[str] | None = None) -> None:
        # 脱敏：防止 secret 真值落入 facts.json
        from ethan.core.secrets_store import mask_text
        content = mask_text(content)
        # Check for contradiction against all active facts
        for f in self._facts:
            if not f.superseded and self._is_contradiction(f.content, content):
                f.superseded = True

        # 自动提取 tags（sync fallback，优先用 add_async 走 LLM）
        if tags is None:
            from ethan.memory.signals import extract_keywords
            tags = extract_keywords(content, max_keywords=6)

        existing = self._find_similar(content)
        if existing and not existing.superseded:
            existing.content = content
            existing.confidence = max(existing.confidence, confidence)
            existing.last_accessed = time.time()
            # 合并 tags（去重）
            if tags:
                existing_tags = set(existing.tags)
                existing.tags = list(existing_tags | set(tags))
        else:
            self._facts.append(Fact(
                content=content,
                confidence=confidence,
                source=source,
                category=category,
                tags=tags,
            ))
        self._save()

    async def add_async(self, content: str, confidence: float = 0.8, source: str = "", category: str = "knowledge", tags: list[str] | None = None) -> None:
        """异步版 add — 用 lite 模型提取高质量 tags。"""
        if tags is None:
            from ethan.memory.signals import extract_keywords_llm
            tags = await extract_keywords_llm(content, max_keywords=6)
        self.add(content, confidence=confidence, source=source, category=category, tags=tags)

    def _is_contradiction(self, old: str, new: str) -> bool:
        """Detect if new content contradicts old (heuristic for both CJK and Latin)."""
        old_lower = old.lower().strip()
        new_lower = new.lower().strip()
        if old_lower == new_lower:
            return False

        # Character-level overlap (works for CJK)
        old_chars = set(old_lower)
        new_chars = set(new_lower)
        char_overlap = len(old_chars & new_chars) / max(len(old_chars), len(new_chars), 1)

        # Word-level overlap (works for Latin)
        old_words = set(old_lower.split())
        new_words = set(new_lower.split())
        word_overlap = len(old_words & new_words) / max(len(old_words), len(new_words), 1)

        overlap = max(char_overlap, word_overlap)

        if overlap > 0.5:
            # Check for update/negation signals
            update_signals = [
                "不", "没", "non", "not", "no longer", "instead",
                "而不是", "改为", "换成", "变成", "更新为", "升级到",
                "changed", "switched", "updated", "migrated",
            ]
            for sig in update_signals:
                if sig in new_lower and sig not in old_lower:
                    return True
            # High overlap but different → likely an update
            if overlap > 0.6 and old_lower != new_lower:
                return True
        return False

    def supersede(self, old_content: str, new_content: str, source: str = "") -> None:
        for f in self._facts:
            if f.content == old_content:
                f.superseded = True
        self.add(new_content, confidence=0.9, source=source, category="knowledge")

    def get_active(self, min_confidence: float = 0.3) -> list[Fact]:
        return [f for f in self._facts if not f.superseded and f.confidence >= min_confidence]

    def build_context(self, max_facts: int = 20) -> str:
        active = self.get_active()
        active.sort(key=lambda f: (-f.confidence, -f.last_accessed))
        top = active[:max_facts]
        if not top:
            return ""

        lines = []
        for f in top:
            lines.append(f"- {f.content}")
        return "\n".join(lines)

    def build_context_with_recall(self, query: str = "", max_facts: int = 15) -> str:
        """按当前对话关键词召回相关 facts（A1）。

        策略：
        1. 提取 query 关键词
        2. 有 tags 的 fact 按 relevance 分数排序，无 tags 的按原 confidence 排序
        3. 相关 facts 优先注入，不足时用 confidence 补齐
        4. 命中的 fact 更新 last_accessed（touch）
        """
        from ethan.memory.signals import extract_keywords, score_relevance

        active = self.get_active()
        if not active:
            return ""

        query_keywords = extract_keywords(query, max_keywords=8) if query else []

        # 打分
        scored = []
        for f in active:
            rel = score_relevance(query_keywords, f.tags) if query_keywords else 0.0
            # 综合分：relevance 权重 0.6，confidence 权重 0.4
            composite = rel * 0.6 + f.confidence * 0.4
            scored.append((composite, rel, f))

        # 先按 relevance 分组：有相关性的优先，无相关性的按 confidence 排
        relevant = [(s, r, f) for s, r, f in scored if r > 0]
        fallback = [(s, r, f) for s, r, f in scored if r == 0]

        relevant.sort(key=lambda x: (-x[0], -x[2].last_accessed))
        fallback.sort(key=lambda x: (-x[2].confidence, -x[2].last_accessed))

        top = (relevant + fallback)[:max_facts]

        if not top:
            return ""

        # touch 命中的 fact:内存里的 last_accessed 总是更新(排序要用),
        # 只有距上次更新超过 60s 才落盘(避免高频 I/O)。
        now = time.time()
        touched = False
        for _, _, f in top:
            if query_keywords and f.tags:
                if now - f.last_accessed > 60:
                    touched = True
                f.last_accessed = now
        if touched:
            self._save()

        lines = []
        for _, _, f in top:
            lines.append(f"- {f.content}")
        return "\n".join(lines)

    def touch(self, content: str) -> None:
        for f in self._facts:
            if f.content == content:
                f.last_accessed = time.time()
                self._save()
                return

    def decay(self, days_threshold: int = 90) -> int:
        now = time.time()
        threshold = now - (days_threshold * 86400)
        removed = 0
        for f in self._facts:
            if f.last_accessed < threshold and f.confidence < 0.5:
                f.superseded = True
                removed += 1
        if removed:
            self._save()
        return removed

    def count(self) -> int:
        return len(self.get_active())

    def _find_similar(self, content: str) -> Optional[Fact]:
        content_lower = content.lower().strip()
        for f in self._facts:
            if f.content.lower().strip() == content_lower:
                return f
            # Simple similarity: if 80%+ of words overlap
            words_new = set(content_lower.split())
            words_old = set(f.content.lower().strip().split())
            if words_new and words_old:
                overlap = len(words_new & words_old) / max(len(words_new), len(words_old))
                if overlap > 0.8:
                    return f
        return None
