"""docs 路由：文档读取 + 图片服务。"""
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/docs")

# When installed via pip, docs live at ethan/docs/ (copied in by CI)
# When running from source, this resolves to the repo-root docs/ folder
_PACKAGE_DOCS = Path(__file__).parent.parent.parent / "docs"    # ethan/docs/ — pip install
_REPO_DOCS = Path(__file__).parent.parent.parent.parent / "docs"  # repo root — dev mode
_DOCS_DIR = _PACKAGE_DOCS if _PACKAGE_DOCS.exists() else _REPO_DOCS


@router.get("")
async def list_docs():
    if not _DOCS_DIR.exists():
        return {"docs": []}
    docs = []
    for f in sorted(_DOCS_DIR.glob("*.md")):
        content = f.read_text(encoding="utf-8")
        first_heading = next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), f.stem)
        docs.append({"slug": f.stem, "title": first_heading, "filename": f.name})
    return {"docs": docs}


@router.get("/images/{filename}")
async def get_doc_image(filename: str):
    if not re.match(r'^[a-zA-Z0-9_.-]+$', filename):
        raise HTTPException(400, "Invalid filename")
    img_path = _DOCS_DIR / "images" / filename
    if not img_path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(str(img_path))


@router.get("/{slug}")
async def get_doc(slug: str):
    if not re.match(r'^[a-zA-Z0-9_-]+$', slug):
        raise HTTPException(400, "Invalid slug")
    doc_path = _DOCS_DIR / f"{slug}.md"
    if not doc_path.exists():
        raise HTTPException(404, "Doc not found")
    return {"slug": slug, "content": doc_path.read_text(encoding="utf-8")}
