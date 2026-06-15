"""API Key 存储与管理（用于 /v1/chat/completions 鉴权）。"""
import secrets
import time
import aiosqlite
from pathlib import Path

from ethan.core.config import CONFIG_DIR

_DB_PATH = CONFIG_DIR / "api_keys.db"


class APIKeyStore:
    _db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(_DB_PATH))
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                key TEXT UNIQUE NOT NULL,
                created_at REAL NOT NULL,
                last_used_at REAL
            )
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def create(self, name: str) -> dict:
        key = f"sk-ethan-{secrets.token_hex(24)}"
        key_id = secrets.token_hex(8)
        now = time.time()
        await self._db.execute(
            "INSERT INTO api_keys (id, name, key, created_at) VALUES (?, ?, ?, ?)",
            (key_id, name, key, now),
        )
        await self._db.commit()
        return {"id": key_id, "name": name, "key": key, "created_at": now}

    async def list_keys(self) -> list[dict]:
        async with self._db.execute(
            "SELECT id, name, key, created_at, last_used_at FROM api_keys ORDER BY created_at DESC"
        ) as cur:
            rows = await cur.fetchall()
        return [
            {
                "id": r[0],
                "name": r[1],
                "key_preview": r[2][:12] + "...",  # 只返回前缀，不暴露完整 key
                "created_at": r[3],
                "last_used_at": r[4],
            }
            for r in rows
        ]

    async def verify(self, key: str) -> bool:
        """验证 key 是否有效，有效时更新 last_used_at。"""
        async with self._db.execute(
            "SELECT id FROM api_keys WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return False
        await self._db.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
            (time.time(), row[0]),
        )
        await self._db.commit()
        return True

    async def delete(self, key_id: str) -> bool:
        cur = await self._db.execute(
            "DELETE FROM api_keys WHERE id = ?", (key_id,)
        )
        await self._db.commit()
        return cur.rowcount > 0
