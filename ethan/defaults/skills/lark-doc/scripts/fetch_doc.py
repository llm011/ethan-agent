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
from pathlib import Path

# ── 图片 URL 识别：匹配飞书内部文件链接 ──────────────────────────────────────
_FEISHU_IMG_RE = re.compile(
    r'!\[([^\]]*)\]\((https?://(?:[^\s/?#)]*\.)?(?:feishu\.cn|larksuite\.com)(?:[/?#:][^\s)]*)?)\)'
)

# ── 视频/附件 Token 识别：lark-cli 导出的媒体块格式 ─────────────────────────
# 例：*视频素材 Token: PlKEbe0lwo68UexmkZTcpBHmnLd*
_MEDIA_TOKEN_RE = re.compile(
    r'\*(?:视频素材|附件|Video|File) Token: ([A-Za-z0-9_-]+)\*'
)

# ── XML img 标签：提取 token 和 url 的映射 ──────────────────────────────────
_XML_IMG_RE = re.compile(r'<img\b[^>]*\btoken="([^"]+)"[^>]*\burl="([^"]+)"', re.IGNORECASE)
_XML_IMG_RE2 = re.compile(r'<img\b[^>]*\burl="([^"]+)"[^>]*\btoken="([^"]+)"', re.IGNORECASE)

# ── 残留 DocxXML 标签清洗 ───────────────────────────────────────────────────
_TITLE_RE = re.compile(r'<title>(.*?)</title>', re.IGNORECASE | re.DOTALL)
_CITE_RE = re.compile(r'<cite\b([^>]*)>\s*</cite>', re.IGNORECASE)
# ISV 只读块：先在 process_isv_blocks 尝试下载，失败后由 clean_markdown 换成占位
_READONLY_ISV_RE = re.compile(
    r'<readonly-block\b[^>]*\bid="([^"]+)"[^>]*\btype="isv"[^>]*>\s*</readonly-block>',
    re.IGNORECASE,
)
_READONLY_RE = re.compile(r'<readonly-block\b[^>]*>\s*</readonly-block>', re.IGNORECASE)
_CALLOUT_RE = re.compile(r'<callout\b([^>]*)>(.*?)</callout>', re.IGNORECASE | re.DOTALL)
_CALLOUT_EMOJI_RE = re.compile(r'\bemoji="([^"]*)"', re.IGNORECASE)
# 匹配任意 HTML/组件开闭/自闭合标签（含 <UIResourceRenderer />、<h1> 等）
_ANY_TAG_RE = re.compile(r'</?[a-zA-Z][a-zA-Z0-9-]*(?:\s[^<>]*?)?/?>')


