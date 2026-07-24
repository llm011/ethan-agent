"""Images 路由 — serve image_search 工具下载到 /tmp/ethan_images/ 的图片。

下载模式下 image_search 把图片存到本地，但前端无法直接访问 file:// 路径，
通过此路由把本地路径转换成可访问的 HTTP URL：
  /api/images/{filename} → /tmp/ethan_images/{filename}

鉴权：支持 Authorization header（fetch 请求）和 cookie ethan_token（<img> 标签）两种方式。
原因：<img src="/api/images/xxx"> 标签无法带 Authorization header，
必须从 cookie 读 token；前端 setAuthToken 已经把 token 写到 cookie 里（path=/），
浏览器请求图片时会自动带上。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ethan.interface.routers.deps import verify_token_or_cookie as _verify_token_or_cookie
from ethan.tools.builtin.image_search import _IMAGE_DOWNLOAD_DIR

router = APIRouter(prefix="/images")

# 允许的图片扩展名（与 image_search.py 保持一致）
_ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}


@router.get("/{filename}", dependencies=[Depends(_verify_token_or_cookie)])
async def get_image(filename: str):
    """读取本地下载的图片文件。

    filename 必须形如 img_xxx.<ext>，不含路径分隔符，扩展名在白名单内。
    """
    # 防目录穿越：filename 只允许 img_xxx.<ext> 格式
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    p = Path(filename)
    if not p.name.startswith("img_") or p.suffix.lower() not in _ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail="invalid filename")
    path = _IMAGE_DOWNLOAD_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path)
