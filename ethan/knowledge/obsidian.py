"""Obsidian Vault 知识库后端 — YAML frontmatter、CLI 集成、层级目录迁移。"""
import re
from pathlib import Path

from ._helpers import _safe_subpath, _strip_redundant_title_line
from .contracts import KnowledgeBase, KnowledgeItem


class ObsidianKnowledgeBase(KnowledgeBase):
    """Obsidian vault 作为知识库后端，遵循 Obsidian 约定（YAML frontmatter、wikilinks 等）。"""

    def __init__(self, vault_path: Path, folder: str = ".", scene: str = ""):
        self._vault = vault_path
        self._folder = folder
        self._dir = vault_path / folder
        self._scene = scene
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # health_check() will report the issue
        self._vector_store: "VectorStore | None" = None  # noqa: F821
        import shutil
        self._cli_available = shutil.which("obsidian") is not None
        self._migrate_double_nested()

    def _migrate_double_nested(self) -> None:
        """一次性修复 scene 前缀重复导致的 double-nested 目录（如 work/work/coze → work/coze）。

        安全策略：
        - 同名文件/目录跳过并告警，绝不覆盖。
        - dest 是文件而 child 是目录时跳过（避免 NotADirectoryError）。
        - 整体包 try/except，迁移失败不影响知识库初始化。
        """
        if not self._scene or not self._dir.exists():
            return
        dup_dir = self._dir / self._scene
        if not dup_dir.is_dir():
            return
        try:
            for child in list(dup_dir.iterdir()):
                dest = self._dir / child.name
                if dest.exists():
                    # dest 已是文件但 child 是目录，跳过避免 NotADirectoryError
                    if dest.is_file() and child.is_dir():
                        print(f"[knowledge] skip migrate {child} -> {dest}: dest is file, child is dir")
                        continue
                    if child.is_dir():
                        for f in child.iterdir():
                            target = dest / f.name
                            if target.exists():
                                print(f"[knowledge] skip migrate {f} -> {target}: dest exists")
                                continue
                            f.rename(target)
                        # 只在子目录已空时删除
                        try:
                            child.rmdir()
                        except OSError:
                            pass
                    else:
                        print(f"[knowledge] skip migrate {child} -> {dest}: dest exists")
                else:
                    child.rename(dest)
            # 仅当 dup_dir 真正空了才删
            try:
                if not any(dup_dir.iterdir()):
                    dup_dir.rmdir()
            except OSError:
                pass
        except Exception as e:
            print(f"[knowledge] _migrate_double_nested failed: {e}")

    def _get_vector_store(self):
        if self._vector_store is None:
            from ethan.memory.vector_store import VectorStore
            self._vector_store = VectorStore()
        return self._vector_store

    # ── Write ──────────────────────────────────────────────────────────────

    def _strip_scene_prefix(self, tags: list[str] | None) -> list[str] | None:
        """剥掉 tags[0] 开头的 scene 前缀，防止路径重复拼接。

        scene 已由 registry 拼进 self._dir，若 tags[0] 也带 scene 前缀
        （如 scene="work" + tags=["work/coze"]），会导致多套一层 work/work/。
        """
        if not tags or not self._scene:
            return tags
        prefix = f"{self._scene}/"
        if tags[0].startswith(prefix):
            stripped = tags[0][len(prefix):]
            if stripped:
                return [stripped, *tags[1:]]
        return tags

    def add(self, title: str, content: str, tags: list[str] | None = None,
            frontmatter: dict | None = None) -> str:
        tags = self._strip_scene_prefix(tags)
        slug = re.sub(r"[^\w]+", "-", title.lower())[:50].strip("-")
        slug = re.sub(r"-{2,}", "-", slug)  # 双保险：合并残余连续短横线
        # 按 tags[0] 分子目录，支持层级标签（如 "coze/prd" → coze/prd/）；
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
        tags = self._strip_scene_prefix(tags)
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

        parts = ["---", fm_text, "---", "", f"# {title}", "", _strip_redundant_title_line(title, content)]
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