def _run_lark_cli(*args: str, timeout: int = 60) -> dict:
    """运行 lark-cli，返回解析后的 JSON dict。失败抛 RuntimeError。"""
    result = subprocess.run(
        ["lark-cli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"lark-cli 调用失败（exit {result.returncode}）:\n{(result.stderr or result.stdout).strip()}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"lark-cli 输出解析失败: {e}\n{result.stdout[:500]}")
    if not data.get("ok"):
        raise RuntimeError(f"飞书 API 错误: {json.dumps(data.get('error', data), ensure_ascii=False)}")
    return data


def _fetch_doc_markdown(doc: str) -> tuple[str, str]:
    """返回 (markdown 内容, document_id)。"""
    data = _run_lark_cli(
        "docs", "+fetch", "--api-version", "v2",
        "--doc", doc, "--doc-format", "markdown", "--as", "user",
    )
    document = data.get("data", {}).get("document", {})
    content = document.get("content", "")
    if not content:
        raise RuntimeError("文档内容为空（可能没有权限或文档不存在）")
    return content, document.get("document_id", "")


def _fetch_doc_xml(doc: str) -> str:
    """获取 XML 格式文档内容（含 block id），用于提取 img token 和 ISV block id。失败返回空串。"""
    try:
        data = _run_lark_cli(
            "docs", "+fetch", "--api-version", "v2",
            "--doc", doc, "--doc-format", "xml", "--detail", "with-ids", "--as", "user",
        )
        return data.get("data", {}).get("document", {}).get("content", "")
    except Exception as e:
        print(f"  [warn] 获取 XML 格式失败，图片/ISV 块将无法处理: {e}", file=sys.stderr)
        return ""


def _build_url_token_map(xml_content: str) -> dict[str, str]:
    """从 XML 内容提取 url→token 映射。"""
    mapping: dict[str, str] = {}
    for m in _XML_IMG_RE.finditer(xml_content):
        token, url = m.group(1), m.group(2)
        mapping[url] = token
    for m in _XML_IMG_RE2.finditer(xml_content):
        url, token = m.group(1), m.group(2)
        mapping[url] = token
    return mapping


def _base_domain(doc: str) -> str:
    """从文档 URL 提取 https://xxx.feishu.cn 域名，用于构造内部文档链接。"""
    from urllib.parse import urlparse
    p = urlparse(doc)
    if p.scheme and p.netloc:
        return f"{p.scheme}://{p.netloc}"
    return "https://feishu.cn"


def _cite_to_link(m: re.Match, base_domain: str) -> str:
    """把 <cite doc-id="..." file-type="..." title="..."> 转成 [title](url)。"""
    attrs = m.group(1)
    doc_id = (re.search(r'\bdoc-id="([^"]+)"', attrs) or re.search(r'\bdoc-id=\'([^\']+)\'', attrs))
    file_type = (re.search(r'\bfile-type="([^"]+)"', attrs) or re.search(r"\bfile-type='([^']+)'", attrs))
    title_m = (re.search(r'\btitle="([^"]+)"', attrs) or re.search(r"\btitle='([^']+)'", attrs))

    title = title_m.group(1) if title_m else ""
    if not doc_id:
        return title  # 没有 doc-id，只保留 title 文字

    ftype = file_type.group(1) if file_type else "docx"
    path = "wiki" if ftype == "wiki" else "docx"
    url = f"{base_domain}/{path}/{doc_id.group(1)}"
    return f"[{title}]({url})" if title else url


def _resolve_user_name(open_id: str, cache: dict[str, str]) -> str:
    """把 open_id 解析成用户名，失败返回原 id。带缓存。"""
    if not open_id:
        return ""
    if open_id in cache:
        return cache[open_id]
    name = open_id
    try:
        data = _run_lark_cli(
            "contact", "+get-user",
            "--user-id", open_id, "--user-id-type", "open_id", "--as", "user",
        )
        user = data.get("data", {}).get("user", {})
        name = user.get("name") or user.get("en_name") or open_id
    except Exception:
        pass
    cache[open_id] = name
    return name


def _fmt_ts(ts: str) -> str:
    """unix 秒字符串 → 'YYYY-MM-DD HH:MM'，失败返回原值。"""
    from datetime import datetime, timedelta, timezone
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone(timedelta(hours=8)))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return ts or ""


def _fetch_doc_meta(document_id: str) -> dict:
    """通过 drive metas batch_query 获取文档基本信息。失败返回 {}。"""
    if not document_id:
        return {}
    try:
        data = _run_lark_cli(
            "drive", "metas", "batch_query", "--as", "user",
            "--data", json.dumps({
                "request_docs": [{"doc_token": document_id, "doc_type": "docx"}],
                "with_url": True,
            }),
        )
    except Exception as e:
        msg = str(e)
        if "drive.metadata" in msg or "missing_scope" in msg:
            print("  [warn] 缺少 drive:drive.metadata:readonly 权限，跳过元信息。"
                  "补授权：lark-cli auth login --scope \"drive:drive.metadata:readonly\"", file=sys.stderr)
        else:
            print(f"  [warn] 获取文档元信息失败: {e}", file=sys.stderr)
        return {}

    metas = data.get("data", {}).get("metas", [])
    if not metas:
        return {}
    m = metas[0]
    name_cache: dict[str, str] = {}
    return {
        "title": m.get("title", ""),
        "url": m.get("url", ""),
        "owner": _resolve_user_name(m.get("owner_id", ""), name_cache),
        "create_time": _fmt_ts(m.get("create_time", "")),
        "modify_user": _resolve_user_name(m.get("latest_modify_user", ""), name_cache),
        "modify_time": _fmt_ts(m.get("latest_modify_time", "")),
    }


