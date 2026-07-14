"""annotations 路由 —— 消息文本标注的存储与读写。

标注（高亮/下划线/批注）按 message_id + user_id 持久化到 SQLite。
偏移 start/end 基于「消息渲染后的纯文本」字符位置（消息不可变 → 稳定）；
前端在气泡与阅读模式间用同一套 highlight pass 回显。
"""
from __future__ import annotations

import asyncio
import time

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ethan.core.config import CONFIG_DIR

from .deps import verify_token

_DB_PATH = CONFIG_DIR / "annotations.db"

router = APIRouter()

ANNOTATION_TYPES = {"highlight", "underline", "strike", "comment"}
# 颜色分类（语义）：黄=重点 蓝=疑问 绿=待办 粉=不同意；None 走默认色
ANNOTATION_COLORS = {"yellow", "blue", "green", "pink", None}


class AnnotationStore:
    """标注存储（aiosqlite，仿 ethan.memory.api_keys.APIKeyStore 风格）。"""

    def __init__(self):
        self._db: aiosqlite.Connection | None = None
        self._lock: asyncio.Lock | None = None

    async def init(self) -> None:
        if self._db is not None:
            return
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._db is not None:
                return
            _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._db = await aiosqlite.connect(str(_DB_PATH))
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS annotations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL,
                    user_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    color TEXT,
                    start INTEGER NOT NULL,
                    end INTEGER NOT NULL,
                    quote TEXT,
                    note TEXT,
                    created_at REAL NOT NULL
                )
                """
            )
            await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def list_for_message(self, message_id: int, user_id: str) -> list[dict]:
        await self.init()
        async with self._db.execute(
            "SELECT id, type, color, start, end, quote, note, created_at "
            "FROM annotations WHERE message_id=? AND user_id=? ORDER BY start ASC",
            (message_id, user_id),
        ) as cur:
            rows = await cur.fetchall()
        return [
            {
                "id": r[0],
                "type": r[1],
                "color": r[2],
                "start": r[3],
                "end": r[4],
                "quote": r[5],
                "note": r[6],
                "created_at": r[7],
            }
            for r in rows
        ]

    async def list_for_messages(
        self, message_ids: list[int], user_id: str
    ) -> dict[str, list[dict]]:
        """一次取多个 message 的标注，按 message_id 分组返回（避免 N+1 查询）。"""
        if not message_ids:
            return {}
        await self.init()
        placeholders = ",".join("?" * len(message_ids))
        sql = (
            "SELECT id, message_id, type, color, start, end, quote, note, created_at "
            f"FROM annotations WHERE message_id IN ({placeholders}) AND user_id=? "
            "ORDER BY message_id, start ASC"
        )
        async with self._db.execute(sql, [*message_ids, user_id]) as cur:
            rows = await cur.fetchall()
        result: dict[str, list[dict]] = {str(mid): [] for mid in message_ids}
        for r in rows:
            result.setdefault(str(r[1]), []).append(
                {
                    "id": r[0],
                    "type": r[2],
                    "color": r[3],
                    "start": r[4],
                    "end": r[5],
                    "quote": r[6],
                    "note": r[7],
                    "created_at": r[8],
                }
            )
        return result

    async def create(
        self,
        message_id: int,
        user_id: str,
        type_: str,
        color: str | None,
        start: int,
        end: int,
        quote: str | None,
        note: str | None,
    ) -> int:
        await self.init()
        now = time.time()
        cur = await self._db.execute(
            "INSERT INTO annotations (message_id, user_id, type, color, start, end, quote, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (message_id, user_id, type_, color, start, end, quote, note, now),
        )
        await self._db.commit()
        return cur.lastrowid

    async def delete(self, anno_id: int, user_id: str) -> bool:
        await self.init()
        cur = await self._db.execute(
            "DELETE FROM annotations WHERE id=? AND user_id=?", (anno_id, user_id)
        )
        await self._db.commit()
        return cur.rowcount > 0


_store = AnnotationStore()


class AnnotationCreate(BaseModel):
    message_id: int
    type: str
    color: str | None = None
    start: int
    end: int
    quote: str | None = None
    note: str | None = None


@router.get("/annotations/batch")
async def batch_get_annotations(ids: str = "", user_id: str = Depends(verify_token)):
    """一次取多个 message 的标注，避免逐条请求（IN 查询，无 N+1）。

    ids 为逗号分隔的 message_id 列表；返回 { "<message_id>": [ {...}, ... ] }。
    必须声明在 /annotations/{message_id} 之前，否则会被路径参数路由截胡。
    """
    mids: list[int] = []
    for raw in ids.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            mids.append(int(raw))
        except ValueError:
            continue
    return await _store.list_for_messages(mids, user_id)


@router.get("/annotations/{message_id}")
async def get_annotations(message_id: int, user_id: str = Depends(verify_token)):
    items = await _store.list_for_message(message_id, user_id)
    return {"annotations": items}


@router.post("/annotations")
async def create_annotation(body: AnnotationCreate, user_id: str = Depends(verify_token)):
    if body.type not in ANNOTATION_TYPES:
        raise HTTPException(status_code=400, detail=f"invalid type: {body.type}")
    if body.start < 0 or body.end <= body.start:
        raise HTTPException(status_code=400, detail="invalid range: start < end required")
    color = body.color if body.color in ANNOTATION_COLORS else None
    anno_id = await _store.create(
        body.message_id, user_id, body.type, color, body.start, body.end, body.quote, body.note
    )
    return {"id": anno_id, "ok": True}


@router.delete("/annotations/{anno_id}")
async def delete_annotation(anno_id: int, user_id: str = Depends(verify_token)):
    ok = await _store.delete(anno_id, user_id)
    return {"ok": ok}
