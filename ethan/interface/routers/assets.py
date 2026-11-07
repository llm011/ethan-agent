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


@router.get("/uploads/{session_id}/{filename}", dependencies=[Depends(_verify_token_or_cookie)])
async def get_upload_file(session_id: str, filename: str):
    """下载/预览聊天附件（非图片上传，如 .md/.pdf）。

    目录由 URL 里的 session_id 段决定，**不接受文件名里带路径**：一个会话的附件
    不会被另一个会话的链接读到（会话归属由调用方自己保证 session_id 正确）。
    与图片路由不同，这里不做扩展名白名单——附件本来就可能是任意类型，安全边界
    是「只能读 uploads/<session_id>/ 这一个目录」。

    `filename` 是落盘名（`<uuid8>_<原始名>`），原始名由 `Content-Disposition` 还原。

    归属校验：URL 里的 session_id 必须是当前用户的会话（与图片路由同样只靠
    「本进程/profile 的会话库」隔离——多租户部署时每个用户有自己的 profile 目录，
    别人的 session 目录根本不在自己的 uploads 下）。`_pending/` 是尚未归属会话的
    暂存区（上传后、发送前点开 chip 也要能看），只接受本次上传返回的落盘名，
    不发目录列表。
    """
    from pathlib import Path

    from ethan.core.uploads import PENDING_DIRNAME, upload_file_path
    from ethan.memory.session import session_exists

    if "/" in session_id or "\\" in session_id or ".." in session_id:
        raise HTTPException(status_code=400, detail="invalid path")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="invalid path")
    # 未归属会话的暂存文件（uploads/_pending/）允许预览：上传后、发送前点 chip 也要能看。
    # 注意 _pending 是「本 profile 的暂存区」，不是某个会话的目录——仍然要求登录态
    # （上面的 _verify_token_or_cookie），且文件名带 uuid 前缀不可枚举。
    if session_id != PENDING_DIRNAME and not await session_exists(session_id):
        raise HTTPException(status_code=404, detail="not found")
    path = upload_file_path(f"{session_id}/{filename}")
    if path is None:
        raise HTTPException(status_code=404, detail="not found")
    # 落盘名形如 "1a2b3c4d_原始名.md"：去掉 uuid 前缀还原原始文件名
    original = Path(filename).name
    head, _, tail = original.partition("_")
    if len(head) == 8 and tail and all(c in "0123456789abcdef" for c in head):
        original = tail
    return FileResponse(
        path,
        filename=original,
        headers={"Cache-Control": "private, max-age=0"},
    )


@router.get("/images/{session_id}/{filename}", dependencies=[Depends(_verify_token_or_cookie)])
async def get_asset_image(session_id: str, filename: str, fmt: str | None = None, w: int | None = None):
    """读取用户上传的图片文件。

    fmt=rgb565：返回按宽 w（默认 240）缩放的 RGB565 小端裸像素，
    响应头 X-Img-Width / X-Img-Height 给出尺寸。供 ESP32 等
    无图片解码器的低内存设备直接渲染，避免传输和解码原图。
    """
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

    if fmt == "rgb565":
        if p.suffix.lower() == ".svg":
            raise HTTPException(status_code=400, detail="svg not supported for rgb565")
        import asyncio

        from ethan.core.assets import build_rgb565_thumbnail

        built = await asyncio.to_thread(build_rgb565_thumbnail, path, w or 240)
        if built is None:
            raise HTTPException(status_code=500, detail="thumbnail generation failed")
        cache, tw, th = built
        return FileResponse(
            cache,
            media_type="application/octet-stream",
            headers={
                "X-Img-Width": str(tw),
                "X-Img-Height": str(th),
                "Cache-Control": "public, max-age=86400",
            },
        )

    return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})
