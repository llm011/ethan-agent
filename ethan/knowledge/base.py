"""知识库系统 — 可扩展的外部知识来源。

默认实现：本地 Markdown 文件目录（~/.ethan/knowledge/）。
通过 adapter 机制支持第三方笔记系统（Obsidian 等）及外部 REST API。
"""
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeItem:
    title: str
    content: str
    source: str  # file path or URL
    tags: list[str]

    def snippet(self, max_len: int = 800) -> str:
        text = re.sub(r"\s+", " ", self.content).strip()
        return text[:max_len] + "…" if len(text) > max_len else text


def _safe_subdir(tag: str) -> str | None:
    """把 tag 清洗为安全的子目录名，防路径穿越。

    只保留 [a-zA-Z0-9_-]，其余替换为 -；空或全为 . 时返回 None（落根目录）。
    """
    name = re.sub(r"[^A-Za-z0-9_\-]", "-", tag).strip("-")
    if not name or name == "." or name == "..":
        return None
    return name


class KnowledgeBase(ABC):
    @abstractmethod
    def add(self, title: str, content: str, tags: list[str] | None = None,
            frontmatter: dict | None = None) -> str:
        """Add an item. Returns its ID/path.

        frontmatter: 仅 Obsidian 后端生效，用于补充 source/url/author 等自定义 front matter 字段；
                     固定字段（title/type/tags/created/updated）仍由后端自动管理，不要在此重复传入。
        """

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
    def update(self, source: str, title: str, content: str, tags: list[str] | None = None,
               frontmatter: dict | None = None) -> None:
        """Update an existing item in place.

        frontmatter: 仅 Obsidian 后端生效，用于补充 source/url/author 等自定义 front matter 字段；
                     固定字段（title/type/tags/created/updated）仍由后端自动管理，不要在此重复传入。
        """

    @abstractmethod
    def delete(self, source: str) -> None:
        """Delete an item by source identifier."""

    @abstractmethod
    def health_check(self) -> tuple[bool, str]:
        """Validate connectivity / accessibility. Returns (ok, message)."""

    def append(self, source: str, content: str) -> str:
        """把内容追加到已有条目正文末尾。默认基于 get+update 实现，子类可 override 优化。"""
        item = self.get(source)
        if item is None:
            raise FileNotFoundError(f"Knowledge item not found: {source}")
        new_content = (item.content.rstrip() + "\n\n" + content.strip()).strip()
        self.update(item.source, item.title, new_content, tags=item.tags)
        return item.source

    def list_tags(self) -> dict[str, int]:
        """列出所有 tag 及出现次数。可选能力，后端按需实现。"""
        raise NotImplementedError(f"{type(self).__name__} does not support list_tags")

    @staticmethod
    def _tokenize_query(query: str) -> set[str]:
        """将查询切分为 token 集合，用于关键词搜索打分。

        - 英文/数字：按空格切分（长度 >= 2 才作为 token）
        - 中文：按 2-gram 切分（"内置浏览器" → {"内置", "置浏", "浏览", "览器"}），
          让查询和文档字面表述不完全一致时也能匹配（如"内置的浏览器"）
        - 完整 query 也作为一个 token（精确匹配加分）
        """
        import re

        query_lower = query.lower().strip()
        if not query_lower:
            return set()

        tokens: set[str] = set()
        for m in re.findall(r"[a-z0-9]+", query_lower):
            if len(m) >= 2:
                tokens.add(m)
        for seg in re.findall(r"[\u4e00-\u9fff]+", query_lower):
            if len(seg) >= 2:
                for i in range(len(seg) - 1):
                    tokens.add(seg[i : i + 2])
            elif len(seg) == 1:
                tokens.add(seg)
        if len(query_lower) >= 2:
            tokens.add(query_lower)
        return tokens

    def _keyword_search(self, query: str, limit: int = 5) -> list["KnowledgeItem"]:
        """通用关键词搜索（2-gram 分词），FilesystemKB 和 ObsidianKB 共用。

        排序策略：标题/文件名命中完整 query 加分远高于正文命中，
        让"内置浏览器"能把标题就是"内置浏览器"的 PRD 文件排到第一，
        而不是被内容里只是提到这个词的其他文件挤掉。
        """
        tokens = self._tokenize_query(query)
        if not tokens:
            return []
        query_lower = query.lower().strip()
        results: list[tuple[int, KnowledgeItem]] = []
        for item in self.list_all():
            filename = Path(item.source).stem.lower()
            title_lower = item.title.lower()
            # 标题/文件名命中完整 query：+20（强偏好）
            # 正文命中完整 query：+5
            # 2-gram 命中：每个 +1
            title_text = title_lower + " " + filename
            content_text = (item.content + " " + " ".join(item.tags)).lower()
            score = sum(1 for t in tokens if t in title_text or t in content_text)
            if query_lower in title_text:
                score += 20
            elif query_lower in content_text:
                score += 5
            if score > 0:
                results.append((score, item))
        results.sort(key=lambda x: -x[0])
        return [item for _, item in results[:limit]]

    def _resolve_in_dir(self, source: str) -> Path:
        """解析 source 为 self._dir 子树内的绝对路径，越界直接拒绝（防路径穿越）。"""
        path = Path(source)
        if not path.is_absolute():
            path = self._dir / source
        resolved = path.resolve()
        try:
            resolved.relative_to(self._dir.resolve())
        except ValueError:
            raise ValueError(f"Path outside knowledge base: {source}")
        return resolved


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
        # 按 tags[0] 分子目录（如 people/、project/），sanitize 后为空则落根目录
        target_dir = self._dir
        if tags:
            subdir = _safe_subdir(tags[0])
            if subdir:
                target_dir = self._dir / subdir
                target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{slug}.md"
        i = 1
        while path.exists():
            path = target_dir / f"{slug}-{i}.md"
            i += 1

        tag_line = f"\ntags: {', '.join(tags)}" if tags else ""
        path.write_text(f"# {title}{tag_line}\n\n{content}", encoding="utf-8")
        return str(path)

    def update(self, source: str, title: str, content: str, tags: list[str] | None = None,
               frontmatter: dict | None = None) -> None:
        # filesystem 后端不支持 front matter，frontmatter 被忽略。
        path = self._resolve_in_dir(source)
        if not path.exists():
            raise FileNotFoundError(f"Knowledge item not found: {source}")
        tag_line = f"\ntags: {', '.join(tags)}" if tags else ""
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


