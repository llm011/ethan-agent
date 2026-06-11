"""知识库系统 — 可扩展的外部知识来源。

默认实现：本地 Markdown 文件目录（~/.ethan/knowledge/）。
通过 adapter 机制支持第三方笔记系统（Obsidian 等）。
"""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class KnowledgeItem:
    title: str
    content: str
    source: str  # file path or URL
    tags: list[str]

    def snippet(self, max_len: int = 300) -> str:
        text = re.sub(r"\s+", " ", self.content).strip()
        return text[:max_len] + "…" if len(text) > max_len else text


class KnowledgeBase(ABC):
    @abstractmethod
    def add(self, title: str, content: str, tags: list[str] | None = None) -> str:
        """Add an item. Returns its ID/path."""

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        """Search by keyword."""

    @abstractmethod
    def list_all(self) -> list[KnowledgeItem]:
        """List all items."""

    @abstractmethod
    def get(self, source: str) -> KnowledgeItem | None:
        """Get item by source identifier."""


class FilesystemKnowledgeBase(KnowledgeBase):
    """Markdown files in a local directory."""

    def __init__(self, directory: Path):
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)

    def add(self, title: str, content: str, tags: list[str] | None = None) -> str:
        slug = re.sub(r"[^\w\-]", "-", title.lower())[:50].strip("-")
        path = self._dir / f"{slug}.md"
        i = 1
        while path.exists():
            path = self._dir / f"{slug}-{i}.md"
            i += 1

        tag_line = f"\ntags: {', '.join(tags)}" if tags else ""
        path.write_text(f"# {title}{tag_line}\n\n{content}", encoding="utf-8")
        return str(path)

    def search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        query_words = set(query.lower().split())
        results: list[tuple[int, KnowledgeItem]] = []

        for item in self.list_all():
            text = (item.title + " " + item.content + " " + " ".join(item.tags)).lower()
            score = sum(1 for w in query_words if w in text)
            if score > 0:
                results.append((score, item))

        results.sort(key=lambda x: -x[0])
        return [item for _, item in results[:limit]]

    def list_all(self) -> list[KnowledgeItem]:
        items = []
        for path in sorted(self._dir.glob("*.md")):
            item = self._parse_file(path)
            if item:
                items.append(item)
        return items

    def get(self, source: str) -> KnowledgeItem | None:
        path = Path(source)
        if not path.exists():
            path = self._dir / source
        if path.exists():
            return self._parse_file(path)
        return None

    def _parse_file(self, path: Path) -> KnowledgeItem | None:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            return None

        lines = text.splitlines()
        title = path.stem
        tags: list[str] = []
        content_start = 0

        for i, line in enumerate(lines):
            if line.startswith("# "):
                title = line[2:].strip()
                content_start = i + 1
            elif line.lower().startswith("tags:"):
                raw = line.split(":", 1)[1].strip()
                tags = [t.strip() for t in raw.split(",") if t.strip()]
                content_start = i + 1

        content = "\n".join(lines[content_start:]).strip()
        return KnowledgeItem(title=title, content=content, source=str(path), tags=tags)
