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
    """把 tag 清洗为安全的**单级**子目录名，防路径穿越。

    只保留 [a-zA-Z0-9_-]，其余替换为 -；空或全为 . 时返回 None（落根目录）。
    保留此函数向后兼容；多层级请用 _safe_subpath。
    """
    name = re.sub(r"[^A-Za-z0-9_\-]", "-", tag).strip("-")
    if not name or name == "." or name == "..":
        return None
    return name


def _safe_subpath(tag: str) -> Path | None:
    """把带 `/` 的层级 tag 清洗为安全的**多级**相对路径（防穿越）。

    例：`work/coze/prd` → Path("work/coze/prd")，落盘成嵌套目录，与 Obsidian
    的层级标签约定打平。规则：
    - 按 `/` 分段（`\\` 也视作分隔符，Windows 路径归一）
    - 每段**保留 Unicode 字母/数字/下划线/连字符/空格**（含中文，与 Obsidian 打平），
      仅把文件系统危险字符（`/ \\ : * ? " < > | ` 及控制符）替换为 `-`，去首尾 `-`/空格
    - 空段、`.`、`..`、纯 `.` 序列跳过（防路径穿越）
    - 所有段都为空时返回 None（落根目录）
    """
    segments: list[str] = []
    for raw in re.split(r"[\\/]", str(tag)):
        # 只替换危险字符，保留 CJK 等 Unicode 文字
        name = re.sub(r'[\x00-\x1f<>:"|?*]', "-", raw)
        name = re.sub(r"-{2,}", "-", name).strip("- ")
        if not name or set(name) == {"."}:  # 空、"."、".." 等纯点段
            continue
        segments.append(name)
    if not segments:
        return None
    return Path(*segments)


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
        slug = re.sub(r"-{2,}", "-", slug)  # 双保险：合并残余连续短横线
        # 按 tags[0] 分子目录，支持层级标签（如 "work/coze/prd" → work/coze/prd/）；
        # sanitize 后为空则落根目录
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


# ── Notion 后端 ────────────────────────────────────────────────────────────


_NOTION_VERSION = "2022-06-28"
_NOTION_TEXT_LIMIT = 1900  # Notion rich_text 单块上限 2000，留余量
_NOTION_MAX_CHILDREN = 100  # Notion 单次创建/追加 children 的上限


