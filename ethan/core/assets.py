"""资产文件管理 — 图片/附件的本地持久化。

图片存储在 ~/.ethan/assets/images/{session_id}/{timestamp}_{idx}.{ext}
DB 只存相对路径（如 "s_20260723_abc1/1690000000_0.png"），不存 base64。
前端通过 /api/assets/images/{path} 访问。
"""
from __future__ import annotations

import base64
import os
import time
from pathlib import Path

from ethan.core.config import CONFIG_DIR

# 资产根目录
ASSETS_DIR = CONFIG_DIR / "assets"
IMAGES_DIR = ASSETS_DIR / "images"

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


def save_image(session_id: str, idx: int, data_b64: str, media_type: str) -> tuple[str, str]:
    """将 base64 图片数据保存到本地文件，返回 (相对路径, media_type)。

    落盘时自动缩放超过 API 限制（8000px）的图片，避免每轮 LLM 请求重复 decode+resize。
    缩放时保留原始格式：PNG→PNG（无损，保护截图文字），JPEG→JPEG q85（照片体积小）。

    返回的 media_type 可能与传入不同（如 PNG 缩放后仍为 PNG，但格式统一）。
    """
    raw = base64.b64decode(data_b64)

    # 落盘前检查尺寸，超限则缩放（保留原始格式）
    downscaled, did_resize, out_media_type = _downscale_bytes(raw, media_type)
    if did_resize:
        raw = downscaled
        media_type = out_media_type
    ext = _MIME_TO_EXT.get(media_type, ".png")

    ts = int(time.time() * 1000)  # 毫秒级时间戳
    rand = os.urandom(3).hex()    # 6 字符随机后缀防碰撞
    filename = f"{ts}_{idx}_{rand}{ext}"

    session_dir = IMAGES_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    file_path = session_dir / filename
    file_path.write_bytes(raw)

    # 返回相对路径和实际 media_type
    return f"{session_id}/{filename}", media_type


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
