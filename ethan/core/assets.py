"""资产文件管理 — 图片/附件的本地持久化。

图片存储在 ~/.ethan/assets/images/{session_id}/{timestamp}_{idx}.{ext}
DB 只存相对路径（如 "s_20260723_abc1/1690000000_0.png"），不存 base64。
前端通过 /api/assets/images/{path} 访问。
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import time
from pathlib import Path

from ethan.core.config import CONFIG_DIR

logger = logging.getLogger(__name__)

# 资产根目录
ASSETS_DIR = CONFIG_DIR / "assets"
IMAGES_DIR = ASSETS_DIR / "images"

# 长图切分阈值（高度超过此值则垂直切分，与 image-split 技能默认值一致）
_SPLIT_HEIGHT_THRESHOLD = 8000
_SPLIT_SEGMENT = 6000
# 切分结果缓存目录（按 sha256(raw) 索引，避免重复计算）
_SPLIT_CACHE_DIR = ASSETS_DIR / "image_split_cache"

# MIME → 扩展名
_MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/bmp": ".bmp",
}


def save_image(session_id: str, idx: int, data_b64: str, media_type: str) -> list[tuple[str, str]]:
    """将 base64 图片数据保存到本地文件，返回 [(相对路径, media_type), ...]。

    长图（高度 > 8000px）会先垂直切分为多段，每段独立保存为一个文件。
    切分后每段再走 _downscale_bytes 兜底（处理宽度超限等 edge case）。
    未切分的图片返回单元素列表，兼容旧调用方。

    落盘时自动缩放超过 API 限制（8000px）的图片，避免每轮 LLM 请求重复 decode+resize。
    缩放时保留原始格式：PNG→PNG（无损，保护截图文字），JPEG→JPEG q85（照片体积小）。

    返回的 media_type 可能与传入不同（如 PNG 缩放后仍为 PNG，但格式统一）。
    """
    raw = base64.b64decode(data_b64)

    # 先尝试垂直切分长图（返回 1 段或多段）
    segments = _split_image_vertical(raw, media_type)

    results: list[tuple[str, str]] = []
    ts = int(time.time() * 1000)  # 毫秒级时间戳
    rand = os.urandom(3).hex()    # 6 字符随机后缀防碰撞
    session_dir = IMAGES_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    for seg_idx, (seg_raw, seg_media_type) in enumerate(segments):
        # 每段独立缩放（处理宽度超限；切分后高度已 ≤ segment，通常无需再缩）
        downscaled, did_resize, out_media_type = _downscale_bytes(seg_raw, seg_media_type)
        if did_resize:
            seg_raw = downscaled
            seg_media_type = out_media_type
        ext = _MIME_TO_EXT.get(seg_media_type, ".png")
        # 多段时加 _segN 后缀，单段保持原命名
        suffix = f"_seg{seg_idx}" if len(segments) > 1 else ""
        filename = f"{ts}_{idx}_{rand}{suffix}{ext}"

        file_path = session_dir / filename
        file_path.write_bytes(seg_raw)
        results.append((f"{session_id}/{filename}", seg_media_type))

    return results


def load_image_b64(relative_path: str) -> str | None:
    """从相对路径读取图片文件，返回 base64 字符串。找不到文件返回 None。"""
    file_path = IMAGES_DIR / relative_path
    if not file_path.is_file():
        return None
    return base64.b64encode(file_path.read_bytes()).decode("ascii")


def image_file_path(relative_path: str) -> Path:
    """根据相对路径返回绝对文件路径（供 FileResponse 用）。"""
    return IMAGES_DIR / relative_path


# 大多数 LLM provider 对图片单边尺寸限制 8000px（Anthropic/Kiro 等）
_MAX_IMAGE_DIM = 8000


def _downscale_bytes(raw: bytes, media_type: str = "image/png", max_dim: int = _MAX_IMAGE_DIM) -> tuple[bytes, bool, str]:
    """如果图片任一边超过 max_dim，按比例缩小，保留原始格式。

    PNG→PNG（无损，保护截图文字），JPEG→JPEG q85（照片体积小）。
    返回 (新字节, 是否缩放, 输出 media_type)。
    Pillow 不可用或解析失败时返回原图，交由 agent 层兜底。
    """
    try:
        import io  # noqa: PLC0415

        from PIL import Image  # noqa: PLC0415

        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        if w <= max_dim and h <= max_dim:
            return raw, False, media_type

        ratio = min(max_dim / w, max_dim / h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        buf = io.BytesIO()
        is_jpeg = media_type in ("image/jpeg", "image/jpg")
        if is_jpeg:
            # JPEG：RGB 化以兼容（RGBA 直接存 JPEG 会报错），q85 兼顾体积与质量
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=85)
            out_media_type = "image/jpeg"
        else:
            # PNG 无损（截图/文字首选）
            img.save(buf, format="PNG")
            out_media_type = "image/png"
        return buf.getvalue(), True, out_media_type
    except Exception:
        return raw, False, media_type


def downscale_image_b64(data_b64: str, media_type: str, max_dim: int = _MAX_IMAGE_DIM) -> tuple[str, bool]:
    """如果图片任一边超过 max_dim，按比例缩小，保留原始格式。

    返回 (新 base64, 是否缩放)。Pillow 不可用或解析失败时返回原图，
    交由 agent 层的 reactive fallback 兜底。
    """
    raw = base64.b64decode(data_b64)
    downscaled, did_resize, _ = _downscale_bytes(raw, media_type, max_dim)
    if not did_resize:
        return data_b64, False
    return base64.b64encode(downscaled).decode("ascii"), True


# ---------------------------------------------------------------------------
# 长图垂直切分
# ---------------------------------------------------------------------------


def _split_image_vertical(raw: bytes, media_type: str) -> list[tuple[bytes, str]]:
    """如果图片高度超过阈值，垂直切分为多段；否则返回原图单段。

    切分时在目标分割线 ±200px 内搜索空白行（像素标准差低），优先在空白处切割，
    避免切到文字。逻辑移植自 image-split 技能的 auto_split（仅垂直方向）。

    结果按 sha256(raw) 缓存到 _SPLIT_CACHE_DIR，同一张图不重复计算。
    Pillow/numpy 不可用或解析失败时返回原图，交由 _downscale_bytes 兜底。
    """
    try:
        from PIL import Image  # noqa: PLC0415

        Image.MAX_IMAGE_PIXELS = None  # 本工具就是处理大图的

        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        if h <= _SPLIT_HEIGHT_THRESHOLD:
            return [(raw, media_type)]

        key = hashlib.sha256(raw).hexdigest()[:16]
        cache_dir = _SPLIT_CACHE_DIR / key
        meta_file = cache_dir / "meta.json"

        # 命中缓存：直接读段文件
        if meta_file.is_file():
            meta = json.loads(meta_file.read_text())
            segments: list[tuple[bytes, str]] = []
            for seg_name in meta["segments"]:
                seg_bytes = (cache_dir / seg_name).read_bytes()
                segments.append((seg_bytes, meta["media_type"]))
            if segments:
                logger.debug("image split cache hit: %s → %d segments", key, len(segments))
                return segments

        # 未命中：执行切分
        segments = _do_vertical_split(img, media_type, w, h)
        if len(segments) <= 1:
            return [(raw, media_type)]

        # 写缓存
        cache_dir.mkdir(parents=True, exist_ok=True)
        seg_names: list[str] = []
        for i, (seg_bytes, seg_mt) in enumerate(segments):
            ext = _MIME_TO_EXT.get(seg_mt, ".png")
            seg_name = f"{i}{ext}"
            (cache_dir / seg_name).write_bytes(seg_bytes)
            seg_names.append(seg_name)
        meta_file.write_text(json.dumps({
            "media_type": segments[0][1],
            "segments": seg_names,
            "original_size": [w, h],
            "threshold": _SPLIT_HEIGHT_THRESHOLD,
            "segment_size": _SPLIT_SEGMENT,
        }, ensure_ascii=False))
        logger.info("image split: %dx%d → %d segments (cached at %s)", w, h, len(segments), key)
        return segments
    except Exception:
        logger.warning("image split failed, falling back to original", exc_info=True)
        return [(raw, media_type)]


def _do_vertical_split(img, media_type: str, w: int, h: int) -> list[tuple[bytes, str]]:
    """垂直切分图片，在空白间隙处切割。返回 [(段字节, media_type), ...]。"""
    import numpy as np  # noqa: PLC0415

    arr = np.array(img)
    if arr.ndim == 3:
        row_std = arr.std(axis=(1, 2))
    else:
        row_std = arr.std(axis=1)

    # 按 _SPLIT_SEGMENT 间距计算分割位置，最后一段 < 100px 则并入前段
    positions = [0]
    pos = _SPLIT_SEGMENT
    while pos < h:
        remaining = h - pos
        if remaining < 100:
            break
        best = _find_best_split_line(row_std, pos)
        if best <= positions[-1]:
            best = positions[-1] + 1
        positions.append(best)
        pos += _SPLIT_SEGMENT
    positions.append(h)

    is_jpeg = media_type in ("image/jpeg", "image/jpg")
    segments: list[tuple[bytes, str]] = []
    for i in range(len(positions) - 1):
        top, bottom = positions[i], positions[i + 1]
        crop = img.crop((0, top, w, bottom))
        buf = io.BytesIO()
        if is_jpeg:
            if crop.mode in ("RGBA", "P"):
                crop = crop.convert("RGB")
            crop.save(buf, format="JPEG", quality=90)
            seg_mt = "image/jpeg"
        else:
            crop.save(buf, format="PNG")
            seg_mt = "image/png"
        segments.append((buf.getvalue(), seg_mt))
    return segments


def _find_best_split_line(row_std, target_pos: int, search_range: int = 200, min_gap: int = 3) -> int:
    """在 target_pos 附近 ±search_range 内搜索最佳空白分割线。

    row_std: 每行像素标准差的 1D 数组
    返回最佳分割位置（原始坐标）。
    """
    start = max(0, target_pos - search_range)
    end = min(len(row_std), target_pos + search_range)
    blank = row_std[start:end] < 5  # std < 5 视为空白

    best_pos = target_pos
    best_dist = float("inf")
    relative_target = target_pos - start

    i = 0
    while i < len(blank):
        if blank[i]:
            j = i
            while j < len(blank) and blank[j]:
                j += 1
            if j - i >= min_gap:
                mid = (i + j) // 2
                dist = abs(mid - relative_target)
                if dist < best_dist:
                    best_dist = dist
                    best_pos = mid + start
            i = j
        else:
            i += 1
    return best_pos