def _render_meta_block(meta: dict) -> str:
    """把元信息渲染成 markdown 头部块（blockquote，ProseMirror 友好）。"""
    if not meta:
        return ""
    owner = meta.get("owner")
    modify_user = meta.get("modify_user")
    create_time = meta.get("create_time")
    modify_time = meta.get("modify_time")
    url = meta.get("url")

    lines: list[str] = []

    # 第一行：作者（+ 最近编辑，仅当与作者不同）
    people = []
    if owner:
        people.append(f"**作者**：{owner}")
    if modify_user and modify_user != owner:
        people.append(f"**最近编辑**：{modify_user}")
    if people:
        lines.append("> " + " | ".join(people))

    # 第二行：创建时间 + 最近修改时间
    times = []
    if create_time:
        times.append(f"**创建时间**：{create_time}")
    if modify_time:
        times.append(f"**最近修改时间**：{modify_time}")
    if times:
        lines.append("> " + " | ".join(times))

    # 第三行：原文链接
    if url:
        lines.append(f"> **原文链接**：{url}")

    return ("\n".join(lines) + "\n\n") if lines else ""


def _cdn_available() -> bool:
    required = ["CDN_ENDPOINT", "CDN_ACCESS_KEY", "CDN_SECRET_KEY", "CDN_BUCKET", "CDN_PUBLIC_URL"]
    return all(os.environ.get(k) for k in required)


def _upload_script_path() -> Path:
    skills_root = Path(__file__).parent.parent.parent
    return skills_root / "upload-cdn" / "scripts" / "upload_cdn.py"


