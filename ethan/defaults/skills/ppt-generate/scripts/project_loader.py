"""项目目录 / 单文件 deck 的统一加载约定。

项目目录结构（逐页生成工作流推荐）：

  <项目目录>/
    deck.json      # 项目元信息：version / canvas / theme（通常是内联定制主题对象），不含 slides
    pages/*.json   # 每页一个 Slide 对象（{"id","type","elements":[...]}），按文件名排序合并为 slides
    assets/        # 图片资源（gen_image.py 在项目模式下的默认输出目录）

单文件模式（兼容旧工作流）：deck.json 自身含 slides 数组。

两个脚本（render_pptx.py / gen_image.py）的 deck 参数都接受文件或目录。
"""
from __future__ import annotations

import json
from pathlib import Path


def load_deck(path: Path) -> tuple[dict, Path, "list[Path] | None"]:
    """加载 deck，返回 (deck, deck_dir, page_files)。

    - 单文件：page_files 为 None；deck_dir 为文件所在目录。
    - 目录：meta 来自 <dir>/deck.json，slides 由 pages/*.json 按文件名排序合并；
      page_files 与 deck["slides"] 一一对应（供调用方原地回写某一页）。
    """
    path = path.resolve()
    if not path.is_dir():
        deck = json.loads(path.read_text(encoding="utf-8"))
        return deck, path.parent, None

    meta_path = path / "deck.json"
    if not meta_path.is_file():
        raise SystemExit(f"[error] 项目目录缺少 deck.json: {path}")
    deck = json.loads(meta_path.read_text(encoding="utf-8"))

    pages_dir = path / "pages"
    page_files = sorted(pages_dir.glob("*.json")) if pages_dir.is_dir() else []
    if not page_files:
        # 目录里没有 pages/ 时退化为「目录里的单文件 deck.json」
        return deck, path, None

    slides = []
    for pf in page_files:
        slide = json.loads(pf.read_text(encoding="utf-8"))
        if not isinstance(slide, dict) or not isinstance(slide.get("elements"), list):
            raise SystemExit(f"[error] 页文件应为单个 Slide 对象（含 elements 数组）: {pf}")
        slides.append(slide)
    deck["slides"] = slides
    return deck, path, page_files


def default_assets_dir(path: Path) -> Path:
    """单文件：<deck名>.assets/（与 deck 同级）；项目目录：<dir>/assets/。"""
    path = path.resolve()
    if path.is_dir():
        return path / "assets"
    return path.with_suffix("").parent / (path.stem + ".assets")


def write_back(path: Path, deck: dict, page_files: "list[Path] | None"):
    """把（可能被原地修改过的）deck 写回磁盘。

    项目模式下 slides[i] 回写到 page_files[i]，deck.json 的元信息保持不变；
    单文件模式整体回写。
    """
    path = path.resolve()
    if page_files:
        for slide, pf in zip(deck.get("slides") or [], page_files):
            pf.write_text(json.dumps(slide, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    if path.is_dir():
        path = path / "deck.json"
    path.write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
