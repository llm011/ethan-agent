#!/usr/bin/env python3
"""把 Map 阶段逐页产出的 page_NNN.json 收拢成一个数组，喂给 Reduce 阶段。

约定：Map 阶段把每页的 5 维度分析写成 <pages_dir>/analysis_page_NNN.json。
本脚本按页码排序合并，输出一个 JSON 数组（不做语义去重——去重是 Reduce 的 LLM 工作）。

用法：
    python merge_analysis.py ./paper_work/2603_pages
    python merge_analysis.py ./dir --glob 'analysis_page_*.json' --out merged.json

输出（stdout 末行）：{"count":N, "merged":"...merged.json"}
"""
import argparse
import json
import re
import sys
from pathlib import Path

PAGE_NUM_RE = re.compile(r"(\d+)")


def _page_key(p: Path) -> int:
    m = PAGE_NUM_RE.findall(p.stem)
    return int(m[-1]) if m else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="合并逐页分析 JSON")
    ap.add_argument("pages_dir", help="存放 analysis_page_*.json 的目录")
    ap.add_argument("--glob", default="analysis_page_*.json", help="匹配模式")
    ap.add_argument("--out", default=None, help="输出文件（默认 <dir>/merged_analysis.json）")
    args = ap.parse_args()

    d = Path(args.pages_dir)
    if not d.is_dir():
        print(f"目录不存在：{d}", file=sys.stderr)
        return 1

    files = sorted(d.glob(args.glob), key=_page_key)
    if not files:
        print(f"没找到匹配 {args.glob} 的文件", file=sys.stderr)
        return 2

    merged = []
    for f in files:
        try:
            merged.append({"page": _page_key(f), "analysis": json.loads(f.read_text(encoding="utf-8"))})
        except json.JSONDecodeError as e:
            print(f"跳过无法解析的 {f.name}：{e}", file=sys.stderr)

    out = Path(args.out) if args.out else d / "merged_analysis.json"
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"count": len(merged), "merged": str(out.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
