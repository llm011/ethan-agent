"""Obsidian Vault 知识库后端 — YAML frontmatter、CLI 集成、层级目录迁移。"""
import re
from pathlib import Path

from ._helpers import _safe_subpath, _strip_redundant_title_line
from .contracts import KnowledgeBase, KnowledgeItem


class ObsidianKnowledgeBase(KnowledgeBase):
    """Obsidian vault 作为知识库后端，遵循 Obsidian 约定（YAML frontmatter、wikilinks 等）。"""

    def __init__(self, vault_path: Path, folder: str = ".", scene: str = ""):
        self._vault = vault_path
        self._scene = scene
        # 归一化 folder：剥掉任何重复的 scene 首段。
        # registry 已保证 folder 只含一层 scene（"./work" → "work"），但历史配置
        # （obsidian_folder="work" + scene="work"）会拼出 work/work，这里做最终兜底，
        # 确保 self._dir 永远不落在 <vault>/<scene>/<scene>。
        raw_folder = str(folder or ".").strip().strip("/")
        parts = [p for p in raw_folder.split("/") if p]
        scene_head = (scene or "").strip("/")
        # 只在「剥完还能剩下内容」时剥，保证至少保留一层目录——
        # folder="work" + scene="work" 是合法目标（vault/work），不能剥成 "."。
        while scene_head and len(parts) > 1 and parts[0] == scene_head:
            parts = parts[1:]
        self._folder = "/".join(parts) if parts else "."
        self._dir = vault_path / self._folder
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
        - 绝不覆盖已有文件。同名且内容相同 → 删重复项；内容不同 → 保留两份，
          旧文件改名为 `<stem>-重复-<mtime日期>.md` 后搬入，避免数据丢失。
        - dest 是文件而 child 是目录时跳过（避免 NotADirectoryError）。
        - 整体包 try/except，迁移失败不影响知识库初始化。
        """
        if not self._scene or not self._dir.exists():
            return
        dup_dir = self._dir / self._scene
        if not dup_dir.is_dir():
            return
        # 防御：若 self._dir 本身就是 <vault>/<scene>（正常情况），
        # 绝不能在 <vault>/<scene> 下再建/搬 <scene> 子目录——那正是 bug 的产物。
        try:
            if self._dir.resolve() == (self._vault / self._scene).resolve():
                print(f"[knowledge] refuse to migrate scene-named dir under scene root: {dup_dir}")
                return
        except OSError:
            pass
        try:
            self._migrate_children(dup_dir, self._dir)
            # 仅当 dup_dir 真正空了才删
            try:
                if not any(dup_dir.iterdir()):
                    dup_dir.rmdir()
            except OSError:
                pass
        except Exception as e:
            print(f"[knowledge] _migrate_double_nested failed: {e}")

    def _migrate_children(self, src: Path, dest_dir: Path) -> None:
        """把 src 下的条目搬到 dest_dir，冲突时按内容决定去重或改名保留。"""
        for child in list(src.iterdir()):
            dest = dest_dir / child.name
            if not dest.exists():
                child.rename(dest)
                continue
            if child.is_dir():
                if dest.is_file():
                    print(f"[knowledge] skip migrate {child} -> {dest}: dest is file, child is dir")
                    continue
                self._migrate_children(child, dest)
                try:
                    if not any(child.iterdir()):
                        child.rmdir()
                except OSError:
                    pass
                continue
            # dest 是文件、child 也是文件 → 比对内容
            if self._same_content(child, dest):
                child.unlink()
                print(f"[knowledge] dedup {child} (identical to {dest})")
            else:
                try:
                    from datetime import datetime
                    stamp = datetime.fromtimestamp(child.stat().st_mtime).strftime("%Y%m%d")
                except OSError:
                    stamp = "old"
                renamed = dest_dir / f"{child.stem}-重复-{stamp}{child.suffix}"
                i = 1
                while renamed.exists():
                    renamed = dest_dir / f"{child.stem}-重复-{stamp}-{i}{child.suffix}"
                    i += 1
                child.rename(renamed)
                print(f"[knowledge] moved {child} -> {renamed} (content differs, kept both)")

    @staticmethod
    def _same_content(a: Path, b: Path) -> bool:
        try:
            if a.stat().st_size != b.stat().st_size:
                return False
            return a.read_bytes() == b.read_bytes()
        except OSError:
            return False

    def _get_vector_store(self):
        if self._vector_store is None:
            from ethan.memory.vector_store import VectorStore
            self._vector_store = VectorStore()
        return self._vector_store

    # ── Write ──────────────────────────────────────────────────────────────

    def _strip_scene_prefix(self, tags: list[str] | None) -> list[str] | None:
        """剥掉 tags[0] 开头重复的 scene 前缀，防止路径重复拼接。

        scene 已由 registry 拼进 self._dir，若 tags[0] 也带 scene 前缀
        （如 scene="work" + tags=["work/coze"] → work/work/coze），会多套一层。
        循环剥离以兼容双层重复（"work/work/coze" → "coze"）和直接等于 scene
        （tags=["work"] → 落 scene 根目录）的情况。
        """
        if not tags or not self._scene:
            return tags
        scene = self._scene.strip("/")
        if not scene:
            return tags
        head, *rest = tags
        changed = False
        while True:
            text = str(head).strip("/")
            if text == scene:
                head, changed = scene, True   # 纯 scene 标签 → 落到 scene 根目录
                break
            if text.startswith(f"{scene}/"):
                head, changed = text[len(scene) + 1:], True
                continue
            head = text
            break
        if not changed:
            return tags
        # 剥没了（tags 只有 "work"）→ 返回 None 表示落 scene 根目录
        stripped = [head, *rest] if head else rest
        return stripped or None

    def _normalize_subpath(self, tags: list[str] | None) -> Path | None:
        """把 tags[0] 清洗为相对 self._dir 的子路径，并禁止越界到 scene 同名目录。

        add() 与 update() 共用：任何情况下都不允许写入 self._dir/<scene>/，
        否则会重新制造 work/work 嵌套。
        """
        if not tags:
            return None
        subpath = _safe_subpath(tags[0], self._scene)
        if subpath is None:
            return None
        scene = (self._scene or "").strip("/")
        # 循环剥掉所有残留的 scene 首段（兼容 "work/work/coze" 这类多层重复）
        while scene and subpath.parts and subpath.parts[0] == scene:
            subpath = Path(*subpath.parts[1:]) if len(subpath.parts) > 1 else None
            if subpath is None:
                return None
        return subpath

    def add(self, title: str, content: str, tags: list[str] | None = None,
            frontmatter: dict | None = None) -> str:
        tags = self._strip_scene_prefix(tags)
        slug = re.sub(r"[^\w]+", "-", title.lower())[:50].strip("-")
        slug = re.sub(r"-{2,}", "-", slug)  # 双保险：合并残余连续短横线
        # 按 tags[0] 分子目录，支持层级标签（如 "coze/prd" → coze/prd/）；
        # sanitize 后为空则落根目录
        target_dir = self._dir
        subpath = self._normalize_subpath(tags)
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