# ── Obsidian Vault 后端 ────────────────────────────────────────────────────


class ObsidianKnowledgeBase(KnowledgeBase):
    """Obsidian vault 作为知识库后端，遵循 Obsidian 约定（YAML frontmatter、wikilinks 等）。"""

    def __init__(self, vault_path: Path, folder: str = "."):
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

    def add(self, title: str, content: str, tags: list[str] | None = None,
            frontmatter: dict | None = None) -> str:
        slug = re.sub(r"[^\w]+", "-", title.lower())[:50].strip("-")
        # 按 tags[0] 分子目录（如 people/、project/），sanitize 后为空则落根目录
        target_dir = self._dir
        if tags:
            subdir = _safe_subdir(tags[0])
            if subdir:
                target_dir = self._dir / subdir
                target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{slug}.md"
        i = 1
        while path.exists():
            path = target_dir / f"{slug}-{i}.md"
            i += 1

        text = self._build_file_content(title, content, tags, frontmatter=frontmatter)
        path.write_text(text, encoding="utf-8")
        return str(path)

    def update(self, source: str, title: str, content: str, tags: list[str] | None = None,
               frontmatter: dict | None = None) -> None:
        path = self._resolve_in_dir(source)
        if not path.exists():
            raise FileNotFoundError(f"Knowledge item not found: {source}")
        # 读取原文件的 created 字段（append/update 时保留创建时间）
        created = self._read_created_from_file(path)
        text = self._build_file_content(title, content, tags, created=created,
                                        frontmatter=frontmatter)
        path.write_text(text, encoding="utf-8")

    def _read_created_from_file(self, path: Path) -> str | None:
        """从已有文件的 front matter 提取 created 字段。

        旧文件可能没有 YAML frontmatter 或没有 created 字段（早期版本不写），
        此时回退到文件 mtime 作为创建日期，避免编辑时把 created 重置为今天，
        导致老笔记的原始创建日期丢失。
        """
        try:
            text = path.read_text(encoding="utf-8")
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    import yaml
                    fm = yaml.safe_load(parts[1]) or {}
                    if isinstance(fm, dict) and fm.get("created"):
                        return str(fm["created"])
        except Exception:
            pass
        # 旧文件无 frontmatter 或无 created 字段：回退到文件 mtime（ISO 日期）
        try:
            from datetime import datetime
            return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
        except OSError:
            return None

    def delete(self, source: str) -> None:
        path = self._resolve_in_dir(source)
        if not path.exists():
            raise FileNotFoundError(f"Knowledge item not found: {source}")
        path.unlink()

    # ── Search ─────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        # 2-gram 关键词搜索对中文更友好（CLI 的 Obsidian 索引对中文分词较弱），
        # CLI 搜索保留作为 list_tags 等其他能力的依赖
        return self._filesystem_search(query, limit)

    def _cli_search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        """使用 Obsidian CLI 的索引搜索（更快更准）。CLI 成功但无结果时返回空，不 fallback。"""
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
                # CLI 可能返回字符串（路径）或字典（{"path": ...}）
                if isinstance(entry, str):
                    path_str = entry
                elif isinstance(entry, dict):
                    path_str = entry.get("path") or entry.get("file", "")
                else:
                    continue
                if not path_str:
                    continue
                path = Path(path_str) if Path(path_str).is_absolute() else self._vault / path_str
                item = self._parse_obsidian_file(path)
                if item:
                    items.append(item)
            # CLI 成功执行（returncode=0 + JSON 可解析）就尊重结果，即使为空。
            # 只有 CLI 异常（超时/JSON 解析失败/非 0 退出）才 fallback。
            return items
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            return self._filesystem_search(query, limit)

    def _filesystem_search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        """纯文件系统关键词搜索（CLI 不可用时的兜底）。"""
        return self._keyword_search(query, limit)

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
        path = self._resolve_in_dir(source)
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

    def _build_file_content(self, title: str, content: str, tags: list[str] | None,
                            created: str | None = None,
                            frontmatter: dict | None = None) -> str:
        """构建 Obsidian 格式 MD 文件（YAML frontmatter + 正文）。

        固定字段：title / type / tags / created / updated
        扩展字段：通过 frontmatter 传入，模型可自由补充 source/url/author 等。
        用 yaml.safe_dump 序列化 frontmatter，确保反斜杠/引号/冒号等特殊字符
        不会破坏 YAML 解析（早期用 repr() 会在含 both ' 和 " 的值上让 YAML 报错）。
        """
        from datetime import date

        import yaml

        today = date.today().isoformat()
        fm: dict = {
            "title": title,
            "created": created or today,
            "updated": today,
        }
        if tags:
            fm["type"] = tags[0]
            fm["tags"] = list(tags)
        # 拒绝固定字段，避免 frontmatter 覆盖自动管理的字段
        reserved = {"title", "type", "tags", "created", "updated"}
        if frontmatter:
            for k, v in frontmatter.items():
                if k not in reserved:
                    fm[k] = v

        # safe_dump 自动处理引号/转义；sort_keys=False 保持稳定字段顺序；
        # allow_unicode=True 避免中文标题被转成 \uXXXX
        fm_text = yaml.safe_dump(
            fm, sort_keys=False, allow_unicode=True, default_flow_style=False
        ).rstrip("\n")

        parts = ["---", fm_text, "---", "", f"# {title}", "", content]
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
                frontmatter_text = parts[1].strip()
                content = parts[2].strip()
                try:
                    import yaml
                    fm = yaml.safe_load(frontmatter_text) or {}
                    if isinstance(fm, dict):
                        if fm.get("title"):
                            title = str(fm["title"]).strip()
                        raw_tags = fm.get("tags", [])
                        if isinstance(raw_tags, list):
                            tags = [str(t).strip() for t in raw_tags if t]
                        elif isinstance(raw_tags, str):
                            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
                except Exception:
                    pass  # YAML 解析失败，降级为默认值

        # 去掉正文中重复的 # title 行
        lines = content.splitlines()
        if lines and lines[0].startswith("# "):
            title = lines[0][2:].strip()
            content = "\n".join(lines[1:]).strip()

        return KnowledgeItem(title=title, content=content, source=str(path), tags=tags)