class NotionKnowledgeBase(KnowledgeBase):
    """Notion 作为知识库后端。

    模型：一个 root page 作为知识库根，每个条目是 root 下的一个 **child page**。
    层级标签（tags[0] 如 "work/coze/prd"）会在 root 下按段创建/复用中间 page，
    条目落在最深一级，与 filesystem/Obsidian 的多层级目录打平。

    - title  → child page 标题
    - content→ 页面正文（markdown 按段落/标题转 Notion blocks，超长自动分块）
    - tags   → 正文顶部一行 `Tags: a, b` 记录（Notion 普通 page 无自定义属性）
    - source → Notion page id（32 位 hex，可带连字符）

    scene 隔离：scene 非空时在 root 下先建一层 `{scene}` page 作为该场景子根。
    """

    def __init__(self, token: str, root_page_id: str, scene: str = ""):
        self._token = token
        self._root_page_id = (root_page_id or "").replace("-", "")
        self._scene = scene
        self._api = "https://api.notion.com/v1"

    # ── HTTP ─────────────────────────────────────────────────────────────
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _client(self):
        import httpx
        return httpx.Client(base_url=self._api, headers=self._headers(), timeout=30)

    # ── markdown ⇄ blocks ────────────────────────────────────────────────
    @staticmethod
    def _text_chunks(s: str) -> list[str]:
        return [s[i:i + _NOTION_TEXT_LIMIT] for i in range(0, len(s), _NOTION_TEXT_LIMIT)] or [""]

    @classmethod
    def _md_to_blocks(cls, content: str) -> list[dict]:
        """极简 markdown → Notion blocks：# 标题 → heading，其余按行 → paragraph。

        不追求完整还原，只保证内容可读、可往返（get 再拼回纯文本）。
        不做数量截断——超过单次 API 上限的部分由调用方分批写入（见 _write_children_batched）。
        """
        blocks: list[dict] = []
        for line in content.splitlines():
            stripped = line.rstrip()
            if not stripped:
                blocks.append({"object": "block", "type": "paragraph",
                               "paragraph": {"rich_text": []}})
                continue
            btype = "paragraph"
            text = stripped
            for lvl, mark in ((3, "### "), (2, "## "), (1, "# ")):
                if stripped.startswith(mark):
                    btype = f"heading_{lvl}"
                    text = stripped[len(mark):]
                    break
            rich = [{"type": "text", "text": {"content": c}} for c in cls._text_chunks(text)]
            blocks.append({"object": "block", "type": btype, btype: {"rich_text": rich}})
        return blocks

    @staticmethod
    def _write_children_batched(client, parent_id: str, blocks: list[dict]) -> None:
        """把 blocks 分批 append 到 parent，绕过 Notion 单次 100 children 上限。

        长笔记不再静默丢内容：超过 100 块的部分按批次续写。
        """
        for i in range(0, len(blocks), _NOTION_MAX_CHILDREN):
            batch = blocks[i:i + _NOTION_MAX_CHILDREN]
            client.patch(f"/blocks/{parent_id}/children",
                         json={"children": batch}).raise_for_status()

    @staticmethod
    def _all_child_blocks(client, parent_id: str) -> list[dict]:
        """翻页取回 parent 下**全部** child block（不止前 100），供读取/删除用。"""
        out: list[dict] = []
        cursor = None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            resp = client.get(f"/blocks/{parent_id}/children", params=params)
            resp.raise_for_status()
            data = resp.json()
            out.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return out

    @staticmethod
    def _blocks_to_text(blocks: list[dict]) -> str:
        lines: list[str] = []
        for b in blocks:
            t = b.get("type", "")
            payload = b.get(t, {})
            rich = payload.get("rich_text", []) if isinstance(payload, dict) else []
            text = "".join(r.get("plain_text") or r.get("text", {}).get("content", "") for r in rich)
            if t == "heading_1":
                lines.append(f"# {text}")
            elif t == "heading_2":
                lines.append(f"## {text}")
            elif t == "heading_3":
                lines.append(f"### {text}")
            else:
                lines.append(text)
        return "\n".join(lines).strip()

    # ── 层级容器 page 解析/创建 ───────────────────────────────────────────
    def _child_pages(self, parent_id: str) -> list[dict]:
        """返回 parent 下所有 child_page 块 [{id, title}]。"""
        out: list[dict] = []
        cursor = None
        with self._client() as c:
            while True:
                params = {"page_size": 100}
                if cursor:
                    params["start_cursor"] = cursor
                resp = c.get(f"/blocks/{parent_id}/children", params=params)
                resp.raise_for_status()
                data = resp.json()
                for blk in data.get("results", []):
                    if blk.get("type") == "child_page":
                        out.append({"id": blk["id"].replace("-", ""),
                                    "title": blk["child_page"].get("title", "")})
                if not data.get("has_more"):
                    break
                cursor = data.get("next_cursor")
        return out

    def _find_or_create_container(self, parent_id: str, title: str) -> str:
        for p in self._child_pages(parent_id):
            if p["title"] == title:
                return p["id"]
        with self._client() as c:
            resp = c.post("/pages", json={
                "parent": {"page_id": parent_id},
                "properties": {"title": {"title": [{"text": {"content": title}}]}},
            })
            resp.raise_for_status()
            return resp.json()["id"].replace("-", "")

    def _resolve_parent(self, tags: list[str] | None) -> str:
        """根据 scene + tags[0] 层级解析出条目应挂载的父 page id（沿途创建容器）。"""
        parent = self._root_page_id
        if self._scene:
            parent = self._find_or_create_container(parent, self._scene)
        if tags:
            subpath = _safe_subpath(tags[0])
            if subpath:
                for seg in subpath.parts:
                    parent = self._find_or_create_container(parent, seg)
        return parent

    # ── Write ────────────────────────────────────────────────────────────
    def add(self, title: str, content: str, tags: list[str] | None = None,
            frontmatter: dict | None = None) -> str:
        parent = self._resolve_parent(tags)
        body = content
        if tags:
            body = f"Tags: {', '.join(tags)}\n\n{content}"
        blocks = self._md_to_blocks(body)
        with self._client() as c:
            # 建页时最多带 100 个 children，其余分批 append，避免长笔记尾部丢失
            resp = c.post("/pages", json={
                "parent": {"page_id": parent},
                "properties": {"title": {"title": [{"text": {"content": title}}]}},
                "children": blocks[:_NOTION_MAX_CHILDREN],
            })
            resp.raise_for_status()
            pid = resp.json()["id"].replace("-", "")
            if len(blocks) > _NOTION_MAX_CHILDREN:
                self._write_children_batched(c, pid, blocks[_NOTION_MAX_CHILDREN:])
            return pid

    def update(self, source: str, title: str, content: str, tags: list[str] | None = None,
               frontmatter: dict | None = None) -> None:
        pid = source.replace("-", "")
        body = content
        if tags:
            body = f"Tags: {', '.join(tags)}\n\n{content}"
        with self._client() as c:
            # 更新标题
            c.patch(f"/pages/{pid}", json={
                "properties": {"title": {"title": [{"text": {"content": title}}]}},
            }).raise_for_status()
            # 清空旧 block 再写新（Notion 无整页替换，逐块删）。
            # 必须翻页取全部旧 block，否则超过 100 块的页面残留尾部会和新内容混在一起。
            for blk in self._all_child_blocks(c, pid):
                try:
                    c.delete(f"/blocks/{blk['id']}").raise_for_status()
                except Exception:
                    pass
            # 新内容分批写入，绕过单次 100 children 上限
            self._write_children_batched(c, pid, self._md_to_blocks(body))

    def delete(self, source: str) -> None:
        pid = source.replace("-", "")
        with self._client() as c:
            # Notion 无硬删除，归档即移出知识库
            c.patch(f"/pages/{pid}", json={"archived": True}).raise_for_status()

    def append(self, source: str, content: str) -> str:
        pid = source.replace("-", "")
        with self._client() as c:
            self._write_children_batched(c, pid, self._md_to_blocks(content))
        return pid  # 遵守基类契约：返回条目 source

    # ── Search / Read ────────────────────────────────────────────────────
    def _parent_page_id(self, pg: dict) -> str | None:
        """取 page 的直接父 page id（仅当 parent 是 page 时），否则 None。"""
        parent = pg.get("parent") or {}
        if parent.get("type") == "page_id":
            return (parent.get("page_id") or "").replace("-", "")
        return None

    def _is_within_root(self, pg: dict, client, root_id: str, cache: dict) -> bool:
        """沿 parent 链上溯，判断 page 是否落在 root_id 子树内。

        Notion /search 是 workspace 级的，会返回 integration 可见的所有页面；
        必须按 root 过滤，否则 people-kb 去重/召回会误匹配知识库外的页面。
        """
        seen: set[str] = set()
        pid = pg.get("id", "").replace("-", "")
        parent_id = self._parent_page_id(pg)
        depth = 0
        while parent_id and depth < 25:
            if parent_id == root_id:
                return True
            if parent_id in seen:  # 环保护
                return False
            seen.add(parent_id)
            # 缓存父链，避免同一批结果重复请求
            if parent_id in cache:
                parent_id = cache[parent_id]
            else:
                pr = client.get(f"/pages/{parent_id}")
                if pr.status_code != 200:
                    return False
                nxt = self._parent_page_id(pr.json())
                cache[parent_id] = nxt
                parent_id = nxt
            depth += 1
        return False

    def _resolve_scene_root(self, client) -> str | None:
        """scene 非空时返回 root 下的 `{scene}` 容器 id（find-only，不创建）；
        找不到返回 None（该 scene 尚无内容）。scene 为空时返回真实 root。"""
        if not self._scene:
            return self._root_page_id
        for p in self._child_pages(self._root_page_id):
            if p["title"] == self._scene:
                return p["id"]
        return None

    def search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        with self._client() as c:
            effective_root = self._resolve_scene_root(c)
            if effective_root is None:
                return []  # scene 容器还没建，说明该场景无任何条目
            # Notion /search 无 parent 过滤能力，先多取一些候选再按 root 收敛
            resp = c.post("/search", json={
                "query": query,
                "filter": {"property": "object", "value": "page"},
                "page_size": max(limit * 4, 20),
            })
            resp.raise_for_status()
            items: list[KnowledgeItem] = []
            ancestry_cache: dict[str, str | None] = {}
            for pg in resp.json().get("results", []):
                if len(items) >= limit:
                    break
                if not self._is_within_root(pg, c, effective_root, ancestry_cache):
                    continue  # 跳过知识库 root 之外的页面
                it = self._page_to_item(pg, with_content=False)
                if it:
                    items.append(it)
            return items

    async def semantic_search(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        # Notion 无向量检索，退回关键词 search
        return self.search(query, limit)

    def list_all(self) -> list[KnowledgeItem]:
        # 递归遍历 root（或 scene 子根）下所有 child page
        root = self._root_page_id
        if self._scene:
            for p in self._child_pages(self._root_page_id):
                if p["title"] == self._scene:
                    root = p["id"]
                    break
        items: list[KnowledgeItem] = []
        self._walk(root, items)
        return items

    def _walk(self, parent_id: str, out: list[KnowledgeItem]) -> None:
        self._walk_pages(self._child_pages(parent_id), out)

    def _walk_pages(self, pages: list[dict], out: list[KnowledgeItem]) -> None:
        """区分层级容器页与知识条目页：
        - 有子 page → 视作层级容器（work/、work/coze/ 这种），只递归、不收录，
          否则空正文的容器页会以空标题条目混进 list_all，且每页 get() 一次形成 N+1。
        - 无子 page → 叶子，才是真正的知识条目。
        条目在本 KB 中始终是叶子（add 总把新页挂在容器下），故该启发式成立。
        """
        for p in pages:
            children = self._child_pages(p["id"])
            if children:
                self._walk_pages(children, out)
            else:
                it = self.get(p["id"])
                if it:
                    out.append(it)

    def get(self, source: str) -> KnowledgeItem | None:
        pid = source.replace("-", "")
        with self._client() as c:
            pr = c.get(f"/pages/{pid}")
            if pr.status_code == 404:
                return None
            pr.raise_for_status()
            pg = pr.json()
            # 归档页 = 已删除（delete 用 archived=true 实现）。Notion 对归档页
            # /pages 仍返回 200，但其 children 已不可读（404）——视作不存在。
            if pg.get("archived") or pg.get("in_trash"):
                return None
            return self._page_to_item(pg, with_content=True)

    def _page_to_item(self, pg: dict, with_content: bool) -> KnowledgeItem | None:
        pid = pg.get("id", "").replace("-", "")
        if not pid:
            return None
        title = ""
        props = pg.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in prop.get("title", []))
                break
        content, tags = "", []
        if with_content:
            with self._client() as c:
                # 翻页取全部 block，避免长笔记只读到前 100 块——
                # 基于截断内容再 update 会永久丢失尾部
                blocks = self._all_child_blocks(c, pid)
            content = self._blocks_to_text(blocks)
            if content.startswith("Tags:"):
                first, _, rest = content.partition("\n")
                tags = [t.strip() for t in first[len("Tags:"):].split(",") if t.strip()]
                content = rest.strip()
        return KnowledgeItem(title=title, content=content, source=pid, tags=tags)

    def health_check(self) -> tuple[bool, str]:
        if not self._token:
            return False, "Notion token 未配置"
        if not self._root_page_id:
            return False, "Notion root_page_id 未配置"
        try:
            with self._client() as c:
                resp = c.get(f"/pages/{self._root_page_id}")
                if resp.status_code == 200:
                    return True, f"Notion 后端 OK：root={self._root_page_id[:8]}…"
                if resp.status_code in (401, 403):
                    return False, "Notion token 无效或未授权访问该 root page（需在 Notion 里把页面分享给 integration）"
                if resp.status_code == 404:
                    return False, "找不到 root page（检查 root_page_id，并确认已分享给 integration）"
                return False, f"Notion API 返回 {resp.status_code}"
        except Exception as e:
            return False, f"Notion 连接失败：{e}"
