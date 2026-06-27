#!/usr/bin/env python3
"""把 arXiv ID / URL / 本地路径统一解析为一个本地 PDF 文件。

仅用标准库（urllib），不引第三方依赖；走 HTTP(S)_PROXY 环境变量。

用法：
    python fetch_paper.py 2603.25737
    python fetch_paper.py https://arxiv.org/abs/2603.25737
    python fetch_paper.py https://example.com/foo.pdf
    python fetch_paper.py ./local.pdf
    python fetch_paper.py 2603.25737 --out-dir ./paper_work

输出（stdout 末行）：一行 JSON {"pdf_path": ..., "source": ..., "arxiv_id": ...}
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
UA = "Mozilla/5.0 (compatible; paper-analysis-skill/1.0)"


def _resolve_arxiv_id(token: str) -> str | None:
    """从纯 ID 或 arxiv URL 里抠出 arXiv ID。"""
    m = ARXIV_ID_RE.search(token)
    if m and ("arxiv" in token.lower() or token.strip() == m.group(0)):
        return m.group(1) + (m.group(2) or "")
    return None


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    # urllib 自动读取 http_proxy / https_proxy 环境变量
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    if not data[:4] == b"%PDF":
        raise ValueError(f"下载内容不是 PDF（前 4 字节={data[:4]!r}），URL: {url}")
    dest.write_bytes(data)


def main() -> int:
    ap = argparse.ArgumentParser(description="解析论文来源为本地 PDF")
    ap.add_argument("source", help="arXiv ID / arXiv URL / PDF URL / 本地 PDF 路径")
    ap.add_argument("--out-dir", default="./paper_work", help="PDF 落地目录")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    src = args.source.strip()
    arxiv_id = _resolve_arxiv_id(src)

    # 1) 本地已存在的 PDF
    local = Path(src)
    if local.exists() and local.suffix.lower() == ".pdf":
        result = {"pdf_path": str(local.resolve()), "source": "local", "arxiv_id": arxiv_id}
        print(json.dumps(result, ensure_ascii=False))
        return 0

    # 2) arXiv：拼 /pdf/<id> 下载
    if arxiv_id:
        url = f"https://arxiv.org/pdf/{arxiv_id}"
        dest = out_dir / f"{arxiv_id.replace('/', '_')}.pdf"
        try:
            _download(url, dest)
        except Exception as e:
            print(f"arXiv 下载失败：{e}", file=sys.stderr)
            return 2
        result = {"pdf_path": str(dest.resolve()), "source": "arxiv", "arxiv_id": arxiv_id}
        print(json.dumps(result, ensure_ascii=False))
        return 0

    # 3) 直接 PDF URL
    if src.lower().startswith(("http://", "https://")):
        name = re.sub(r"[^\w.\-]", "_", src.rstrip("/").split("/")[-1]) or "paper"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        dest = out_dir / name
        try:
            _download(src, dest)
        except Exception as e:
            print(f"URL 下载失败：{e}", file=sys.stderr)
            return 2
        result = {"pdf_path": str(dest.resolve()), "source": "url", "arxiv_id": None}
        print(json.dumps(result, ensure_ascii=False))
        return 0

    print(f"无法识别的来源：{src}（既不是本地 PDF，也不是 arXiv/URL）", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
