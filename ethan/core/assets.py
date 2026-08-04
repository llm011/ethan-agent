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


def save_image(session_id: str, idx: int, data_b64: str, media_type: str) -> str:
    """将 base64 图片数据保存到本地文件，返回相对路径（不含 IMAGES_DIR 前缀）。

    文件路径: ~/.ethan/assets/images/{session_id}/{timestamp}_{idx}.{ext}
    返回值如: "s_20260723_abc1/1690000000_0.png"
    """
    ext = _MIME_TO_EXT.get(media_type, ".png")
    ts = int(time.time() * 1000)  # 毫秒级时间戳
    rand = os.urandom(3).hex()    # 6 字符随机后缀防碰撞
    filename = f"{ts}_{idx}_{rand}{ext}"

    session_dir = IMAGES_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    file_path = session_dir / filename
    file_path.write_bytes(base64.b64decode(data_b64))

    # 返回相对路径
    return f"{session_id}/{filename}"


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


def downscale_image_b64(data_b64: str, media_type: str, max_dim: int = _MAX_IMAGE_DIM) -> tuple[str, bool]:
    """如果图片任一边超过 max_dim，按比例缩小为 JPEG。

    返回 (新 base64, 是否缩放)。Pillow 不可用或解析失败时返回原图，
    交由 agent 层的 reactive fallback 兜底。
    """
    try:
        import io  # noqa: PLC0415

        from PIL import Image  # noqa: PLC0415

        raw = base64.b64decode(data_b64)
        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        if w <= max_dim and h <= max_dim:
            return data_b64, False

        ratio = min(max_dim / w, max_dim / h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        # RGB 化以兼容 JPEG（RGBA 图片直接存 JPEG 会报错）
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        new_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return new_b64, True
    except Exception:
        return data_b64, False
