"""资产文件管理 — 图片/附件的本地持久化。

图片存储在 ~/.ethan/assets/images/{session_id}/{timestamp}_{idx}.{ext}
DB 只存相对路径（如 "s_20260723_abc1/1690000000_0.png"），不存 base64。
前端通过 /api/assets/images/{path} 访问。
"""
from __future__ import annotations

import base64
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
    ts = int(time.time())
    filename = f"{ts}_{idx}{ext}"

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
