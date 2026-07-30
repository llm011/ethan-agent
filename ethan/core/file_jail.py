"""交付文件的 jail 与类型白名单 — deliver_file 工具与 files 路由共用的唯一事实源。

两处任何一处单独改动都会让「工具能交付」与「路由能下载/预览」分叉，
所以 jail 规则、扩展名白名单、deck 项目布局约定全部收敛到本模块。
"""
from __future__ import annotations

from pathlib import Path

# 可内联查看（图片）的扩展名：交付后前端用 Lightbox 打开，走 /files/view 直出。
# 与 ASSET_EXTS 内容一致但语义不同——ASSET_EXTS 限项目 assets/ 内引用，
# IMAGE_EXTS 是「作为独立文件交付」的图片（deliver_file 直接交付一张图）。
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}
# 允许交付/下载的扩展名（按需扩充）。图片并入——交付图片时走文件卡片（kind=png 等），
# 前端识别图片 kind 后渲染缩略图 + 点击 Lightbox 放大，其余类型走下载/预览。
DELIVER_EXTS = {".pptx", ".pdf", ".docx", ".xlsx", ".csv", ".zip", ".md", ".html"} | IMAGE_EXTS
# 项目 assets/ 里允许直出的图片扩展名
ASSET_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}


def resolve_jailed(path: str) -> Path | None:
    """解析路径并做 jail 校验：只允许 home 目录和 /tmp 下的文件；不合法返回 None。

    注意：jail 只是第一道防线，允许整个 home 是为了兼容 deliver_file 的任意输出路径。
    它本身不足以防止越权读敏感文件（如 ~/.ssh/id_rsa）——caller（/files/* 路由）必须
    独立做 session grant check（granted_files/granted_dirs 集合成员判定）+ 扩展名白名单
    （DELIVER_EXTS/ASSET_EXTS）。任何新 caller 都不能只靠 jail 就放行下载。
    """
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


def build_file_card(path: str, title: str = "") -> dict | None:
    """构建文件卡片 dict —— deliver_file 工具与正文兜底扫描共用的唯一构造点。

    path 必须 jail 内、真实存在、扩展名在 DELIVER_EXTS 白名单，否则返回 None。
    收敛在此避免工具与兜底两处各自拼卡片导致字段漂移（尤其 pptx 的 project_dir/page_count）。
    """
    p = resolve_jailed(path)
    if p is None or not p.is_file() or p.suffix.lower() not in DELIVER_EXTS:
        return None
    card: dict = {
        "type": "file",
        "filename": p.name,
        "title": title or p.stem,
        "path": str(p),
        "size_kb": round(p.stat().st_size / 1024, 1),
        "kind": p.suffix.lower().lstrip("."),
    }
    project_dir, page_count = detect_project(p)
    if project_dir:
        card["project_dir"] = project_dir
        card["page_count"] = page_count
    return card


# 兜底扫描只认「明确是产物」的高信号扩展名，避免正文里随手提到的 .md/.html 被误转成卡片。
FALLBACK_CARD_EXTS = {".pptx", ".pdf", ".docx", ".xlsx"} | IMAGE_EXTS


def scan_file_cards_in_text(text: str, existing_paths: set[str]) -> list[dict]:
    """扫描正文里的裸绝对路径，为「可交付、存在、且尚未成卡片」的文件补文件卡片。

    仅用于 agent 忘了调 deliver_file、直接把路径写进正文的兜底场景。返回的卡片会被
    持久化进 messages.cards——这同时也是 /files 路由的下载授权来源，所以补卡片 = 补授权，
    卡片才点得动（否则纯前端识别路径渲染的卡片点了必 403）。
    """
    import re

    if not text:
        return []
    exts = "|".join(sorted(e.lstrip(".") for e in FALLBACK_CARD_EXTS))
    # 匹配以 / 或 ~ 开头、不含空白与引号/反引号的路径，以高信号扩展名结尾
    pattern = re.compile(r"(?:~|/)[^\s`\"'<>|]*\.(?:" + exts + r")", re.IGNORECASE)
    # 去重键统一用 resolve 后的绝对路径——existing_paths 可能是原始写法（如 /tmp/x），
    # 而 build_file_card 存的是 resolve 后的（macOS 上 /tmp→/private/tmp），不归一会漏去重。
    def _norm(pth: str) -> str:
        r = resolve_jailed(pth)
        return str(r) if r is not None else pth
    seen = {_norm(p) for p in existing_paths if p}
    cards: list[dict] = []
    for m in pattern.finditer(text):
        card = build_file_card(m.group(0))
        if card is None or card["path"] in seen:
            continue
        seen.add(card["path"])
        cards.append(card)
    return cards
