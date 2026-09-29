"""文档库（Documents）—— Agent 产出文档的统一落盘目录与文件树。

背景：deliver_file 的 jail 只限制「home 或 /tmp」，具体路径由 Agent 临场决定，
导致产出散落各处。实测 sessions.db 里 57 个交付文件仅 1 个仍存在——48 个写在
/tmp 被系统清理。本模块把这批文档收拢到 ~/.ethan/documents/ 统一管理。

目录约定（AGENT 自主分类，但根固定）：
    ~/.ethan/documents/
    ├── work/coze/每日MR/2026-09-28-xxx.md
    ├── life/
    ├── routine/
    └── .library.json      ← 元数据：收藏 / 置顶 / 来源对话

设计取舍：文件树直接由文件系统推导，不维护索引表。元数据只存「附加信息」
（favorite/pinned/session 关联），文件被外部删除时元数据自然失效，
不会出现「索引与实际不一致」的漂移。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# 文档根目录。可用环境变量覆盖（测试隔离用）。
DEFAULT_ROOT = "~/.ethan/documents"
# 元数据文件名（放在根目录，以 . 开头避免被当作文档扫出来）
LIBRARY_FILE = ".library.json"
# 允许出现在文档库里的扩展名——与 file_jail.DELIVER_EXTS 的文档子集保持一致
DOC_EXTS = {".md", ".markdown", ".txt", ".html", ".htm", ".pdf", ".docx", ".csv", ".xlsx"}

# 目录/文件名的安全校验：禁路径分隔符、上级引用、控制字符、Windows 保留字符。
# Agent 用它命名分类目录，必须挡住 "../" 之类的越狱尝试。
_UNSAFE_NAME_RE = re.compile(r'[<>:"|?*\x00-\x1f]')


def documents_root() -> Path:
    """文档库根目录（不保证存在，caller 需要时自行 mkdir）。

    优先级：ETHAN_DOCUMENTS_DIR（测试隔离）> per-profile 数据目录 > ~/.ethan/documents。
    走 user_data_dir() 是为了与 memory/knowledge/sessions 一致地按 profile 隔离——
    否则命名 profile 的用户会与 default profile 共用同一个文档库。
    default profile 下 user_data_dir() 就是 ~/.ethan，路径与历史行为一致。
    """
    override = os.environ.get("ETHAN_DOCUMENTS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    try:
        from ethan.core.paths import user_data_dir

        return (user_data_dir() / "documents").resolve()
    except Exception:
        # 路径模块不可用（如独立导入本模块做脚本）时退回默认根
        return Path(DEFAULT_ROOT).expanduser().resolve()


def ensure_root() -> Path:
    root = documents_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def sanitize_segment(name: str) -> str:
    """把一段路径（分类目录名/文件名）清洗成安全形式。

    去除路径分隔符与上级引用，防止 Agent 传入 "../../etc/passwd" 逃出文档库。
    清洗后为空则返回 "_"，避免产生空目录名。
    """
    if not name:
        return "_"
    # 只取最后一段，丢掉任何目录穿越成分
    name = name.replace("\\", "/")
    parts = [p for p in name.split("/") if p not in ("", ".", "..")]
    name = parts[-1] if parts else "_"
    name = _UNSAFE_NAME_RE.sub("_", name).strip().strip(".")
    return name or "_"


def resolve_in_root(rel_path: str) -> Path | None:
    """把相对路径解析到文档库内；越界返回 None。

    这是文档库的安全边界：所有写/读/删都必须经过它，确保最终路径仍在根目录内。
    """
    root = documents_root()
    try:
        # 逐段清洗，杜绝 "../" 与绝对路径注入
        segs = [sanitize_segment(s) for s in rel_path.replace("\\", "/").split("/") if s.strip()]
        if not segs:
            return None
        target = root.joinpath(*segs).resolve()
    except Exception:
        return None
    if not target.is_relative_to(root):
        return None
    return target


def relative_to_root(path: Path) -> str:
    """绝对路径 → 相对文档库的 posix 路径（元数据键、API 参数都用它）。"""
    try:
        return path.resolve().relative_to(documents_root()).as_posix()
    except Exception:
        return ""


# ---------------------------------------------------------------- 元数据


@dataclass
class DocMeta:
    """单个文档的附加元数据（不存正文，正文始终以文件为准）。"""
    favorite: bool = False
    pinned: bool = False
    session_id: str = ""
    message_id: int = 0   # 来源消息，用于「定位到对话」
    title: str = ""       # 展示名（缺省用文件名）
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        d = {"favorite": self.favorite, "pinned": self.pinned}
        if self.session_id:
            d["session_id"] = self.session_id
        if self.message_id:
            d["message_id"] = self.message_id
        if self.title:
            d["title"] = self.title
        if self.updated_at:
            d["updated_at"] = self.updated_at
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DocMeta":
        return cls(
            favorite=bool(d.get("favorite")),
            pinned=bool(d.get("pinned")),
            session_id=str(d.get("session_id") or ""),
            message_id=int(d.get("message_id") or 0),
            title=str(d.get("title") or ""),
            updated_at=float(d.get("updated_at") or 0.0),
        )


class Library:
    """文档库元数据（收藏/置顶/来源对话）的读写。

    存储为根目录下的 .library.json：{"<rel_path>": {...}}。
    读操作容忍文件损坏（返回空库），避免一个坏 JSON 让整个文档页打不开。
    """

    def __init__(self, root: Path | None = None):
        self.root = root or documents_root()
        self._path = self.root / LIBRARY_FILE
        self._cache: dict[str, DocMeta] | None = None

    def _load(self) -> dict[str, DocMeta]:
        if self._cache is not None:
            return self._cache
        data: dict[str, DocMeta] = {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if isinstance(v, dict):
                        data[k] = DocMeta.from_dict(v)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass  # 首次运行或文件损坏——按空库处理，不阻断页面
        self._cache = data
        return data

    def _save(self, data: dict[str, DocMeta]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {k: v.to_dict() for k, v in data.items() if v.to_dict()}
        # 先写临时文件再替换：避免写入中途崩溃留下半截 JSON
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)
        self._cache = data

    def get(self, rel: str) -> DocMeta:
        return self._load().get(rel, DocMeta())

    def all(self) -> dict[str, DocMeta]:
        return dict(self._load())

    def update(self, rel: str, **fields) -> DocMeta:
        data = self._load()
        meta = data.get(rel, DocMeta())
        for k, v in fields.items():
            if hasattr(meta, k):
                setattr(meta, k, v)
        data[rel] = meta
        self._save(data)
        return meta

    def remove(self, rel: str) -> None:
        data = self._load()
        if rel in data:
            del data[rel]
            self._save(data)

    def rename(self, old_rel: str, new_rel: str) -> None:
        """文件移动/重命名时跟随迁移元数据，避免收藏状态丢失。"""
        data = self._load()
        if old_rel in data:
            data[new_rel] = data.pop(old_rel)
            self._save(data)


# ---------------------------------------------------------------- 文件树


@dataclass
class DocNode:
    """文件树节点（文件或目录）。"""
    name: str
    path: str                      # 相对文档库的 posix 路径
    is_dir: bool
    size_kb: float = 0.0
    mtime: float = 0.0
    meta: DocMeta = field(default_factory=DocMeta)
    children: list["DocNode"] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "path": self.path,
            "is_dir": self.is_dir,
            "mtime": self.mtime,
        }
        if not self.is_dir:
            d["size_kb"] = self.size_kb
            d["ext"] = Path(self.name).suffix.lower().lstrip(".")
            d["favorite"] = self.meta.favorite
            d["pinned"] = self.meta.pinned
            if self.meta.session_id:
                d["session_id"] = self.meta.session_id
                d["message_id"] = self.meta.message_id
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


def _build_tree(directory: Path, root: Path, lib: Library, depth: int = 0) -> list[DocNode]:
    """递归构建文件树。深度上限防病态嵌套导致递归过深。"""
    if depth > 12:
        return []
    nodes: list[DocNode] = []
    try:
        entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except (PermissionError, FileNotFoundError, OSError):
        return []

    for entry in entries:
        # 跳过隐藏文件（.library.json、.DS_Store 等）
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            children = _build_tree(entry, root, lib, depth + 1)
            # 空目录不展示——避免树里出现一堆点不开的空节点
            if not children:
                continue
            nodes.append(DocNode(
                name=entry.name,
                path=entry.relative_to(root).as_posix(),
                is_dir=True,
                children=children,
            ))
        elif entry.is_file() and entry.suffix.lower() in DOC_EXTS:
            try:
                st = entry.stat()
            except OSError:
                continue
            rel = entry.relative_to(root).as_posix()
            nodes.append(DocNode(
                name=entry.name,
                path=rel,
                is_dir=False,
                size_kb=round(st.st_size / 1024, 1),
                mtime=st.st_mtime,
                meta=lib.get(rel),
            ))
    return nodes


def build_file_tree() -> list[DocNode]:
    """构建整个文档库的文件树（供 /api/documents/tree 使用）。"""
    root = documents_root()
    if not root.is_dir():
        return []
    lib = Library(root)
    return _build_tree(root, root, lib)


def count_documents(nodes: list[DocNode]) -> int:
    """统计文件总数（前端顶部显示「N 个文档」）。"""
    total = 0
    for n in nodes:
        total += count_documents(n.children) if n.is_dir else 1
    return total


def list_flat(limit: int = 0) -> list[DocNode]:
    """平铺列出所有文档（按修改时间倒序），供「最近」等视图使用。"""
    out: list[DocNode] = []

    def walk(nodes: list[DocNode]) -> None:
        for n in nodes:
            if n.is_dir:
                walk(n.children)
            else:
                out.append(n)

    walk(build_file_tree())
    out.sort(key=lambda n: n.mtime, reverse=True)
    return out[:limit] if limit > 0 else out
