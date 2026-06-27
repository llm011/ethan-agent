#!/usr/bin/env python3
"""把 PDF 拆成「逐页」素材，供 Map 阶段逐页精读。

每页产出两样东西：
  - page_NNN.png   渲染图（让多模态模型能看到图表/架构图/公式排版）
  - 一份 manifest.json，含每页的 text（嵌入文字层）+ png 路径

依赖 PyMuPDF（fitz）。本仓库未把它列为运行时依赖，因此推荐用：
    uv run --with pymupdf python extract_pages.py <pdf> [--out-dir DIR] [--dpi 150]

用法：
    uv run --with pymupdf python extract_pages.py ./paper_work/2603.25737.pdf
    uv run --with pymupdf python extract_pages.py paper.pdf --dpi 200 --max-pages 40

输出（stdout 末行）：一行 JSON
    {"pdf_path":..., "num_pages":N, "effective_pages":M, "references_start_page":K|null, "manifest":"...manifest.json", "pages":[{...}]}

  - effective_pages：实际应精读的页数 = min(max_pages, references_start-1)。References
    及之后不精读，默认上限 15 页（--max-pages 可调）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print(
        "缺少 PyMuPDF。请用：uv run --with pymupdf python extract_pages.py ...\n"
        "或先安装：uv pip install pymupdf",
        file=sys.stderr,
    )
    raise SystemExit(3)

# References 起始页标题（独立成行、大小写不敏感）
REF_TITLE_RE = re.compile(
    r"^\s*(references?|bibliography|参考文献|文献|references?\s+and\s+notes?)\s*[:：]?\s*$",
    re.IGNORECASE,
)
# 引用条目行：[1] / [12] / 1. / (1) 开头
REF_ENTRY_RE = re.compile(r"^\s*(\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}\.)\s+\S")
# 强引用信号：[N] 后跟作者名（大写字母/中文开头）——区分正文编号列表
REF_BRACKET_RE = re.compile(r"^\s*\[\d{1,3}\]\s+[A-Z一-鿿]")


def detect_references_start(pages: list[dict]) -> int | None:
    """返回 References 起始页码（1-based）；未检测到返回 None。

    两条判据（满足任一）：
    1) 该页前 3 个非空行有 References/Bibliography 标题，且本页或下一页含引用条目；
    2) 该页前 3 个非空行有 ≥2 行是 "[N] 作者" 方括号引用格式（不少论文省略 References 标题）。
    """
    n = len(pages)
    for idx, p in enumerate(pages):
        lines = [ln.strip() for ln in p["text"].splitlines() if ln.strip()]
        if not lines:
            continue
        head = lines[:3]
        # 判据2：方括号引用条目密集（不依赖标题）
        bracket_hits = sum(1 for ln in head if REF_BRACKET_RE.match(ln))
        if bracket_hits >= 2:
            return p["page"]
        # 判据1：标题 + 引用条目确认
        if any(REF_TITLE_RE.match(ln) for ln in head):
            check_pages = [p] + ([pages[idx + 1]] if idx + 1 < n else [])
            entry_hits = sum(1 for cp in check_pages for ln in cp["text"].splitlines() if REF_ENTRY_RE.match(ln))
            if entry_hits >= 2:
                return p["page"]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="PDF 逐页拆分为图片+文字")
    ap.add_argument("pdf", help="本地 PDF 路径")
    ap.add_argument("--out-dir", default=None, help="输出目录（默认 <pdf>_pages/）")
    ap.add_argument("--dpi", type=int, default=150, help="渲染 DPI（默认 150，清晰度/体积权衡）")
    ap.add_argument("--max-pages", type=int, default=15, help="最多处理前 N 页（默认 15；0=全部）")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"PDF 不存在：{pdf_path}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else pdf_path.with_suffix("").parent / f"{pdf_path.stem}_pages"
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    total = doc.page_count
    limit = min(total, args.max_pages) if args.max_pages > 0 else total
    zoom = args.dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    pages = []
    for i in range(limit):
        page = doc.load_page(i)
        text = page.get_text("text")
        png_path = out_dir / f"page_{i + 1:03d}.png"
        pix = page.get_pixmap(matrix=matrix)
        pix.save(str(png_path))
        pages.append({
            "page": i + 1,
            "png": str(png_path.resolve()),
            "text": text,
            "char_count": len(text),
        })

    doc.close()

    # 检测 References 起始页，计算实际精读页数。
    # 注意：包含 references_start_page 本身 —— 该页前半可能是正文（结论/致谢），只从中后部
    # 才进入引用，精读它不漏正文结尾；即使整页都是引用，Reduce 阶段也会自然忽略纯引用。
    refs_start = detect_references_start(pages)
    if refs_start:
        effective = min(limit, refs_start)
    else:
        effective = limit
    effective = max(effective, 0)

    manifest_path = out_dir / "manifest.json"
    manifest = {
        "pdf_path": str(pdf_path.resolve()),
        "num_pages": total,
        "processed_pages": limit,
        "effective_pages": effective,
        "references_start_page": refs_start,
        "max_pages": (args.max_pages if args.max_pages > 0 else total),
        "dpi": args.dpi,
        "pages": pages,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # stdout 末行给精简版（避免把全文 text 刷屏，pages 里只留路径和字数）
    summary = {
        "pdf_path": manifest["pdf_path"],
        "num_pages": total,
        "effective_pages": effective,
        "references_start_page": refs_start,
        "manifest": str(manifest_path.resolve()),
        "pages": [{"page": p["page"], "png": p["png"], "char_count": p["char_count"]} for p in pages],
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
