"""Filesystem 知识库后端 — 本地 Markdown 目录 + 可选向量检索。"""
import re
from pathlib import Path

from ._helpers import _safe_subpath, _strip_redundant_title_line
from .contracts import KnowledgeBase, KnowledgeItem


class FilesystemKnowledgeBase(KnowledgeBase):
    """Markdown files in a local directory, with optional vector search."""

    def __init__(self, directory: Path):
        self._dir = directory
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # health_check() will report the issue
        self._vector_store: "VectorStore | None" = None  # noqa: F821 — lazy import, forward ref

    # ── Vector store (lazy) ────────────────────────────────────────────────

    def _get_vector_store(self):
        if self._vector_store is None:
            from ethan.memory.vector_store import VectorStore
            self._vector_store = VectorStore()
        return self._vector_store

    # ── Write ──────────────────────────────────────────────────────────────

    def add(self, title: str, content: str, tags: list[str] | None = None,
            frontmatter: dict | None = None) -> str:
        slug = re.sub(r"[^\w]+", "-", title.lower())[:50].strip("-")
        slug = re.sub(r"-{2,}", "-", slug)  # 双保险：合并残余连续短横线
        # 按 tags[0] 分子目录，支持层级标签（如 "work/coze/prd"）；sanitize 后为空则落根目录
        target_dir = self._dir
        if tags:
            subpath = _safe_subpath(tags[0])
            if subpath:
                target_dir = self._dir / subpath
                target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{slug}.md"
        i = 1
        while path.exists():
            path = target_dir / f"{slug}-{i}.md"
            i += 1

        tag_line = f"\ntags: {', '.join(tags)}" if tags else ""
        content = _strip_redundant_title_line(title, content)
        path.write_text(f"# {title}{tag_line}\n\n{content}", encoding="utf-8")
        return str(path)

    def update(self, source: str, title: str, content: str, tags: list[str] | None = None,
               frontmatter: dict | None = None) -> None:
        # filesystem 后端不支持 front matter，frontmatter 被忽略。
        path = self._resolve_in_dir(source)
        if not path.exists():
            raise FileNotFoundError(f"Knowledge item not found: {source}")
        tag_line = f"\ntags: {', '.join(tags)}" if tags else ""
        content = _strip_redundant_title_line(title, content)
        path.write_text(f"# {title}{tag_line}\n\n{content}", encoding="utf-8")

    def delete(self, source: str) -> None:
        path = self._resolve_in_dir(source)
        if not path.exists():
            raise FileNotFoundError(f"Knowledge item not found: {source}")
        path.unlink()

    # ── Keyword search (existing) ──────────────────────────────────────────

    def search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        return self._keyword_search(query, limit)

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
        for path in sorted(self._dir.rglob("*.md")):
            item = self._parse_file(path)
            if item:
                items.append(item)
        return items

    def get(self, source: str) -> KnowledgeItem | None:
        path = self._resolve_in_dir(source)
        if path.exists():
            return self._parse_file(path)
        return None

    def health_check(self) -> tuple[bool, str]:
        if self._dir.exists() and self._dir.is_dir():
            return True, f"Filesystem knowledge base OK: {self._dir}"
        return False, f"Directory not accessible: {self._dir}"

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
