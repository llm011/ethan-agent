"""知识库系统 — 可扩展的外部知识来源。

默认实现：本地 Markdown 文件目录（~/.ethan/knowledge/）。
通过 adapter 机制支持第三方笔记系统（Obsidian 等）及外部 REST API。
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

    @abstractmethod
    def delete(self, source: str) -> None:
        """Delete an item by source identifier."""

    @abstractmethod
    def health_check(self) -> tuple[bool, str]:
        """Validate connectivity / accessibility. Returns (ok, message)."""


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

    def delete(self, source: str) -> None:
        path = Path(source)
        if not path.exists():
            path = self._dir / source
        if not path.exists():
            raise FileNotFoundError(f"Knowledge item not found: {source}")
        path.unlink()

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


# ── Obsidian Vault 后端 ────────────────────────────────────────────────────


class ObsidianKnowledgeBase(KnowledgeBase):
    """Obsidian vault 作为知识库后端，遵循 Obsidian 约定（YAML frontmatter、wikilinks 等）。"""

    def __init__(self, vault_path: Path, folder: str = "Knowledge"):
        self._vault = vault_path
        self._folder = folder
        self._dir = vault_path / folder
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # health_check() will report the issue
        self._vector_store: "VectorStore | None" = None  # noqa: F821
        import shutil
        self._cli_available = shutil.which("obsidian") is not None

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

        text = self._build_file_content(title, content, tags)
        path.write_text(text, encoding="utf-8")
        self._reindex(path, title, content, tags)
        return str(path)

    def update(self, source: str, title: str, content: str, tags: list[str] | None = None) -> None:
        path = Path(source)
        if not path.exists():
            path = self._dir / source
        if not path.exists():
            raise FileNotFoundError(f"Knowledge item not found: {source}")
        text = self._build_file_content(title, content, tags)
        path.write_text(text, encoding="utf-8")
        self._reindex(path, title, content, tags)

    def delete(self, source: str) -> None:
        path = Path(source)
        if not path.exists():
            path = self._dir / source
        if not path.exists():
            raise FileNotFoundError(f"Knowledge item not found: {source}")
        path.unlink()

    def append(self, source: str, content: str) -> str:
        """把内容追加到已有条目正文末尾（保留原标题/标签）。"""
        item = self.get(source)
        if item is None:
            raise FileNotFoundError(f"Knowledge item not found: {source}")
        new_content = (item.content.rstrip() + "\n\n" + content.strip()).strip()
        self.update(item.source, item.title, new_content, tags=item.tags)
        return item.source

    # ── Search ─────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        if self._cli_available:
            return self._cli_search(query, limit)
        return self._filesystem_search(query, limit)

    def _cli_search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        """使用 Obsidian CLI 的索引搜索（更快更准）。"""
        import json
        import subprocess
        try:
            result = subprocess.run(
                ["obsidian", "search", f"query={query}", "--json"],
                capture_output=True, text=True, timeout=10,
                cwd=str(self._vault),
            )
            if result.returncode != 0:
                return self._filesystem_search(query, limit)

            # 尝试解析 JSON 输出
            data = json.loads(result.stdout)
            items: list[KnowledgeItem] = []
            results_list = data if isinstance(data, list) else data.get("results", [])
            for entry in results_list[:limit]:
                path_str = entry.get("path") or entry.get("file", "")
                if not path_str:
                    continue
                path = Path(path_str) if Path(path_str).is_absolute() else self._vault / path_str
                item = self._parse_obsidian_file(path)
                if item:
                    items.append(item)
            return items if items else self._filesystem_search(query, limit)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            return self._filesystem_search(query, limit)

    def _filesystem_search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        """纯文件系统关键词搜索（CLI 不可用时的兜底）。"""
        query_words = set(query.lower().split())
        results: list[tuple[int, KnowledgeItem]] = []

        for item in self.list_all():
            text = (item.title + " " + item.content + " " + " ".join(item.tags)).lower()
            score = sum(1 for w in query_words if w in text)
            if score > 0:
                results.append((score, item))

        results.sort(key=lambda x: -x[0])
        return [item for _, item in results[:limit]]

    async def semantic_search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
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
            item = self._parse_obsidian_file(path)
            if item:
                items.append(item)
        return items

    def get(self, source: str) -> KnowledgeItem | None:
        path = Path(source)
        if not path.exists():
            path = self._dir / source
        if path.exists():
            return self._parse_obsidian_file(path)
        return None

    def health_check(self) -> tuple[bool, str]:
        if not self._vault.exists():
            return False, f"Obsidian vault path not found: {self._vault}"
        if not self._vault.is_dir():
            return False, f"Obsidian vault path is not a directory: {self._vault}"
        # 验证 .obsidian 目录存在（确认是合法 vault）
        if not (self._vault / ".obsidian").exists():
            return False, f"Not a valid Obsidian vault (missing .obsidian/): {self._vault}"
        if not self._dir.exists():
            return False, f"Knowledge folder not found: {self._dir}"
        cli_status = "CLI ✓" if self._cli_available else "CLI ✗ (filesystem fallback)"
        return True, f"Obsidian vault OK: {self._vault} (folder: {self._folder}) [{cli_status}]"

    def list_tags(self) -> dict[str, int]:
        """列出 vault 中所有 tag 及出现次数。CLI 可用时使用 obsidian tags counts。"""
        if self._cli_available:
            return self._cli_list_tags()
        return self._filesystem_list_tags()

    def _cli_list_tags(self) -> dict[str, int]:
        """通过 CLI 获取 tag 列表。"""
        import json
        import subprocess
        try:
            result = subprocess.run(
                ["obsidian", "tags", "counts", "--json"],
                capture_output=True, text=True, timeout=10,
                cwd=str(self._vault),
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    return data
                # 如果是列表格式 [{tag, count}, ...]
                if isinstance(data, list):
                    return {item["tag"]: item.get("count", 1) for item in data if "tag" in item}
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            pass
        return self._filesystem_list_tags()

    def _filesystem_list_tags(self) -> dict[str, int]:
        """通过扫描文件 frontmatter 获取 tag 列表（兜底）。"""
        tag_counts: dict[str, int] = {}
        for item in self.list_all():
            for tag in item.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        return tag_counts

# ── Internal ───────────────────────────────────────────────────────────

    def _build_file_content(self, title: str, content: str, tags: list[str] | None) -> str:
        """构建 Obsidian 格式 MD 文件（YAML frontmatter + 正文）。"""
        parts = ["---"]
        parts.append(f"title: {title}")
        if tags:
            parts.append("tags:")
            for t in tags:
                parts.append(f"  - {t}")
        parts.append("---")
        parts.append("")
        parts.append(f"# {title}")
        parts.append("")
        parts.append(content)
        return "\n".join(parts)

    def _parse_obsidian_file(self, path: Path) -> KnowledgeItem | None:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            return None

        title = path.stem
        tags: list[str] = []
        content = text

        # 解析 YAML frontmatter
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                frontmatter = parts[1].strip()
                content = parts[2].strip()
                for line in frontmatter.splitlines():
                    line_s = line.strip()
                    if line_s.startswith("title:"):
                        title = line_s[6:].strip().strip("'\"")
                    elif line_s.startswith("- ") and tags is not None:
                        # tag item in YAML list
                        tags.append(line_s[2:].strip())
                    elif line_s.startswith("tags:") and "[" in line_s:
                        # inline tags: [tag1, tag2]
                        raw = line_s.split("[", 1)[1].rstrip("]")
                        tags = [t.strip().strip("'\"") for t in raw.split(",") if t.strip()]

        # 去掉正文中重复的 # title 行
        lines = content.splitlines()
        if lines and lines[0].startswith("# "):
            title = lines[0][2:].strip()
            content = "\n".join(lines[1:]).strip()

        return KnowledgeItem(title=title, content=content, source=str(path), tags=tags)

    def _reindex(self, path: Path, title: str, content: str, tags: list[str] | None) -> None:
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
            pass


# ── 外部 REST API 后端 ─────────────────────────────────────────────────────


class ExternalKnowledgeBase(KnowledgeBase):
    """通过 REST API 连接外部知识库服务。"""

    def __init__(self, base_url: str, api_key: str = "", headers: dict[str, str] | None = None):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._headers = headers or {}
        if api_key:
            self._headers.setdefault("Authorization", f"Bearer {api_key}")

    def _client(self):
        import httpx
        return httpx.Client(base_url=self._base_url, headers=self._headers, timeout=30)

    def _async_client(self):
        import httpx
        return httpx.AsyncClient(base_url=self._base_url, headers=self._headers, timeout=30)

    # ── Write ──────────────────────────────────────────────────────────────

    def add(self, title: str, content: str, tags: list[str] | None = None) -> str:
        with self._client() as client:
            resp = client.post("/items", json={"title": title, "content": content, "tags": tags or []})
            resp.raise_for_status()
            data = resp.json()
            return data.get("source") or data.get("id") or ""

    def update(self, source: str, title: str, content: str, tags: list[str] | None = None) -> None:
        with self._client() as client:
            resp = client.put(f"/items/{source}", json={"title": title, "content": content, "tags": tags or []})
            resp.raise_for_status()

    def delete(self, source: str) -> None:
        with self._client() as client:
            resp = client.delete(f"/items/{source}")
            resp.raise_for_status()

    def append(self, source: str, content: str) -> str:
        """追加内容到已有条目（通过 get + update 实现）。"""
        item = self.get(source)
        if item is None:
            raise FileNotFoundError(f"Knowledge item not found: {source}")
        new_content = (item.content.rstrip() + "\n\n" + content.strip()).strip()
        self.update(item.source, item.title, new_content, tags=item.tags)
        return item.source

    # ── Search ─────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        with self._client() as client:
            resp = client.get("/search", params={"q": query, "limit": limit})
            resp.raise_for_status()
            return self._parse_items(resp.json())

    async def semantic_search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        async with self._async_client() as client:
            resp = await client.get("/search", params={"q": query, "limit": limit, "semantic": "true"})
            resp.raise_for_status()
            return self._parse_items(resp.json())

    # ── Read ───────────────────────────────────────────────────────────────

    def list_all(self) -> list[KnowledgeItem]:
        with self._client() as client:
            resp = client.get("/items")
            resp.raise_for_status()
            return self._parse_items(resp.json())

    def get(self, source: str) -> KnowledgeItem | None:
        with self._client() as client:
            resp = client.get(f"/items/{source}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return KnowledgeItem(
                title=data.get("title", ""),
                content=data.get("content", ""),
                source=data.get("source") or data.get("id") or source,
                tags=data.get("tags") or [],
            )

    def health_check(self) -> tuple[bool, str]:
        import httpx
        try:
            with self._client() as client:
                # 尝试 /health 端点，退而求其次 /
                for endpoint in ("/health", "/"):
                    try:
                        resp = client.get(endpoint)
                        if resp.status_code < 500:
                            return True, f"External KB API reachable: {self._base_url}"
                    except httpx.HTTPError:
                        continue
                return False, f"External KB API not healthy: {self._base_url}"
        except Exception as e:
            return False, f"External KB API connection failed: {e}"


    # ── Internal ───────────────────────────────────────────────────────────

    def _parse_items(self, data) -> list[KnowledgeItem]:
        """从 API 响应解析条目列表，兼容 {"items": [...]} 或直接 [...] 格式。"""
        items_raw = data if isinstance(data, list) else data.get("items") or data.get("results") or []
        items = []
        for d in items_raw:
            items.append(KnowledgeItem(
                title=d.get("title", ""),
                content=d.get("content", ""),
                source=d.get("source") or d.get("id") or "",
                tags=d.get("tags") or [],
            ))
        return items
