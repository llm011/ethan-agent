#!/usr/bin/env python3
"""从飞书云文档导出标准 Markdown 文件，图片可选上传 CDN。

Usage:
    python fetch_doc.py <doc_url_or_token> [output_path]

依赖：
- lark-cli（必须，已完成 auth login）
- CDN 环境变量（可选，来自 ~/.ethan/.secrets/upload-cdn.env 自动注入）
  CDN_ENDPOINT / CDN_ACCESS_KEY / CDN_SECRET_KEY / CDN_BUCKET / CDN_PUBLIC_URL

成功时 stdout 打印输出文件路径；失败时 stderr 打印错误并 exit 非0。
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


# ── 图片 URL 识别：匹配飞书内部文件链接 ──────────────────────────────────────
_FEISHU_IMG_RE = re.compile(
    r'!\[([^\]]*)\]\((https?://[^\s)]+(?:feishu\.cn|larksuite\.com)[^\s)]*)\)'
)

# ── 视频/附件 Token 识别：lark-cli 导出的媒体块格式 ─────────────────────────
# 例：*视频素材 Token: PlKEbe0lwo68UexmkZTcpBHmnLd*
_MEDIA_TOKEN_RE = re.compile(
    r'\*(?:视频素材|附件|Video|File) Token: ([A-Za-z0-9_-]+)\*'
)


def _fetch_doc_markdown(doc: str) -> str:
    """调用 lark-cli 获取文档 markdown 内容，返回 content 字符串。"""
    result = subprocess.run(
        [
            "lark-cli", "docs", "+fetch",
            "--api-version", "v2",
            "--doc", doc,
            "--doc-format", "markdown",
            "--as", "user",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        raise RuntimeError(f"lark-cli 调用失败（exit {result.returncode}）:\n{stderr or stdout}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"lark-cli 输出解析失败: {e}\n{result.stdout[:500]}")

    if not data.get("ok"):
        err = data.get("error", data)
        raise RuntimeError(f"飞书 API 错误: {json.dumps(err, ensure_ascii=False)}")

    content = data.get("data", {}).get("document", {}).get("content", "")
    if not content:
        raise RuntimeError("文档内容为空（可能没有权限或文档不存在）")
    return content


def _cdn_available() -> bool:
    required = ["CDN_ENDPOINT", "CDN_ACCESS_KEY", "CDN_SECRET_KEY", "CDN_BUCKET", "CDN_PUBLIC_URL"]
    return all(os.environ.get(k) for k in required)


def _upload_script_path() -> Path:
    # __file__ = ~/.ethan/skills/lark-doc/scripts/fetch_doc.py
    # upload_cdn.py = ~/.ethan/skills/upload-cdn/scripts/upload_cdn.py
    skills_root = Path(__file__).parent.parent.parent
    return skills_root / "upload-cdn" / "scripts" / "upload_cdn.py"


def _upload_image(url: str, key: str) -> str | None:
    """下载飞书图片，上传 CDN，返回公开 URL。失败返回 None。"""
    upload_script = _upload_script_path()
    if not upload_script.is_file():
        return None

    # 下载图片到临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix=_url_ext(url)) as tmp:
        tmp_path = tmp.name

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "lark-doc-fetcher/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            Path(tmp_path).write_bytes(resp.read())

        result = subprocess.run(
            [sys.executable, str(upload_script), tmp_path, key],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        print(f"  [warn] 图片上传失败 {key}: {result.stderr.strip()}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [warn] 图片处理失败 {url}: {e}", file=sys.stderr)
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _url_ext(url: str) -> str:
    path = url.split("?")[0]
    ext = Path(path).suffix
    return ext if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp") else ".png"


def _url_to_key(url: str, index: int) -> str:
    """生成 CDN object key：feishu-docs/HASH.ext"""
    digest = hashlib.md5(url.encode()).hexdigest()[:10]
    ext = _url_ext(url)
    return f"feishu-docs/{digest}{ext}"


def process_images(content: str, output_path: Path) -> tuple[str, int, int]:
    """扫描图片 URL，有 CDN 则上传替换，无则保留。返回 (新内容, 总图片数, 成功数)。"""
    matches = list(_FEISHU_IMG_RE.finditer(content))
    total = len(matches)
    if total == 0:
        return content, 0, 0

    if not _cdn_available():
        return content, total, 0  # 不替换，保留飞书原始链接

    # 去重：同一 URL 只上传一次
    url_to_cdn: dict[str, str | None] = {}
    for i, m in enumerate(matches):
        url = m.group(2)
        if url not in url_to_cdn:
            key = _url_to_key(url, i)
            print(f"  上传图片 {i+1}/{total}: {key}", file=sys.stderr)
            url_to_cdn[url] = _upload_image(url, key)

    def replacer(m: re.Match) -> str:
        alt = m.group(1)
        url = m.group(2)
        cdn_url = url_to_cdn.get(url)
        return f"![{alt}]({cdn_url})" if cdn_url else m.group(0)

    new_content = _FEISHU_IMG_RE.sub(replacer, content)
    succeeded = sum(1 for v in url_to_cdn.values() if v)
    return new_content, total, succeeded


def _download_media_token(token: str, media_dir: Path) -> str | None:
    """用 lark-cli docs +media-download 下载媒体文件，返回本地路径（相对于 md 文件）或 None。"""
    media_dir.mkdir(parents=True, exist_ok=True)
    # 先用 token 为文件名（lark-cli 会自动加正确扩展名）
    out_path = media_dir / token
    result = subprocess.run(
        [
            "lark-cli", "docs", "+media-download",
            "--token", token,
            "--output", str(out_path),
            "--as", "user",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"  [warn] 视频下载失败 {token}: {result.stderr.strip() or result.stdout.strip()}", file=sys.stderr)
        return None

    # lark-cli 会自动加扩展名，找实际写出的文件
    candidates = sorted(media_dir.glob(f"{token}*"))
    if not candidates:
        print(f"  [warn] 视频下载后找不到文件: {token}", file=sys.stderr)
        return None
    return candidates[0].name  # 只返回文件名，调用方拼相对路径


def process_media_tokens(content: str, output_path: Path) -> tuple[str, int, int]:
    """检测视频/附件 token，下载到 media/ 目录并替换为本地链接。返回 (新内容, 总数, 成功数)。"""
    matches = list(_MEDIA_TOKEN_RE.finditer(content))
    total = len(matches)
    if total == 0:
        return content, 0, 0

    media_dir = output_path.parent / "media"
    token_to_file: dict[str, str | None] = {}

    for i, m in enumerate(matches):
        token = m.group(1)
        if token not in token_to_file:
            print(f"  下载视频/附件 {i+1}/{total}: {token}", file=sys.stderr)
            token_to_file[token] = _download_media_token(token, media_dir)

    def replacer(m: re.Match) -> str:
        token = m.group(1)
        fname = token_to_file.get(token)
        if fname:
            return f"[📹 {fname}](./media/{fname})"
        return m.group(0)  # 下载失败保留原样

    new_content = _MEDIA_TOKEN_RE.sub(replacer, content)
    succeeded = sum(1 for v in token_to_file.values() if v)
    return new_content, total, succeeded


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: fetch_doc.py <doc_url_or_token> [output_path]", file=sys.stderr)
        sys.exit(1)

    doc = sys.argv[1]
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("document.md")

    print(f"获取文档内容: {doc}", file=sys.stderr)
    try:
        content = _fetch_doc_markdown(doc)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"处理图片...", file=sys.stderr)
    content, img_total, img_ok = process_images(content, output_path)

    print(f"处理视频/附件...", file=sys.stderr)
    content, media_total, media_ok = process_media_tokens(content, output_path)

    if img_total > 0:
        if not _cdn_available():
            content += (
                "\n\n---\n"
                "> **提示**：文档中有 " + str(img_total) + " 张图片，链接为飞书内部 URL，"
                "在本地 Markdown 编辑器中可能无法显示。\n"
                "> 配置 `upload-cdn` 密钥后重新导出可自动上传图床获得公开链接。"
            )
            print(f"  图片 {img_total} 张，未配置 CDN，保留飞书原始链接", file=sys.stderr)
        else:
            print(f"  图片 {img_total} 张，上传成功 {img_ok} 张", file=sys.stderr)

    if media_total > 0:
        print(f"  视频/附件 {media_total} 个，下载成功 {media_ok} 个", file=sys.stderr)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(str(output_path))


if __name__ == "__main__":
    main()
