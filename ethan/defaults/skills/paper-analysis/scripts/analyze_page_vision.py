#!/usr/bin/env python3
"""【路 A：vision】逐页分析单页论文（脚本调用多模态 API）。

agent 框架的 tool result 只能是纯文本，file_read 读 PNG 会变乱码，所以"看图精读"必须
在脚本里用 vision API 完成。本脚本接受一个页码，读该页的 PNG+文字层，调多模态模型产出
5 维度 JSON，落盘到 analysis_page_NNN.json。

为什么逐页而不是一次跑完：① 控制单次 token 量避免网关 524 超时；② agent 每调一次本脚本
= 一个 ToolEvent(start/done)，前端能逐页看到进度。

用 OpenAI 兼容协议（绝大多数中转网关 yuntoken/lkfhome/new-api 以及 OpenAI/Anthropic
官方的兼容层都走这个），统一 image_url base64 格式。依赖 openai SDK：
    uv run --with openai python analyze_page_vision.py ...

环境变量（按优先级，VISION_* 优先于 OPENAI_*）：
    VISION_BASE_URL / OPENAI_BASE_URL   端点（如 https://api.lkfhome.cn:29999/v1）
    VISION_API_KEY  / OPENAI_API_KEY    密钥
    VISION_MODEL    / OPENAI_MODEL      vision 模型（如 gemini-3.1-flash-lite）
    VISION_USER_AGENT                   默认 curl/8.4.0 —— 很多中转网关 WAF 拦 SDK 默认 UA

用法：
    uv run --with openai python analyze_page_vision.py <manifest.json> --page 3
    uv run --with openai python analyze_page_vision.py <manifest.json> --page 3 --out-dir ./out

stdout 末行：{"page":N, "out":"...analysis_page_003.json", "chars":C, "model":...}
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("缺少 openai SDK。请用：uv run --with openai python analyze_page_vision.py ...",
          file=sys.stderr)
    raise SystemExit(3)

PROMPT_TMPL = (
    "你在为「知乎式深度论文解读」做逐页素材提取（Map 阶段）。这是论文第 {page} 页的渲染图和文字层。"
    "请像一位真正读懂了这篇论文的研究者那样,把这一页嚼碎,只输出一个 JSON 对象,字段如下:\n"
    "- 页面定位:这一页在全篇讲什么(标题/小节名)\n"
    "- 核心要点:本页的关键信息、定义、公式、结论(必须带原文数字/符号/引用编号)\n"
    "- 通俗解读:把本页最难的技术点用大白话+一个贴切类比讲清楚(像给非该领域的研究生讲)\n"
    "- 图表解读:若有图/表/伪代码/架构图,描述它的结构、每部分含义、它揭示了什么(不能只说'有张图')\n"
    "- 重要数字:本页出现的所有具体数值/百分比/参数量/实验指标,逐个列出\n"
    "- 引用关系:本页引用了哪些前人工作[编号],作者用它支持/对比什么\n"
    "- 疑问与启发:本页让你想到的延伸问题、潜在局限、或对读者的启发\n\n"
    "要求:所有内容必须来自这一页原文,不许编造;没涉及的字段留空。末尾加字段 \"本页备注\"。\n\n"
    "文字层(可能不全,以渲染图为准):\n{text}"
)


def _env(*keys: str) -> str | None:
    for k in keys:
        v = os.environ.get(k)
        if v:
            return v
    return None


def _extract_json(text: str) -> str:
    """模型常把 JSON 包在 ```json ... ``` 围栏里，剥掉围栏，取最外层 {...}。

    保证落盘的是干净 JSON，下游 merge_analysis / Reduce 不用再处理围栏。
    另：模型常把 LaTeX 公式（\\hat{a}、\\theta）直接塞进 JSON 字符串，
    反斜杠后跟非法转义字符（如 \\h）会让 json.loads 报错，这里做修复。
    """
    s = text.strip()
    # 去掉开头的 ```json / ``` 和结尾的 ```
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
        s = s.strip()
    # 兜底：若还有杂字符，取第一个 { 到最后一个 }
    if not s.startswith("{"):
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j != -1 and j > i:
            s = s[i:j + 1]
    # 尝试解析；失败则修复非法转义（LaTeX 反斜杠）后重试
    try:
        json.loads(s)
        return s
    except json.JSONDecodeError:
        return _repair_escapes(s)


def _repair_escapes(s: str) -> str:
    """把 JSON 字符串里的非法反斜杠转义修成合法（\\h → \\\\h）。

    仅在 JSON 字符串值内部生效（遇 " 配对跳过键名/结构）。合法转义：
    "  \\  /  b  f  n  r  t  uXXXX。其余 \\X 一律把反斜杠翻倍。
    """
    valid = set('"\\/bfnrtu')
    out = []
    in_str = False
    escape = False
    for ch in s:
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            continue
        # in_str
        if escape:
            escape = False
            out.append(ch)
            continue
        if ch == "\\":
            # 看下一个字符是否合法转义；此处先吞掉反斜杠，下一个字符在合法集才保留单斜杠
            out.append(ch)
            escape = True
            continue
        if ch == '"':
            in_str = False
        out.append(ch)
    # 第二遍：对字符串内的非法转义翻倍（上面只标记了 escape，这里真正修复）
    # 重新实现更直接的版本：
    return _repair_escapes_impl(s)


def _repair_escapes_impl(s: str) -> str:
    valid_after = set('"\\/bfnrtu')
    out = []
    in_str = False
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            i += 1
            continue
        # 在字符串内
        if ch == "\\":
            if i + 1 < n and s[i + 1] in valid_after:
                out.append(ch)
                out.append(s[i + 1])
                i += 2
            elif i + 1 < n and s[i + 1] == "u":
                out.append(ch)
                out.append(s[i + 1])
                i += 2
            else:
                # 非法转义：翻倍反斜杠
                out.append("\\\\")
                i += 1
            continue
        if ch == '"':
            in_str = False
        out.append(ch)
        i += 1
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="【路A vision】逐页分析单页论文")
    ap.add_argument("manifest", help="extract_pages.py 产出的 manifest.json")
    ap.add_argument("--page", type=int, required=True, help="要分析的页码（从 1 开始）")
    ap.add_argument("--out-dir", default=None, help="JSON 落盘目录（默认与 manifest 同目录）")
    ap.add_argument("--max-tokens", type=int, default=20000, help="输出 token 上限（gemini 3.x 是思维链模型，token 太少会被内部推理吃光导致空输出，默认 20000）")
    ap.add_argument("--timeout", type=int, default=120, help="单次 API 调用超时秒数")
    ap.add_argument("--retries", type=int, default=5, help="失败重试次数（默认 5，指数退避）")
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    page = next((p for p in manifest["pages"] if p["page"] == args.page), None)
    if not page:
        print(f"manifest 里没有第 {args.page} 页", file=sys.stderr)
        return 1

    png = Path(page["png"])
    if not png.exists():
        print(f"页面渲染图不存在：{png}", file=sys.stderr)
        return 1
    png_b64 = base64.standard_b64encode(png.read_bytes()).decode()

    api_key = _env("VISION_API_KEY", "OPENAI_API_KEY")
    if not api_key:
        print("缺少 VISION_API_KEY / OPENAI_API_KEY", file=sys.stderr)
        return 2
    base_url = _env("VISION_BASE_URL", "OPENAI_BASE_URL")
    model = _env("VISION_MODEL", "OPENAI_MODEL", "VISION_DEFAULT_MODEL") or "gpt-4o"
    ua = os.environ.get("VISION_USER_AGENT", "curl/8.4.0")

    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
        default_headers={"User-Agent": ua},
        timeout=args.timeout,
    )
    prompt = PROMPT_TMPL.format(page=args.page, text=page["text"][:3500])

    # 重试：中转网关（lkfhome 等）后端轮询不稳，常表现为 503/"model_not_found"——
    # 并不是模型名错，而是请求被路由到一个当下没加载该模型的后端节点。瞬时性、可重试。
    # 策略：指数退避（2,4,8,15,25s），只对"可重试"错误退避；认证/参数类 4xx 立即失败。
    from openai import (
        APIConnectionError, APITimeoutError, RateLimitError,
        APIStatusError, InternalServerError,
    )

    def _retryable(e: Exception) -> tuple[bool, str]:
        """返回 (是否可重试, 简短原因)。"""
        if isinstance(e, (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)):
            return True, f"{type(e).__name__}"
        if isinstance(e, APIStatusError):
            code = e.status_code or 0
            # 5xx / 429 网关瞬时故障 → 重试；4xx（除 429）参数/认证错 → 立即失败
            if code >= 500 or code == 429:
                # 503 model_not_found 属此类：网关后端不可用
                return True, f"HTTP {code}"
            return False, f"HTTP {code}"
        # 其它未知异常保守重试一次（网络偶发）
        return True, type(e).__name__

    backoffs = [2, 4, 8, 15, 25]
    last_err = None
    text = ""
    for attempt in range(args.retries):
        try:
            resp = client.chat.completions.create(
                model=model, max_tokens=args.max_tokens,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_b64}"}},
                ]}],
            )
            msg = resp.choices[0].message
            # 部分中转网关把结构化输出包成 tool_call
            text = (msg.content or "").strip()
            if not text and msg.tool_calls:
                text = (msg.tool_calls[0].function.arguments or "").strip()
            if text:
                break
            last_err = "空输出（模型未返回内容）"
        except Exception as e:
            last_err = f"{_retryable(e)[1]}: {str(e)[:120]}"
            ok, why = _retryable(e)
            if not ok:
                # 致命错误：不重试
                print(f"第 {args.page} 页致命错误（不重试）：{last_err}", file=sys.stderr)
                return 5
            print(f"第 {args.page} 页第 {attempt+1}/{args.retries} 次失败（{why}，将重试）：{last_err}", file=sys.stderr)
        if attempt < args.retries - 1:
            wait = backoffs[min(attempt, len(backoffs) - 1)]
            time.sleep(wait)
    else:
        print(f"第 {args.page} 页分析失败（重试 {args.retries} 次）：{last_err}", file=sys.stderr)
        return 4

    out_dir = Path(args.out_dir) if args.out_dir else Path(args.manifest).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"analysis_page_{args.page:03d}.json"
    clean = _extract_json(text)  # 剥围栏，保证落盘是干净 JSON（兼容有/无围栏两种情况）
    out_path.write_text(clean, encoding="utf-8")

    print(json.dumps({"page": args.page, "out": str(out_path.resolve()),
                      "chars": len(clean), "model": model}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
