"""Assets 路由 — serve 用户上传的图片等资产文件。

/api/assets/images/{session_id}/{filename} → ~/.ethan/assets/images/{session_id}/{filename}

鉴权：同 images.py，支持 Authorization header 和 cookie ethan_token。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ethan.core.assets import image_file_path

router = APIRouter(prefix="/assets")

# 允许的图片扩展名
_ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}


async def _verify_token_or_cookie(request: Request) -> str:
    """支持 Authorization header、cookie ethan_token、query ?token= 三种鉴权方式。

    <img> 标签无法带 Authorization header；跨端口开发时 cookie 也不跨域，
    因此额外支持 ?token= query 参数（仅用于图片等静态资源访问）。
    """
    from ethan.core.context import set_user_id
    from ethan.core.users import get_user_store

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth.removeprefix("Bearer ").strip()
    else:
        token = request.cookies.get("ethan_token", "") or request.query_params.get("token", "")

    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_store = get_user_store()
    user_id = user_store.resolve_web_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    set_user_id(user_id)
    request.state.user_id = user_id
    return user_id


@router.get("/images/{session_id}/{filename}", dependencies=[Depends(_verify_token_or_cookie)])
async def get_asset_image(session_id: str, filename: str):
    """读取用户上传的图片文件。"""
    # 防目录穿越
    if "/" in filename or "\\" in filename or ".." in session_id or ".." in filename:
        raise HTTPException(status_code=400, detail="invalid path")

    from pathlib import Path
    p = Path(filename)
    if p.suffix.lower() not in _ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail="invalid file type")

    path = image_file_path(f"{session_id}/{filename}")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})
