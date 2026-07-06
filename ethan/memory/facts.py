"""结构化持久记忆 — 跨 session 的 key facts 存储（Phase 2a）。

每个 fact 带有：
- content: 内容
- confidence: 置信度 (0.0-1.0)
- source: 来源 session ID
- created_at: 创建时间
- last_accessed: 最后访问时间
- category: 分类 (preference/decision/knowledge/correction)
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

    def add(self, content: str, confidence: float = 0.8, source: str = "", category: str = "knowledge") -> None:
        # Check for contradiction against all active facts
        for f in self._facts:
            if not f.superseded and self._is_contradiction(f.content, content):
                f.superseded = True

        existing = self._find_similar(content)
        if existing and not existing.superseded:
            existing.content = content
            existing.confidence = max(existing.confidence, confidence)
            existing.last_accessed = time.time()
        else:
            self._facts.append(Fact(
                content=content,
                confidence=confidence,
                source=source,
                category=category,
            ))
        self._save()

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