# ── 外部 REST API 后端 ─────────────────────────────────────────────────────


class ExternalKnowledgeBase(KnowledgeBase):
    """通过 REST API 连接外部知识库服务。

    scene 参数用于按场景隔离（如 'work'/'life'）。客户端会把 scene 作为
    query 参数 / payload 字段传给外部服务；外部服务应按 scene 隔离存储与搜索，
    以履行 knowledge 工具宣称的 "Different scenes are isolated for storage
    and search" 契约。scene 为空时不传该字段，向后兼容。
    """

    def __init__(self, base_url: str, api_key: str = "", headers: dict[str, str] | None = None,
                 scene: str = ""):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._scene = scene
        self._headers = headers or {}
        if api_key:
            self._headers.setdefault("Authorization", f"Bearer {api_key}")

    def _client(self):
        import httpx
        return httpx.Client(base_url=self._base_url, headers=self._headers, timeout=30)

    def _async_client(self):
        import httpx
        return httpx.AsyncClient(base_url=self._base_url, headers=self._headers, timeout=30)

    @staticmethod
    def _encode_source(source: str) -> str:
        """URL-encode source，避免 / # ? 等字符破坏路径。"""
        return quote(str(source), safe="")

    def _scene_params(self, extra: dict | None = None) -> dict:
        """构造 query 参数，scene 非空时附加。"""
        params = dict(extra or {})
        if self._scene:
            params.setdefault("scene", self._scene)
        return params

    def _with_scene(self, payload: dict) -> dict:
        """给 POST/PUT payload 注入 scene 字段（非空时）。"""
        if self._scene:
            return {**payload, "scene": self._scene}
        return payload

    # ── Write ──────────────────────────────────────────────────────────────

    def add(self, title: str, content: str, tags: list[str] | None = None,
            frontmatter: dict | None = None) -> str:
        payload = self._with_scene({"title": title, "content": content, "tags": tags or []})
        if frontmatter:
            payload["frontmatter"] = frontmatter
        with self._client() as client:
            resp = client.post("/items", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("source") or data.get("id") or ""

    def update(self, source: str, title: str, content: str, tags: list[str] | None = None,
               frontmatter: dict | None = None) -> None:
        payload = self._with_scene({"title": title, "content": content, "tags": tags or []})
        if frontmatter:
            payload["frontmatter"] = frontmatter
        with self._client() as client:
            resp = client.put(f"/items/{self._encode_source(source)}", json=payload)
            resp.raise_for_status()

    def delete(self, source: str) -> None:
        with self._client() as client:
            resp = client.delete(
                f"/items/{self._encode_source(source)}", params=self._scene_params()
            )
            resp.raise_for_status()

    # ── Search ─────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        with self._client() as client:
            resp = client.get(
                "/search", params=self._scene_params({"q": query, "limit": limit})
            )
            resp.raise_for_status()
            return self._parse_items(resp.json())

    async def semantic_search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        async with self._async_client() as client:
            resp = await client.get(
                "/search",
                params=self._scene_params({"q": query, "limit": limit, "semantic": "true"}),
            )
            resp.raise_for_status()
            return self._parse_items(resp.json())

    # ── Read ───────────────────────────────────────────────────────────────

    def list_all(self) -> list[KnowledgeItem]:
        with self._client() as client:
            resp = client.get("/items", params=self._scene_params())
            resp.raise_for_status()
            return self._parse_items(resp.json())

    def get(self, source: str) -> KnowledgeItem | None:
        with self._client() as client:
            resp = client.get(
                f"/items/{self._encode_source(source)}", params=self._scene_params()
            )
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
                            return True, f"External KB API reachable (status={resp.status_code}): {self._base_url}"
                    except httpx.HTTPError:
                        continue
                return False, f"External KB API not healthy: {self._base_url}"
        except Exception as e:
            return False, f"External KB API connection failed: {e}"

    # ── Internal ───────────────────────────────────────────────────────────

    def _parse_items(self, data) -> list[KnowledgeItem]:
        """从 API 响应解析条目列表，兼容 {"items": [...]} 或直接 [...] 格式。"""
        if data is None:
            return []
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