def _download_img_by_token(token: str) -> "str | None":
    """用 lark-cli docs +media-download 下载图片到临时文件，返回路径或 None。"""
    suffix = ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name

    # lark-cli 会自动加扩展名，所以先给个无扩展名的路径
    base_path = tmp_path[:-len(suffix)]
    result = subprocess.run(
        [
            "lark-cli", "docs", "+media-download",
            "--token", token,
            "--output", base_path,
            "--as", "user",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    # 删掉预创建的临时文件（lark-cli 会写新文件名）
    try:
        Path(tmp_path).unlink(missing_ok=True)
    except OSError:
        pass

    if result.returncode != 0:
        print(f"  [warn] 图片下载失败 token={token}: {(result.stderr or result.stdout).strip()}", file=sys.stderr)
        return None

    # lark-cli 会自动补扩展名
    candidates = sorted(Path(base_path).parent.glob(Path(base_path).name + "*"))
    if not candidates:
        # 也可能直接写到了 base_path
        if Path(base_path).is_file():
            return base_path
        print(f"  [warn] 图片下载后找不到文件: token={token}", file=sys.stderr)
        return None
    return str(candidates[0])


def _upload_image(token: str, url: str, key: str) -> "str | None":
    """下载飞书图片（走 lark-cli 认证），上传 CDN，返回公开 URL。失败返回 None。"""
    upload_script = _upload_script_path()
    if not upload_script.is_file():
        print(f"  [warn] 找不到 upload_cdn.py: {upload_script}", file=sys.stderr)
        return None

    tmp_path = _download_img_by_token(token)
    if not tmp_path:
        return None

    try:
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
        print(f"  [warn] 图片上传异常 {key}: {e}", file=sys.stderr)
        return None
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass


def _url_ext(url: str) -> str:
    path = url.split("?")[0]
    ext = Path(path).suffix
    return ext if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp") else ".png"


def _url_to_key(url: str) -> str:
    """生成 CDN object key：feishu-docs/HASH.ext"""
    digest = hashlib.md5(url.encode()).hexdigest()[:10]
    ext = _url_ext(url)
    return f"feishu-docs/{digest}{ext}"


def _escape_tags_outside_code(text: str) -> str:
    """把残留的 HTML/组件标签转义成实体，但保护 ``` 代码块和 `行内代码`。"""
    def _esc(seg: str) -> str:
        return _ANY_TAG_RE.sub(
            lambda m: m.group(0).replace("<", "&lt;").replace(">", "&gt;"), seg
        )
    out = []
    for i, block in enumerate(re.split(r'(```[\s\S]*?```)', text)):
        if i % 2 == 1:  # 代码块，原样保留
            out.append(block)
            continue
        for j, span in enumerate(re.split(r'(`[^`\n]*`)', block)):
            out.append(span if j % 2 == 1 else _esc(span))
    return "".join(out)


def _callout_to_blockquote(m: re.Match) -> str:
    attrs = m.group(1) or ""
    em = _CALLOUT_EMOJI_RE.search(attrs)
    emoji = em.group(1) if em else ""
    inner = m.group(2).strip()
    lines = [ln.strip() for ln in inner.splitlines() if ln.strip()]
    if not lines:
        return ""
    prefix = (emoji + " ") if emoji else ""
    quoted = [f"> {prefix}{lines[0]}"] + [f"> {ln}" for ln in lines[1:]]
    return "\n" + "\n".join(quoted) + "\n"


def clean_markdown(content: str, base_domain: str = "https://feishu.cn") -> str:
    """清洗飞书 markdown 导出里残留的 DocxXML 标签，避免 ProseMirror 渲染丢内容/变换行。"""
    content = _TITLE_RE.sub(lambda m: f"# {m.group(1).strip()}\n", content)
    content = _CALLOUT_RE.sub(_callout_to_blockquote, content)
    content = _CITE_RE.sub(lambda m: _cite_to_link(m, base_domain), content)
    # 剩余未被 process_isv_blocks 替换掉的 readonly-block 换占位
    content = _READONLY_RE.sub(
        "> ⚠️ 此处为第三方交互嵌入块（ISV widget），导出接口无法获取内容，已省略。",
        content,
    )
    content = _escape_tags_outside_code(content)
    return content


def process_isv_blocks(content: str, output_path: Path, isv_block_ids: list) -> tuple[str, int, int]:
    """尝试把 ISV 只读块（Mermaid/画板等）下载成图片并替换。
    isv_block_ids 从 XML 中按顺序提取；markdown 里对应位置的 <readonly-block> 按顺序替换。
    先试 whiteboard 类型，再试 media 类型；有 CDN 则上传，无则存到 media/。
    返回 (新内容, 总数, 成功数)。"""
    # 找 markdown 里所有 readonly-block（可能有 id 也可能没有）
    md_blocks = list(re.finditer(r'<readonly-block\b[^>]*>\s*</readonly-block>', content, re.IGNORECASE))
    total = len(md_blocks)
    if total == 0 or not isv_block_ids:
        return content, total, 0

    media_dir = output_path.parent / "media"
    upload_script = _upload_script_path()
    succeeded = 0
    # 替换时从后往前，避免位置偏移
    pairs = list(zip(md_blocks, isv_block_ids))

    for i, (md_match, block_id) in enumerate(reversed(pairs)):
        print(f"  处理 ISV 块 {total - i}/{total}: {block_id}", file=sys.stderr)

        local_path: "str | None" = None

        for dl_type in ("whiteboard", "media"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                tmp_path = tmp.name
            base_path = tmp_path[:-4]
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass

            result = subprocess.run(
                [
                    "lark-cli", "docs", "+media-download",
                    "--type", dl_type,
                    "--token", block_id,
                    "--output", base_path,
                    "--as", "user",
                ],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                candidates = sorted(Path(base_path).parent.glob(Path(base_path).name + "*"))
                if candidates:
                    local_path = str(candidates[0])
                    break
                if Path(base_path).is_file():
                    local_path = base_path
                    break
            else:
                err = result.stderr or result.stdout
                if "missing_scope" in err or "missing required scope" in err:
                    print("  [warn] ISV 块下载缺少权限，需运行: lark-cli auth login --scope \"docs:document.media:download\"", file=sys.stderr)
                    return content, total, succeeded

        if not local_path:
            continue

        cdn_url: "str | None" = None
        if _cdn_available() and upload_script.is_file():
            key = f"feishu-docs/isv-{hashlib.md5(block_id.encode()).hexdigest()[:10]}.png"
            r = subprocess.run(
                [sys.executable, str(upload_script), local_path, key],
                capture_output=True, text=True, timeout=60,
            )
            if r.returncode == 0:
                cdn_url = r.stdout.strip()
        if not cdn_url:
            media_dir.mkdir(parents=True, exist_ok=True)
            fname = f"isv-{block_id[:12]}{Path(local_path).suffix}"
            dest = media_dir / fname
            Path(local_path).rename(dest)
            cdn_url = f"./media/{fname}"
        else:
            try:
                Path(local_path).unlink(missing_ok=True)
            except OSError:
                pass

        replacement = f"![]({cdn_url})"
        content = content[:md_match.start()] + replacement + content[md_match.end():]
        succeeded += 1
        print(f"  ISV 块已转换: {cdn_url}", file=sys.stderr)

    return content, total, succeeded


def process_images(content: str, url_token_map: dict[str, str]) -> tuple[str, int, int]:
    """扫描图片 URL，有 CDN 且有 token 则下载上传替换，无则保留。返回 (新内容, 总图片数, 成功数)。"""
    matches = list(_FEISHU_IMG_RE.finditer(content))
    total = len(matches)
    if total == 0:
        return content, 0, 0

    if not _cdn_available():
        return content, total, 0  # 不替换，保留飞书原始链接

    if not url_token_map:
        print("  [warn] 未能提取 img token，图片将保留飞书原始链接", file=sys.stderr)
        return content, total, 0

    # 去重：同一 URL 只处理一次
    url_to_cdn: dict[str, "str | None"] = {}
    unique_urls = list(dict.fromkeys(m.group(2) for m in matches))

    for i, url in enumerate(unique_urls):
        token = url_token_map.get(url)
        if not token:
            print(f"  [warn] 找不到 token for URL: {url[:80]}", file=sys.stderr)
            url_to_cdn[url] = None
            continue
        key = _url_to_key(url)
        print(f"  上传图片 {i+1}/{len(unique_urls)}: {key}", file=sys.stderr)
        url_to_cdn[url] = _upload_image(token, url, key)

    def replacer(m: re.Match) -> str:
        alt = m.group(1)
        url = m.group(2)
        cdn_url = url_to_cdn.get(url)
        return f"![{alt}]({cdn_url})" if cdn_url else m.group(0)

    new_content = _FEISHU_IMG_RE.sub(replacer, content)
    succeeded = sum(1 for v in url_to_cdn.values() if v)
    return new_content, total, succeeded


def _download_media_token(token: str, media_dir: Path) -> "str | None":
    """用 lark-cli docs +media-download 下载媒体文件，返回文件名或 None。"""
    media_dir.mkdir(parents=True, exist_ok=True)
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
        print(f"  [warn] 视频下载失败 {token}: {(result.stderr or result.stdout).strip()}", file=sys.stderr)
        return None

    candidates = sorted(media_dir.glob(f"{token}*"))
    if not candidates:
        print(f"  [warn] 视频下载后找不到文件: {token}", file=sys.stderr)
        return None
    return candidates[0].name


def process_media_tokens(content: str, output_path: Path) -> tuple[str, int, int]:
    """检测视频/附件 token，下载到 media/ 目录并替换为本地链接。返回 (新内容, 总数, 成功数)。"""
    matches = list(_MEDIA_TOKEN_RE.finditer(content))
    total = len(matches)
    if total == 0:
        return content, 0, 0

    media_dir = output_path.parent / "media"
    token_to_file: dict[str, "str | None"] = {}

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
        return m.group(0)

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
        content, document_id = _fetch_doc_markdown(doc)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print("获取文档基本信息...", file=sys.stderr)
    meta = _fetch_doc_meta(document_id)

    # 提取 url→token 映射（需要额外一次 XML fetch）
    url_token_map: dict[str, str] = {}
    isv_block_ids: list[str] = []
    # 总是获取 XML（含 block id），用于图片 token 和 ISV 块 id
    print("获取 XML 格式以提取图片 token 和 ISV 块...", file=sys.stderr)
    xml_content = _fetch_doc_xml(doc)
    if xml_content:
        url_token_map = _build_url_token_map(xml_content)
        isv_block_ids = re.findall(
            r'<readonly-block\s+id="([^"]+)"\s+type="isv"', xml_content
        ) or re.findall(
            r'<readonly-block[^>]+\btype="isv"[^>]+\bid="([^"]+)"', xml_content
        )
        print(f"  图片 token {len(url_token_map)} 个，ISV 块 {len(isv_block_ids)} 个", file=sys.stderr)

    print("处理图片...", file=sys.stderr)
    content, img_total, img_ok = process_images(content, url_token_map)

    print("处理 ISV 块（Mermaid/画板）...", file=sys.stderr)
    content, isv_total, isv_ok = process_isv_blocks(content, output_path, isv_block_ids)

    print("处理视频/附件...", file=sys.stderr)
    content, media_total, media_ok = process_media_tokens(content, output_path)

    print("清洗残留标签...", file=sys.stderr)
    content = clean_markdown(content, base_domain=_base_domain(doc))

    # 在标题后插入元信息块
    meta_block = _render_meta_block(meta)
    if meta_block:
        lines = content.split("\n", 1)
        if lines and lines[0].startswith("# "):
            rest = lines[1] if len(lines) > 1 else ""
            content = lines[0] + "\n\n" + meta_block + rest.lstrip("\n")
        else:
            content = meta_block + content

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
