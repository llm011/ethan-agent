#!/usr/bin/env python3
"""【路 A：vision】逐页分析单页论文（脚本调用多模态 API，agent 框架原生不支持把图片喂给 LLM）。

agent 框架的 tool result 只能是纯文本，file_read 读 PNG 会变乱码，所以"看图精读"必须
在脚本里用 vision API 完成。本脚本接受一个页码，读该页的 PNG+文字层，调多模态模型产出
5 维度 JSON，落盘到 analysis_page_NNN.json。

为什么逐页而不是一次跑完：① 控制单次 token 量避免网关 524 超时；② agent 每调一次本脚本
= 一个 ToolEvent(start/done)，前端能逐页看到进度。

依赖 anthropic SDK：uv run --with anthropic python analyze_page_vision.py ...

环境变量：
    ANTHROPIC_BASE_URL      中转/官方端点（如 https://yuntoken.vip）
    ANTHROPIC_API_KEY       密钥（或 ANTHROPIC_AUTH_TOKEN 兼容）；走 x-api-key 头
    ANTHROPIC_MODEL         vision 模型（默认 claude-opus-4.8）
    ANTHROPIC_USER_AGENT    默认 curl/8.4.0 —— 很多中转网关的 WAF 会拦 SDK 默认 UA，
                            直连官方可忽略；如被拦可改这个

用法：
    uv run --with anthropic python analyze_page_vision.py <manifest.json> --page 3
    uv run --with anthropic python analyze_page_vision.py <manifest.json> --page 3 --out-dir ./out

stdout 末行：{"page":N, "out":"...analysis_page_003.json", "chars":C, "model":...}
"""
import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("缺少 anthropic SDK。请用：uv run --with anthropic python analyze_page_vision.py ...",
          file=sys.stderr)
    raise SystemExit(3)

PROMPT_TMPL = (
    "你在做论文逐页精读（Map 阶段）。这是论文第 {page} 页的渲染图和文字层。"
    "请严格按 5 维度分析这一页，只输出一个 JSON 对象，字段："
    "维度1_摘要 / 维度2_为什么重要 / 维度3_前人工作 / 维度4_创新点 / 维度5_实验。"
    "该页没涉及的维度留空对象。所有数字、方法名、引用必须来自这一页原文，不许编造。"
    "末尾加一个字段 \"本页备注\"，说明这页的关键图表/表格定位。\n\n"
    "文字层：\n{text}"
)


def _extract(resp) -> str:
    """网关兼容：同时取 text block 和 tool_use block（部分中转会把结构化输出包成 tool_use）。"""
    parts = []
    for b in resp.content:
        if b.type == "text":
            parts.append(b.text)
        elif b.type == "tool_use":
            try:
                parts.append(json.dumps(b.input, ensure_ascii=False))
            except Exception:
                parts.append(str(b.input))
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description="【路A vision】逐页分析单页论文")
    ap.add_argument("manifest", help="extract_pages.py 产出的 manifest.json")
    ap.add_argument("--page", type=int, required=True, help="要分析的页码（从 1 开始）")
    ap.add_argument("--out-dir", default=None, help="JSON 落盘目录（默认与 manifest 同目录）")
    ap.add_argument("--max-tokens", type=int, default=1800)
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

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not api_key:
        print("缺少 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN", file=sys.stderr)
        return 2
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4.8")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    ua = os.environ.get("ANTHROPIC_USER_AGENT", "curl/8.4.0")

    client = anthropic.Anthropic(
        base_url=base_url,
        api_key=api_key,
        default_headers={"User-Agent": ua},
    )
    prompt = PROMPT_TMPL.format(page=args.page, text=page["text"][:3500])

    # 重试：网络/网关偶发抖动
    last_err = None
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=model, max_tokens=args.max_tokens,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png_b64}},
                    {"type": "text", "text": prompt},
                ]}],
            )
            text = _extract(resp).strip()
            if text:
                break
            last_err = "空输出"
        except Exception as e:
            last_err = str(e)
            print(f"第 {args.page} 页第 {attempt+1} 次失败：{e[:120] if isinstance(e,str) else str(e)[:120]}", file=sys.stderr)
            time.sleep(5)
    else:
        print(f"第 {args.page} 页分析失败（重试 3 次）：{last_err}", file=sys.stderr)
        return 4
    text = text or ""

    out_dir = Path(args.out_dir) if args.out_dir else Path(args.manifest).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"analysis_page_{args.page:03d}.json"
    out_path.write_text(text, encoding="utf-8")

    print(json.dumps({"page": args.page, "out": str(out_path.resolve()),
                      "chars": len(text), "model": model}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
