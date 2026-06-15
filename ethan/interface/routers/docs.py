"""docs 路由：文档读取 + 图片服务。"""
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from .deps import verify_token
from fastapi import Depends

router = APIRouter(prefix="/docs")

_REPO_ROOT = Path(__file__).parent.parent.parent.parent


@router.get("", dependencies=[Depends(verify_token)])
async def list_docs():
    docs_dir = _REPO_ROOT / "docs"
    if not docs_dir.exists():
        return {"docs": []}
    docs = []
    for f in sorted(docs_dir.glob("*.md")):
        content = f.read_text(encoding="utf-8")
        first_heading = next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), f.stem)
        docs.append({"slug": f.stem, "title": first_heading, "filename": f.name})
    return {"docs": docs}


@router.get("/images/{filename}")
async def get_doc_image(filename: str):
    """图片无需鉴权（Markdown img 标签直接请求）。"""
    if not re.match(r'^[a-zA-Z0-9_.-]+$', filename):
        raise HTTPException(400, "Invalid filename")
    img_path = _REPO_ROOT / "docs" / "images" / filename
    if not img_path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(str(img_path))


@router.get("/{slug}", dependencies=[Depends(verify_token)])
async def get_doc(slug: str):
    if not re.match(r'^[a-zA-Z0-9_-]+$', slug):
        raise HTTPException(400, "Invalid slug")
    doc_path = _REPO_ROOT / "docs" / f"{slug}.md"
    if not doc_path.exists():
        raise HTTPException(404, "Doc not found")
    return {"slug": slug, "content": doc_path.read_text(encoding="utf-8")}
