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
ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})")

# Reduce 阶段提示词模板。**不写死任何论文标题/编号**——arxiv_id 从 manifest 的
# pdf_path 自动提取后填入；标题由模型从第 1 页素材自行确定。换任何论文都能通用。
OUTLINE_TMPL = """你是一位知乎顶级的 AI 论文解读答主。下面是 arXiv:{arxiv_id} 论文逐页深度解析的 JSON 素材（每页含：页面定位/核心要点/通俗解读/图表解读/重要数字/引用关系/疑问与启发/本页备注）。

请写成一篇「知乎式深度论文解读长文」，要求：
1. **先确定论文标题**：从第 1 页素材里读出准确标题，作为文章 H1。开篇用一段引子 hook 读者：这个问题为什么难、为什么这篇论文值得读（大白话 + 一个生活化类比）
2. 背景与痛点：该领域知识/方法的困境，前人各流派的硬伤，讲清每种为什么不行
3. 核心思想：用一个精妙的类比讲透主方案，再展开关键模块的解耦/分工
4. 技术深挖（重点，讲透）：每个关键算法/流水线/协议——先讲「为什么需要它」再讲「它怎么做」，配上公式用大白话解释
5. 实验结果：主结果表 + 消融，每个关键数字点出「它说明了什么」，不要堆数字
6. 批判性思考：聪明之处、潜在局限、可质疑的点
7. 总结与启发：读者能带走什么

风格：像跟聪明的朋友聊天，有观点、有类比、有情绪，不干巴巴罗列。关键数字/引用编号要带。输出中文 markdown。

逐页素材：
"""


def _repair_escapes(s: str) -> str:
    """修复 JSON 字符串值里的非法反斜杠转义（LaTeX 如 \\hat、\\theta）。

    在字符串内部，\\ 后跟合法转义字符（" \\ / b f n r t u）才保留单斜杠，
    否则翻倍成 \\\\。围栏外的结构不动。
    """
    valid = set('"\\/bfnrtu')
    out, in_str, i, n = [], False, 0, len(s)
    while i < n:
        ch = s[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            i += 1
            continue
        if ch == "\\":
            if i + 1 < n and (s[i + 1] in valid or s[i + 1] == "u"):
                out.append(ch); out.append(s[i + 1]); i += 2
            else:
                out.append("\\\\"); i += 1
            continue
        if ch == '"':
            in_str = False
        out.append(ch); i += 1
    return "".join(out)


def _load_analysis(path: Path):
    """读取一个逐页分析文件为 dict。容忍 ```json 围栏与 LaTeX 非法转义。"""
    raw = path.read_text(encoding="utf-8").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    if not raw.startswith("{"):
        i, j = raw.find("{"), raw.rfind("}")
        if i != -1 and j != -1:
            raw = raw[i:j + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(_repair_escapes(raw))


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
            merged.append({"page": _page_key(f), "analysis": _load_analysis(f)})
        except (json.JSONDecodeError, Exception) as e:
            print(f"跳过无法解析的 {f.name}：{e}", file=sys.stderr)

    out = Path(args.out) if args.out else d / "merged_analysis.json"
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    # 从 manifest 的 pdf_path 自动提取 arxiv_id（非 arxiv 来源则为空），生成
    # 参数化的 Reduce 提示词文件——不写死标题，换任何论文通用。
    arxiv_id = ""
    manifest_path = d / "manifest.json"
    if manifest_path.exists():
        try:
            pdf_path = json.loads(manifest_path.read_text(encoding="utf-8")).get("pdf_path", "")
            m = ARXIV_ID_RE.search(Path(pdf_path).name)
            if m:
                arxiv_id = m.group(1)
        except Exception:
            pass
    reduce_prompt_path = d / "reduce_prompt.txt"
    reduce_prompt_path.write_text(OUTLINE_TMPL.format(arxiv_id=arxiv_id or "<未知>"), encoding="utf-8")

    print(json.dumps({"count": len(merged), "merged": str(out.resolve()),
                      "arxiv_id": arxiv_id, "reduce_prompt": str(reduce_prompt_path.resolve())},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
