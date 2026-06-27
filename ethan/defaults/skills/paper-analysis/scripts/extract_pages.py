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
    {"pdf_path":..., "num_pages":N, "manifest":"...manifest.json", "pages":[{...}]}
"""
import argparse
import json
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


def main() -> int:
    ap = argparse.ArgumentParser(description="PDF 逐页拆分为图片+文字")
    ap.add_argument("pdf", help="本地 PDF 路径")
    ap.add_argument("--out-dir", default=None, help="输出目录（默认 <pdf>_pages/）")
    ap.add_argument("--dpi", type=int, default=150, help="渲染 DPI（默认 150，清晰度/体积权衡）")
    ap.add_argument("--max-pages", type=int, default=0, help="最多处理前 N 页（0=全部）")
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

    manifest_path = out_dir / "manifest.json"
    manifest = {
        "pdf_path": str(pdf_path.resolve()),
        "num_pages": total,
        "processed_pages": limit,
        "dpi": args.dpi,
        "pages": pages,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # stdout 末行给精简版（避免把全文 text 刷屏，pages 里只留路径和字数）
    summary = {
        "pdf_path": manifest["pdf_path"],
        "num_pages": total,
        "processed_pages": limit,
        "manifest": str(manifest_path.resolve()),
        "pages": [{"page": p["page"], "png": p["png"], "char_count": p["char_count"]} for p in pages],
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
