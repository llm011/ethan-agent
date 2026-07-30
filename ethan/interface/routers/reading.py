"""reading 路由 —— 网页辅助阅读模式的标注存储。

与 annotations.py（按 message_id 存 SQLite，用于聊天消息）不同：
本路由服务浏览器扩展的「辅助阅读模式」，标注按 **页面 URL** 归档，
每个 URL 一个 JSON 文件，存到当前 profile 数据目录的 reading/ 子目录下。

偏移 start/end 基于「清洗后正文的渲染纯文本」字符位置——扩展进入阅读模式时
用同一套清洗逻辑还原正文 DOM，故同一套 offset 可精确回显标注。
"""
from __future__ import annotations

import hashlib
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ethan.core.paths import user_data_dir

from .deps import verify_token

router = APIRouter(prefix="/reading")

# 与 annotations.py 保持一致的语义约定：
# 类型：highlight 高亮 / underline 划线 / comment 评论
# 颜色：黄=重点 蓝=疑问 绿=待办 粉=不同意；None 走默认色
ANNOTATION_TYPES = {"highlight", "underline", "comment"}
ANNOTATION_COLORS = {"yellow", "blue", "green", "pink", None}


def _reading_dir():
    d = user_data_dir() / "reading"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path_for(url: str):
    """URL → 存储文件路径。用 sha1 哈希避免 URL 里的非法文件名字符。"""
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return _reading_dir() / f"{h}.json"


def _load(url: str) -> dict:
    p = _path_for(url)
    if not p.exists():
        return {"url": url, "annotations": [], "next_id": 1}
    try:
        data = json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"url": url, "annotations": [], "next_id": 1}
    data.setdefault("url", url)
    data.setdefault("annotations", [])
    data.setdefault("next_id", 1)
    return data


def _save(url: str, data: dict) -> None:
    _path_for(url).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), "utf-8"
    )


class ReadingAnnotationCreate(BaseModel):
    url: str
    type: str
    color: str | None = None
    start: int
    end: int
    quote: str | None = None
    note: str | None = None
    auto: bool = False  # True = AI 自动高亮的核心句（前端可视觉区分）


class ReadingAnnotationDelete(BaseModel):
    url: str
    id: int


@router.get("/annotations")
async def get_reading_annotations(url: str = "", user_id: str = Depends(verify_token)):
    """取某 URL 下的全部标注（进入阅读模式时重应用）。"""
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    data = _load(url)
    return {"url": url, "annotations": data["annotations"]}


@router.post("/annotations")
async def create_reading_annotation(
    body: ReadingAnnotationCreate, user_id: str = Depends(verify_token)
):
    if body.type not in ANNOTATION_TYPES:
        raise HTTPException(status_code=400, detail=f"invalid type: {body.type}")
    if body.start < 0 or body.end <= body.start:
        raise HTTPException(status_code=400, detail="invalid range: start < end required")
    color = body.color if body.color in ANNOTATION_COLORS else None

    data = _load(body.url)
    anno_id = data["next_id"]
    data["next_id"] = anno_id + 1
    data["annotations"].append(
        {
            "id": anno_id,
            "type": body.type,
            "color": color,
            "start": body.start,
            "end": body.end,
            "quote": body.quote,
            "note": body.note,
            "auto": body.auto,
            "created_at": time.time(),
        }
    )
    _save(body.url, data)
    return {"id": anno_id, "ok": True}


@router.delete("/annotations")
async def delete_reading_annotation(
    body: ReadingAnnotationDelete, user_id: str = Depends(verify_token)
):
    data = _load(body.url)
    before = len(data["annotations"])
    data["annotations"] = [a for a in data["annotations"] if a.get("id") != body.id]
    removed = len(data["annotations"]) < before
    if removed:
        _save(body.url, data)
    return {"ok": removed}
