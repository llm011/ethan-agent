#!/usr/bin/env python3
"""gen_image.py — deck JSON 图片占位符瀑布流解析器。

扫描 deck 中所有 image 元素（含 background.image）的 src：
  - `gen:搜索词`      → 照片瀑布流：Pexels → Unsplash → AI 生图 → 纯色占位 PNG
  - `icon:集合:名称`  → Iconify（免费无需 key，如 icon:mdi:rocket-launch）
  - 空 src + imageQuery 字段 → 等同 gen:imageQuery

解析后把 src 改写为本地相对路径（<deck名>.assets/ 下），deck JSON 原地更新。

环境变量（都不配时自动降级到占位图，不报错）：
  PEXELS_API_KEY            Pexels 照片（推荐，免费注册 https://www.pexels.com/api/）
  UNSPLASH_ACCESS_KEY       Unsplash 照片
  ETHAN_IMAGE_GEN_BASE_URL  AI 生图 OpenAI 兼容端点（默认 https://api.openai.com/v1）
  ETHAN_IMAGE_GEN_API_KEY   AI 生图 key
  ETHAN_IMAGE_GEN_MODEL     AI 生图模型（默认 dall-e-3，可换便宜模型）

用法:
  python3 gen_image.py deck.json [--assets-dir DIR] [--dry-run] [--placeholder-color "#E5E7EB"]
  python3 gen_image.py <项目目录>   # 含 deck.json + pages/*.json，逐页原地更新

纯标准库实现，无第三方依赖。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

from project_loader import default_assets_dir, load_deck, write_back

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
TIMEOUT = 30


# ---------------------------------------------------------------------------
# HTTP 工具（stdlib）
# ---------------------------------------------------------------------------

def http_get_json(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_download(url: str, dest: Path, headers: dict | None = None) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
        if len(data) < 512:  # 太小多半是错误页
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 下载失败 {url[:80]}: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 图源：Pexels / Unsplash / AI 生图 / 占位
# ---------------------------------------------------------------------------

def try_pexels(query: str) -> str | None:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return None
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "per_page": 3, "orientation": "landscape"}
    )
    try:
        data = http_get_json(url, {"Authorization": key})
        for photo in data.get("photos") or []:
            src = (photo.get("src") or {}).get("large2x") or photo.get("src", {}).get("large")
            if src:
                return src
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] Pexels 查询失败: {e}", file=sys.stderr)
    return None


def try_unsplash(query: str) -> str | None:
    key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not key:
        return None
    url = "https://api.unsplash.com/search/photos?" + urllib.parse.urlencode(
        {"query": query, "per_page": 3, "orientation": "landscape"}
    )
    try:
        data = http_get_json(url, {"Authorization": f"Client-ID {key}"})
        for photo in data.get("results") or []:
            src = (photo.get("urls") or {}).get("regular")
            if src:
                return src
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] Unsplash 查询失败: {e}", file=sys.stderr)
    return None


def try_ai_image(query: str, dest: Path) -> bool:
    """OpenAI 兼容 images/generations 端点。直接写文件（url 或 b64_json）。"""
    api_key = os.environ.get("ETHAN_IMAGE_GEN_API_KEY")
    if not api_key:
        return False
    base = os.environ.get("ETHAN_IMAGE_GEN_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("ETHAN_IMAGE_GEN_MODEL", "dall-e-3")
    payload = json.dumps({
        "model": model,
        "prompt": f"Professional presentation illustration: {query}. Clean, high quality, no text watermark.",
        "n": 1,
        "size": "1792x1024" if "dall-e-3" in model else "1024x1024",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/images/generations", data=payload,
        headers={"User-Agent": UA, "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        item = (data.get("data") or [{}])[0]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if item.get("b64_json"):
            import base64

            dest.write_bytes(base64.b64decode(item["b64_json"]))
            return True
        if item.get("url"):
            return http_download(item["url"], dest)
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] AI 生图失败: {e}", file=sys.stderr)
    return False


def write_placeholder_png(dest: Path, color: str = "#E5E7EB", w: int = 1280, h: int = 720):
    """纯 stdlib 写纯色 PNG（最终降级，保证流程不断）。"""
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(x * 2 for x in c)
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    row = b"\x00" + bytes([r, g, b]) * w  # filter 0 + RGB 扫描行
    raw = row * h

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(png)


# ---------------------------------------------------------------------------
# Iconify（SVG）→ PNG 光栅化
# ---------------------------------------------------------------------------

def iconify_url(collection: str, name: str, color: str | None = None) -> str:
    params = {}
    if color:
        params["color"] = color
    qs = f"?{urllib.parse.urlencode(params)}" if params else ""
    return f"https://api.iconify.design/{collection}/{name}.svg{qs}"


def _http_get_bytes(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read()
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 下载失败 {url[:80]}: {e}", file=sys.stderr)
        return None


def _pip_install(*pkgs: str) -> bool:
    print(f"  [info] 安装依赖 {' '.join(pkgs)} ...", file=sys.stderr)
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", *([] if in_venv else ["--user"]), *pkgs]
    try:
        subprocess.check_call(cmd)
        import site

        user_site = site.getusersitepackages()
        if user_site not in sys.path:
            sys.path.insert(0, user_site)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 自动安装失败: {e}", file=sys.stderr)
        return False


def _svg_to_png(svg_bytes: bytes, dest: Path, size: int = 512) -> bool:
    """SVG → PNG。优先 cairosvg，其次 PyMuPDF（全平台预编译 wheel，自动安装）。"""
    try:
        import cairosvg

        dest.parent.mkdir(parents=True, exist_ok=True)
        cairosvg.svg2png(bytestring=svg_bytes, write_to=str(dest), output_width=size, output_height=size)
        return True
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] cairosvg 转换失败: {e}", file=sys.stderr)
        return False
    for attempt in range(2):
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=svg_bytes, filetype="svg")
            page = doc[0]
            if page.rect.width <= 0:
                return False
            zoom = size / page.rect.width
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=True)
            dest.parent.mkdir(parents=True, exist_ok=True)
            pix.save(str(dest))
            return True
        except ImportError:
            if attempt == 0 and _pip_install("pymupdf"):
                continue
            return False
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] pymupdf 转换失败: {e}", file=sys.stderr)
            return False
    return False


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def iter_image_specs(deck: dict):
    """yield (owner_dict, src_key) for every image src in the deck."""
    for slide in deck.get("slides") or []:
        bg = slide.get("background") or {}
        if bg.get("type") == "image" and (bg.get("image") or {}).get("src") is not None:
            yield bg["image"], "src"
        for el in slide.get("elements") or []:
            if el.get("type") == "image":
                yield el, "src"


def slugify(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9一-鿿]+", "-", text).strip("-").lower()
    return (s[:maxlen] or "img")


def resolve_one(src: str, el: dict, assets_dir: Path, deck_dir: Path, placeholder_color: str, dry_run: bool):
    """返回 (新src, 来源) ；无需处理时返回 (原src, None)。"""
    icon_color = el.get("iconColor")

    if src.startswith("icon:"):
        parts = src.split(":", 2)
        if len(parts) != 3 or not parts[1] or not parts[2]:
            print(f"  [error] icon 格式应为 icon:collection:name，收到: {src}", file=sys.stderr)
            return src, None
        _, collection, name = parts
        fname = f"icon-{collection}-{name}.png"
        dest = assets_dir / fname
        if dry_run:
            return f"{assets_dir.name}/{fname}", "iconify(dry)"
        svg_bytes = _http_get_bytes(iconify_url(collection, name, icon_color))
        if svg_bytes and _svg_to_png(svg_bytes, dest):
            return f"{assets_dir.name}/{fname}", "iconify"
        print(f"  [warn] Iconify 拉取/转换失败，降级为占位图: {src}", file=sys.stderr)
        write_placeholder_png(dest, placeholder_color)
        return f"{assets_dir.name}/{fname}", "placeholder"

    query = None
    if src.startswith("gen:"):
        query = src[4:].strip()
    elif not src and el.get("imageQuery"):
        query = str(el["imageQuery"]).strip()
    if not query:
        return src, None

    stem = slugify(query) + "-" + hashlib.md5(query.encode()).hexdigest()[:6]
    if dry_run:
        return f"{assets_dir.name}/{stem}.jpg", "gen(dry)"

    # 瀑布流：Pexels → Unsplash → AI → 占位
    url = try_pexels(query)
    if url:
        dest = assets_dir / f"{stem}.jpg"
        if http_download(url, dest):
            return f"{assets_dir.name}/{dest.name}", "pexels"
    url = try_unsplash(query)
    if url:
        dest = assets_dir / f"{stem}.jpg"
        if http_download(url, dest):
            return f"{assets_dir.name}/{dest.name}", "unsplash"
    dest = assets_dir / f"{stem}.png"
    if try_ai_image(query, dest):
        return f"{assets_dir.name}/{dest.name}", "ai"
    write_placeholder_png(dest, placeholder_color)
    return f"{assets_dir.name}/{dest.name}", "placeholder"


def main():
    ap = argparse.ArgumentParser(description="deck JSON 图片占位符瀑布流解析")
    ap.add_argument("deck", help="deck JSON 路径，或项目目录（含 deck.json + pages/*.json）；原地更新")
    ap.add_argument("--assets-dir", help="图片资源目录（默认 单文件: <deck名>.assets/，项目目录: assets/）")
    ap.add_argument("--dry-run", action="store_true", help="只列出待解析项，不下载")
    ap.add_argument("--placeholder-color", default="#E5E7EB", help="占位图颜色（默认 #E5E7EB）")
    args = ap.parse_args()

    deck_path = Path(args.deck).resolve()
    deck, deck_dir, page_files = load_deck(deck_path)
    assets_dir = Path(args.assets_dir).resolve() if args.assets_dir else default_assets_dir(deck_path)

    stats = {}
    pending = 0
    for el, key in iter_image_specs(deck):
        src = el.get(key) or ""
        if not (src.startswith("gen:") or src.startswith("icon:") or (not src and el.get("imageQuery"))):
            continue
        pending += 1
        label = src or f"gen:{el.get('imageQuery')}"
        new_src, source = resolve_one(src, el, assets_dir, deck_dir, args.placeholder_color, args.dry_run)
        if source:
            stats[source.split("(")[0]] = stats.get(source.split("(")[0], 0) + 1
            if not args.dry_run:
                el[key] = new_src
                el.pop("imageQuery", None)
            print(f"  [{source}] {label} -> {new_src}")

    if pending == 0:
        print("[ok] 没有待解析的图片占位符")
        return
    if args.dry_run:
        print(f"[dry-run] 共 {pending} 个占位符待解析")
        return
    write_back(deck_path, deck, page_files)
    print(f"[ok] 解析完成 {pending} 个占位符 {stats}，已更新: {deck_path}")


if __name__ == "__main__":
    main()
