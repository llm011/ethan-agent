"""Browser HTTP 路由 —— Web 端读取截图文件。

挂在 /api 前缀下:GET /api/browser/shot/{name} 返回 browser-shots 下的图片。
飞书侧不走这里(直接用 send_lark_image 的本地路径)。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ethan.interface.routers.deps import verify_token

router = APIRouter()


@router.get("/browser/shot/{name}")
async def get_shot(name: str, user_id: str = Depends(verify_token)):
    # 防目录穿越:只允许 shot-*.<ext>,不含路径分隔符
    if "/" in name or "\\" in name or not name.startswith("shot-"):
        raise HTTPException(status_code=400, detail="invalid name")
    from ethan.browser.screenshot import shots_dir
    path = shots_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path)
