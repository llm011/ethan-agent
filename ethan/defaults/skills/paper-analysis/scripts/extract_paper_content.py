#!/usr/bin/env python3
"""【路 C：结构化提取】从 PDF 提取章节文本、图片、表格、公式。

与 extract_pages.py 互补：extract_pages.py 把 PDF 渲染成逐页 PNG（喂给 vision），
本脚本用 pypdf 抽取 PDF 内嵌对象（图片/表格标题/公式行/章节）——vision 看图、本脚本
拆结构，二者配合可同时拿到「视觉排版」和「结构化清单」。

依赖 pypdf + Pillow（本仓库未列为运行时依赖），推荐用 uv 临时拉取：
    uv run --with pypdf,pillow python extract_paper_content.py <pdf>

用法：
    uv run --with pypdf,pillow python extract_paper_content.py ./paper_work/2603.25737.pdf
    uv run --with pypdf,pillow python extract_paper_content.py paper.pdf --out-dir ./paper_work/2603_extracted

输出（stdout 末行）：一行 JSON
    {"pdf_path":..., "output_dir":..., "result_file":..., "images":N, "useful_images":M,
     "tables":K, "formulas":L, "sections":S, "useful_images_dir":..., "images_dir":...,
     "tables_dir":..., "formulas_dir":...}

产物目录布局：
    <out_dir>/
      <pdf_stem>/
        extraction_result.json   # 完整结果汇总
        images/                  # 全部图片（含小图标）
        useful_images/           # 尺寸 ≥ 20×20 的有价值图片（语义命名）
        tables/                  # 表格标题清单（pypdf 不抽表格内容）
        formulas/                # 公式文本（按行检测，含数学符号/Equation N）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

# Pillow 可选——只影响图片提取，文本/表格/公式仍可工作
try:
    import io  # noqa: F401

    from PIL import Image as PILImage  # noqa: F401
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

try:
    from pypdf import PdfReader
except ImportError:
    print(
        "缺少 pypdf。请用：uv run --with pypdf,pillow python extract_paper_content.py ...\n"
        "或先安装：uv pip install pypdf pillow",
        file=sys.stderr,
    )
    raise SystemExit(3)


class PaperExtractor:
    """论文内容提取器：文本（按章节）/ 图片（含语义命名）/ 表格标题 / 公式行。"""

    # 有价值图片的最小尺寸阈值（像素）。小于此视为图标/装饰，不进 useful_images/
    USEFUL_MIN_SIZE = 20

    def __init__(self, pdf_path: str, output_dir: str):
        self.pdf_path = Path(pdf_path)
        self.output_dir = Path(output_dir)
        self.reader: Any = None
        # 用 PDF 文件名 stem 作为子目录键（兼容 arXiv ID 与任意 PDF 文件名）
        self.paper_key = self.pdf_path.stem
        self.pillow_available = PILLOW_AVAILABLE

        # 子目录布局
        self.images_dir = self.output_dir / self.paper_key / "images"
        self.tables_dir = self.output_dir / self.paper_key / "tables"
        self.formulas_dir = self.output_dir / self.paper_key / "formulas"
        self.useful_images_dir = self.output_dir / self.paper_key / "useful_images"

        for d in (self.images_dir, self.tables_dir, self.formulas_dir, self.useful_images_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ PDF
    def open_pdf(self) -> bool:
        try:
            self.reader = PdfReader(str(self.pdf_path))
            print(f"✓ 打开 PDF: {self.pdf_path}（{len(self.reader.pages)} 页）")
            return True
        except Exception as e:
            print(f"✗ 无法打开 PDF: {e}", file=sys.stderr)
            return False

    # ----------------------------------------------------------------- 文本
    def extract_text(self) -> Dict[str, Any]:
        """按章节切分全文，并尝试识别标题与摘要。"""
        if not self.reader:
            raise Exception("PDF未打开")

        text_content: Dict[str, Any] = {"title": "", "abstract": "", "sections": [], "full_text": ""}

        current_section: str | None = None
        section_text: List[str] = []

        for page_num, page in enumerate(self.reader.pages):
            text = page.extract_text() or ""
            if not text:
                continue
            text_content["full_text"] += text + "\n\n"

            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue

                is_header = (
                    (line.isupper() and 10 < len(line) < 100)
                    or (re.match(r"^\d+\.?\s+\w+", line) and 10 < len(line) < 200)
                    or (
                        line.startswith(("Abstract", "Introduction", "Conclusion",
                                         "References", "Related Work", "Method"))
                        and len(line) < 200
                    )
                )

                if is_header:
                    if current_section and section_text:
                        text_content["sections"].append({"title": current_section, "content": "\n".join(section_text)})
                    current_section = line
                    section_text = []
                else:
                    if current_section:
                        section_text.append(line)
                    elif "Abstract" in line and not text_content["abstract"]:
                        m = re.search(r"Abstract\s*(.+?)(?=\n\n|\n\s*[A-Z][a-z]+\s*$)",
                                      text, re.IGNORECASE | re.DOTALL)
                        if m:
                            text_content["abstract"] = m.group(1).strip()
                    elif not text_content["title"] and 10 < len(line) < 200:
                        text_content["title"] = line

        if current_section and section_text:
            text_content["sections"].append({"title": current_section, "content": "\n".join(section_text)})

        print(f"✓ 文本提取：标题「{text_content['title'][:50]}」/ 章节 {len(text_content['sections'])} / 摘要 "
              f"{'有' if text_content['abstract'] else '无'}")
        return text_content

    # --------------------------------------------------------- 图片语义命名
    def _generate_image_name(self, page_num: int, image_index: int,
                             page_text: str = "", is_useful: bool = False) -> str:
        """从页面文字里找 Figure N / 图 N 之类的 caption，给图片起语义化文件名。"""
        semantic_name = None
        if page_text:
            patterns = [
                r"Figure\s+(\d+[a-z]?)[:\s]*([^.\n]{0,30})",
                r"图\s*(\d+)[:\s]*([^。\n]{0,30})",
                r"Fig[.\s]*(\d+)[:\s]*([^.\n]{0,30})",
                r"架构图|Architecture",
                r"模型图|Model",
                r"流程图|Flow",
                r"示意图|Diagram",
                r"示例图|Example",
                r"对比图|Comparison",
                r"结果图|Result",
            ]
            for pat in patterns:
                m = re.search(pat, page_text, re.IGNORECASE)
                if m:
                    if m.groups():
                        kws = [g.strip() for g in m.groups() if g.strip()]
                        if kws:
                            semantic_name = "_".join(kws)
                            semantic_name = re.sub(r"[^\w\u4e00-\u9fff]", "_", semantic_name)
                            semantic_name = semantic_name[:30].strip("_")
                            break
            if not semantic_name:
                for kw in ("Figure", "Table", "Architecture", "Model", "Chart", "Diagram"):
                    if kw.lower() in page_text.lower():
                        semantic_name = kw.lower()
                        break

        if not semantic_name:
            semantic_name = f"img_p{page_num}_{image_index}"

        if is_useful:
            semantic_name = f"{semantic_name}_useful"
        return semantic_name

    # ----------------------------------------------------------------- 图片
    def extract_images(self) -> List[Dict[str, Any]]:
        if not self.reader:
            raise Exception("PDF未打开")
        if not self.pillow_available:
            print("  警告: Pillow 未安装，跳过图片提取（文本/表格/公式不受影响）")
            return []

        images: List[Dict[str, Any]] = []
        useful_count = 0
        image_count = 0

        try:
            for page_num, page in enumerate(self.reader.pages):
                try:
                    page_text = page.extract_text() or ""
                except Exception:
                    page_text = ""
                try:
                    page_images = page.images
                except Exception as e:
                    print(f"  警告: 第{page_num+1}页无法提取图片: {e}")
                    continue

                for img in page_images:
                    try:
                        pil_image = img.image
                        width, height = pil_image.size
                        is_useful = width >= self.USEFUL_MIN_SIZE and height >= self.USEFUL_MIN_SIZE

                        original_format = pil_image.format if pil_image.format else None
                        save_format = original_format if original_format in ("JPEG", "PNG", "GIF") else "PNG"

                        image_name = self._generate_image_name(page_num + 1, image_count + 1, page_text, False)
                        image_filename = f"{image_name}.{save_format.lower()}"
                        image_path = self.images_dir / image_filename
                        pil_image.save(image_path, format=save_format)

                        entry = {
                            "page": page_num + 1,
                            "index": image_count + 1,
                            "filename": image_filename,
                            "path": str(image_path),
                            "width": width,
                            "height": height,
                            "format": save_format,
                            "is_useful": is_useful,
                        }

                        if is_useful:
                            useful_name = self._generate_image_name(page_num + 1, useful_count + 1, page_text, True)
                            useful_filename = f"{useful_name}.{save_format.lower()}"
                            useful_path = self.useful_images_dir / useful_filename
                            pil_image.save(useful_path, format=save_format)
                            entry["useful_path"] = str(useful_path)
                            useful_count += 1

                        images.append(entry)
                        image_count += 1
                    except Exception as e:
                        print(f"  警告: 第{page_num+1}页图片处理失败: {e}")
                        continue
        except Exception as e:
            print(f"  警告: 图片提取异常: {e}")

        print(f"✓ 图片提取：共 {image_count} 张（有价值 {useful_count} 张，存于 useful_images/）")
        return images

    # ----------------------------------------------------------------- 表格
    def extract_tables(self) -> List[Dict[str, Any]]:
        """启发式检测「Table N: ...」标题。pypdf 不提供表格内容，只给定位。"""
        if not self.reader:
            raise Exception("PDF未打开")

        tables: List[Dict[str, Any]] = []
        table_pattern = r"(Table\s+\d+[:\.]\s*.+|表\s*\d+[:\.]\s*.+)"

        for page_num, page in enumerate(self.reader.pages):
            text = page.extract_text() or ""
            if not text:
                continue
            for m in re.finditer(table_pattern, text, re.IGNORECASE | re.MULTILINE):
                table_title = m.group(1).strip()
                table_filename = f"page{page_num+1}_table{len(tables)+1}.json"
                table_path = self.tables_dir / table_filename
                with open(table_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "page": page_num + 1,
                        "title": table_title,
                        "note": "pypdf 仅检测标题，表格内容需查看原文 PNG 或 vision 分析",
                    }, f, ensure_ascii=False, indent=2)
                tables.append({
                    "page": page_num + 1,
                    "index": len(tables) + 1,
                    "filename": table_filename,
                    "path": str(table_path),
                    "title": table_title,
                })

        print(f"✓ 表格检测：{len(tables)} 个（仅标题，内容需 vision 或人工对照）")
        return tables

    # ----------------------------------------------------------------- 公式
    def extract_formulas(self) -> List[Dict[str, Any]]:
        """启发式检测公式行：Equation N / 数学符号 / 等式模式。

        注意：pypdf 抽的公式是文字层片段，可能丢上下标/特殊符号。要原貌请走路径 A
        （vision 看 page_NNN.png）。这里给的只是「这页有公式，大致内容」的清单。
        """
        if not self.reader:
            raise Exception("PDF未打开")

        formulas: List[Dict[str, Any]] = []
        indicators = [
            r"Equation\s+\d+", r"Eq\.\s*\d+", r"eqn\.\s*\d+",
            r"Formula\s+\d+", r"公式\s*\d+",
            r"\(\d+\)\s*[A-Z][a-z]*\s*=",
        ]
        math_symbols = ("∑", "∫", "∂", "√", "∞", "±", "≤", "≥", "≈", "≠", "∝", "∇")
        eq_pattern = re.compile(r"[a-zA-Z]\s*=\s*[a-zA-Z0-9+\-*/^(){}√∑∫]+")

        for page_num, page in enumerate(self.reader.pages):
            text = page.extract_text() or ""
            if not text:
                continue
            for line in text.split("\n"):
                line = line.strip()
                if not line or len(line) <= 5 or len(line) >= 500:
                    continue

                is_formula = False
                context = ""
                for pat in indicators:
                    m = re.search(pat, line, re.IGNORECASE)
                    if m:
                        is_formula = True
                        context = m.group(0)
                        break
                if not is_formula:
                    if any(sym in line for sym in math_symbols):
                        is_formula = True
                        context = "数学符号公式"
                    elif eq_pattern.search(line):
                        is_formula = True
                        context = "等式"

                if is_formula:
                    formula_filename = f"page{page_num+1}_formula{len(formulas)+1}.txt"
                    formula_path = self.formulas_dir / formula_filename
                    with open(formula_path, "w", encoding="utf-8") as f:
                        f.write(f"上下文: {context}\n")
                        f.write(f"内容: {line}\n")
                    formulas.append({
                        "page": page_num + 1,
                        "index": len(formulas) + 1,
                        "filename": formula_filename,
                        "path": str(formula_path),
                        "context": context,
                        "content": line,
                    })

        print(f"✓ 公式检测：{len(formulas)} 个（文字层，精度有限，重要公式请走 vision）")
        return formulas

    # --------------------------------------------------------------- 汇总
    def extract_all(self) -> Dict[str, Any]:
        if not self.open_pdf():
            return {}
        result = {
            "pdf_path": str(self.pdf_path),
            "output_dir": str(self.output_dir),
            "text": self.extract_text(),
            "images": self.extract_images(),
            "tables": self.extract_tables(),
            "formulas": self.extract_formulas(),
        }
        useful_images = [img for img in result["images"] if img.get("is_useful")]

        result_file = self.output_dir / self.paper_key / "extraction_result.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump({
                "pdf_path": result["pdf_path"],
                "output_dir": result["output_dir"],
                "text": result["text"],
                "images_count": len(result["images"]),
                "useful_images_count": len(useful_images),
                "images": result["images"],
                "tables_count": len(result["tables"]),
                "tables": result["tables"],
                "formulas_count": len(result["formulas"]),
                "formulas": result["formulas"],
                "useful_images_dir": str(self.useful_images_dir),
                "images_dir": str(self.images_dir),
                "tables_dir": str(self.tables_dir),
                "formulas_dir": str(self.formulas_dir),
            }, f, ensure_ascii=False, indent=2)

        self.reader = None  # 释放

        summary = {
            "pdf_path": str(self.pdf_path.resolve()),
            "output_dir": str(self.output_dir.resolve()),
            "result_file": str(result_file.resolve()),
            "images": len(result["images"]),
            "useful_images": len(useful_images),
            "tables": len(result["tables"]),
            "formulas": len(result["formulas"]),
            "sections": len(result["text"]["sections"]),
            "useful_images_dir": str(self.useful_images_dir.resolve()),
            "images_dir": str(self.images_dir.resolve()),
            "tables_dir": str(self.tables_dir.resolve()),
            "formulas_dir": str(self.formulas_dir.resolve()),
        }
        # stdout 末行：单行 JSON（与 fetch_paper.py / extract_pages.py 约定一致）
        print(json.dumps(summary, ensure_ascii=False))
        return result


def main() -> int:
    ap = argparse.ArgumentParser(description="【路 C】从 PDF 提取章节文本/图片/表格标题/公式行")
    ap.add_argument("pdf", help="本地 PDF 路径")
    ap.add_argument("--out-dir", default=None,
                   help="输出根目录（默认: <pdf>_extracted/，与 extract_pages.py 同风格）")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"PDF 不存在: {pdf_path}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else pdf_path.with_suffix("").parent / f"{pdf_path.stem}_extracted"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        extractor = PaperExtractor(str(pdf_path), str(out_dir))
        result = extractor.extract_all()
        return 0 if result else 1
    except Exception as e:
        print(f"✗ 提取失败: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
