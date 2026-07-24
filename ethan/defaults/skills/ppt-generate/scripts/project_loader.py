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

import copy
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple


def _page_sort_key(p: Path) -> tuple[int, int, str]:
    """页面文件排序：按文件名前导数字排，容忍未补零的 1_, 10_（纯字典序会得到 1,10,2…）。"""
    m = re.match(r"(\d+)", p.name)
    return (0, int(m.group(1)), p.name) if m else (1, 0, p.name)


class PageFile(NamedTuple):
    """一个页文件：路径 + 加载时的内容快照（供 write_back 判断该页是否真的被改过）。"""

    path: Path
    original: dict


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"[error] JSON 解析失败: {path}（{e}）") from e


def load_deck(path: Path) -> tuple[dict, Path, "list[PageFile] | None"]:
    """加载 deck，返回 (deck, deck_dir, page_files)。

    - 单文件：page_files 为 None；deck_dir 为文件所在目录。
    - 目录：meta 来自 <dir>/deck.json，slides 由 pages/*.json 按文件名排序合并；
      page_files 与 deck["slides"] 一一对应（供调用方原地回写某一页）。
    """
    path = path.resolve()
    if not path.is_dir():
        return _load_json(path), path.parent, None

    meta_path = path / "deck.json"
    if not meta_path.is_file():
        raise SystemExit(f"[error] 项目目录缺少 deck.json: {path}")
    deck = _load_json(meta_path)

    pages_dir = path / "pages"
    page_paths = sorted(pages_dir.glob("*.json"), key=_page_sort_key) if pages_dir.is_dir() else []
    if not page_paths:
        # 目录里没有 pages/ 时退化为「目录里的单文件 deck.json」
        return deck, path, None

    if deck.get("slides"):
        print(f"[warn] {meta_path} 含 slides，但 pages/ 存在——以 pages/*.json 为准，deck.json 的 slides 被忽略", file=sys.stderr)

    slides = []
    page_files = []
    for pp in page_paths:
        slide = _load_json(pp)
        if not isinstance(slide, dict) or not isinstance(slide.get("elements"), list):
            raise SystemExit(f"[error] 页文件应为单个 Slide 对象（含 elements 数组）: {pp}")
        slides.append(slide)
        page_files.append(PageFile(pp, copy.deepcopy(slide)))
    deck["slides"] = slides
    return deck, path, page_files


def default_assets_dir(path: Path) -> Path:
    """单文件：<deck名>.assets/（与 deck 同级）；项目目录：<dir>/assets/。"""
    path = path.resolve()
    if path.is_dir():
        return path / "assets"
    return path.with_suffix("").parent / (path.stem + ".assets")


def write_back(path: Path, deck: dict, page_files: "list[PageFile] | None") -> int:
    """把（可能被原地修改过的）deck 写回磁盘，返回实际写入的文件数。

    项目模式下只回写内容真正变化过的页（与加载时快照比对），未改动的页文件
    保持原始排版不动；deck.json 的元信息保持不变。单文件模式整体回写。
    """
    path = path.resolve()
    if page_files:
        slides = deck.get("slides") or []
        if len(slides) != len(page_files):
            raise SystemExit(f"[error] slides 数量({len(slides)})与页文件数量({len(page_files)})不一致，无法回写")
        written = 0
        for slide, page in zip(slides, page_files):
            if slide == page.original:
                continue
            page.path.write_text(json.dumps(slide, ensure_ascii=False, indent=2), encoding="utf-8")
            written += 1
        return written
    if path.is_dir():
        path = path / "deck.json"
    path.write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1
