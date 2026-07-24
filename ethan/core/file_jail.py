"""交付文件的 jail 与类型白名单 — deliver_file 工具与 files 路由共用的唯一事实源。

两处任何一处单独改动都会让「工具能交付」与「路由能下载/预览」分叉，
所以 jail 规则、扩展名白名单、deck 项目布局约定全部收敛到本模块。
"""
from __future__ import annotations

from pathlib import Path

# 允许交付/下载的扩展名（按需扩充）
DELIVER_EXTS = {".pptx", ".pdf", ".docx", ".xlsx", ".csv", ".zip", ".md", ".html"}
# 项目 assets/ 里允许直出的图片扩展名
ASSET_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}


def resolve_jailed(path: str) -> Path | None:
    """解析路径并做 jail 校验：只允许 home 目录和 /tmp 下的文件；不合法返回 None。"""
    try:
        p = Path(path).expanduser().resolve()
    except Exception:
        return None
    home = Path.home().resolve()
    tmp = Path("/tmp").resolve()  # macOS 上 /tmp 是 /private/tmp 的软链，resolve 后再比
    if not (p.is_relative_to(home) or p.is_relative_to(tmp)):
        return None
    return p


def is_project_dir(d: Path) -> bool:
    """deck 项目布局约定：目录内含 deck.json + pages/。"""
    return (d / "deck.json").is_file() and (d / "pages").is_dir()


def detect_project(file_path: Path) -> tuple[str | None, int | None]:
    """pptx 同目录若是项目制 deck（deck.json + pages/），返回项目目录与页数。"""
    if file_path.suffix.lower() != ".pptx":
        return None, None
    project_dir = file_path.parent
    if not is_project_dir(project_dir):
        return None, None
    page_count = len(list((project_dir / "pages").glob("*.json")))
    return (str(project_dir), page_count) if page_count else (None, None)
