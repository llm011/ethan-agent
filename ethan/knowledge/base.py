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
    async def semantic_search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        """Search by semantic similarity."""

    @abstractmethod
    def list_all(self) -> list[KnowledgeItem]:
        """List all items."""

    @abstractmethod
    def get(self, source: str) -> KnowledgeItem | None:
        """Get item by source identifier."""

    @abstractmethod
    def update(self, source: str, title: str, content: str, tags: list[str] | None = None) -> None:
        """Update an existing item in place."""


class FilesystemKnowledgeBase(KnowledgeBase):
    """Markdown files in a local directory, with optional vector search."""

    def __init__(self, directory: Path):
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)
        self._vector_store: "VectorStore | None" = None  # noqa: F821 — lazy import, forward ref

    # ── Vector store (lazy) ────────────────────────────────────────────────

    def _get_vector_store(self):
        if self._vector_store is None:
            from ethan.memory.vector_store import VectorStore
            self._vector_store = VectorStore()
        return self._vector_store

    # ── Write ──────────────────────────────────────────────────────────────

    def add(self, title: str, content: str, tags: list[str] | None = None) -> str:
        slug = re.sub(r"[^\w\-]", "-", title.lower())[:50].strip("-")
        path = self._dir / f"{slug}.md"
        i = 1
        while path.exists():
            path = self._dir / f"{slug}-{i}.md"
            i += 1

        tag_line = f"\ntags: {', '.join(tags)}" if tags else ""
        path.write_text(f"# {title}{tag_line}\n\n{content}", encoding="utf-8")
        self._reindex(path, title, content, tags)
        return str(path)

    def _reindex(self, path: Path, title: str, content: str, tags: list[str] | None) -> None:
        """重建该条目的向量索引。best-effort：嵌入不可用/失败时静默跳过，不阻断写入。"""
        try:
            from ethan.memory.embeddings import embed_sync
            text_for_embed = f"{title} {' '.join(tags or [])} {content}"
            embedding = embed_sync(text_for_embed)
            vs = self._get_vector_store()
            vs.add(
                id=str(path),
                text=text_for_embed,
                embedding=embedding,
                metadata={"title": title, "source": str(path), "tags": tags or []},
            )
        except Exception:
            pass  # vector indexing is optional

    def update(self, source: str, title: str, content: str, tags: list[str] | None = None) -> None:
        path = Path(source)
        if not path.exists():
            path = self._dir / source
        if not path.exists():
            raise FileNotFoundError(f"Knowledge item not found: {source}")
        tag_line = f"\ntags: {', '.join(tags)}" if tags else ""
        path.write_text(f"# {title}{tag_line}\n\n{content}", encoding="utf-8")
        self._reindex(path, title, content, tags)

    def append(self, source: str, content: str) -> str:
        """把内容追加到已有条目正文末尾（保留原标题/标签）。返回文件路径。

        与 update（整篇覆盖）互补：适合「再记一条 / 补充一点」的增量场景，不必让模型
        先读全文再回写。中间用空行隔开，确保 markdown 段落分隔正确。
        """
        item = self.get(source)
        if item is None:
            raise FileNotFoundError(f"Knowledge item not found: {source}")
        new_content = (item.content.rstrip() + "\n\n" + content.strip()).strip()
        self.update(item.source, item.title, new_content, tags=item.tags)
        return item.source

    # ── Keyword search (existing) ──────────────────────────────────────────

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

    # ── Semantic search (new) ──────────────────────────────────────────────

    async def semantic_search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        """Vector similarity search using sqlite-vec embeddings."""
        from ethan.memory.embeddings import embed

        query_embedding = await embed(query)
        vs = self._get_vector_store()
        hits = vs.search(query_embedding, limit=limit)

        items: list[KnowledgeItem] = []
        for hit in hits:
            source = hit["metadata"].get("source") or hit["id"]
            item = self.get(source)
            if item:
                items.append(item)
        return items

    # ── Read ───────────────────────────────────────────────────────────────

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
