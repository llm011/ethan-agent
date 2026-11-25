"""session assets responsibilities; public facade: memory.session."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from ethan.providers.base import Message

from .session_titles import _build_intermediate_markdown, _intermediate_preview, _slug_message_id

logger = logging.getLogger(__name__)


class SessionAssetsMixin:
    async def _migrate_inline_image_cards_once(self) -> None:
        """启动时的内联图片迁移，每个库只跑一次。

        历史 bug：这个迁移每次 init() 都全量重扫。查询条件只看「行体积大」，
        但体积大的常见原因是 tool_steps 里的长文本（命令输出、工具结果），
        并不含 base64 图片；这些行永远迁移不掉，于是每次启动都被重新取出、
        反序列化、逐卡检查——用户库里有 1967 行命中、86.8 MB，单次 init 卡 93 秒，
        而且 init 发生在每个新会话/重连，实测「点一个对话半天才出内容」。

        现在用库内标记表记住「已迁移过」，正常情况下只跑一次；
        需要重跑时删掉 meta 里对应的行即可。
        """
        await self._db.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta ("
            "  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL)"
        )
        await self._db.commit()
        # 判断要不要跑，用「库里还有没有待迁移数据」而不是单纯的时间点标记。
        #
        # 只用标记会漏掉一种真实情况：标记写入之后，旧数据才被写进来
        # （升级前创建的会话 / 从备份恢复 / 另一个旧版本进程并发写入）。
        # 这里先做一次极轻量的存在性探测（COUNT + LIMIT 1，走索引，微秒级），
        # 有活才进迁移函数；没有就立刻返回。
        #
        # 注意必须同时带 instr('data:')，否则「体积大但只是长文本」的行会让
        # 这个探测永远为真（历史上正是这样每次启动重扫 1967 行 / 86 MB / 93 秒）。
        async with self._db.execute(
            "SELECT 1 FROM messages "
            "WHERE (cards IS NOT NULL AND LENGTH(cards) > 2048 AND instr(cards, 'data:') > 0) "
            "   OR (tool_steps IS NOT NULL AND LENGTH(tool_steps) > 8192 AND instr(tool_steps, 'data:') > 0) "
            "LIMIT 1"
        ) as cursor:
            if await cursor.fetchone() is None:
                return  # 没有待迁移数据：绝大多数启动走这里

        await self._migrate_inline_image_cards()


    async def _migrate_inline_image_cards(self) -> None:
        """把 messages.cards / tool_steps 里内联的 base64 图片转成资产文件路径。

        幂等：处理过的卡片 url 变成 "assets/images/..."，不再匹配 data: 前缀，
        重启后二次扫描直接跳过。单次只扫带 cards/tool_steps 且体积可观的行，
        避免每次启动全表扫 5000 行。
        """
        import json as _json

        try:
            async with self._db.execute(
                # 必须同时满足「够大」和「真含 data:」：只看体积会把命令输出、
                # 长工具结果这类纯文本行也捞进来（实测 1967 行里只有 314 行真含图片），
                # 白读几十 MB、白白反序列化，还永远迁移不掉。
                "SELECT id, session_id, cards, tool_steps FROM messages "
                "WHERE (cards IS NOT NULL AND LENGTH(cards) > 2048 AND instr(cards, 'data:') > 0) "
                "   OR (tool_steps IS NOT NULL AND LENGTH(tool_steps) > 8192 AND instr(tool_steps, 'data:') > 0)"
            ) as cursor:
                rows = await cursor.fetchall()
        except Exception:
            return

        if not rows:
            return

        try:
            from ethan.core.assets import save_image
        except Exception:
            return

        # 已判定为「扫过、但没有可迁移结构」的行要记下来，否则它们会永远留在
        # 待迁移集合里被反复拉取。历史上库里有一批 tool_steps 内含 base64、
        # 但不在 step["cards"] 结构下的老数据（当前解析逻辑覆盖不到），
        # 每次启动都白读 86 MB、白做 JSON 反序列化。
        await self._db.execute(
            "CREATE TABLE IF NOT EXISTS inline_image_migration_skipped ("
            "  message_id INTEGER PRIMARY KEY, skipped_at REAL NOT NULL)"
        )
        async with self._db.execute(
            "SELECT message_id FROM inline_image_migration_skipped"
        ) as cursor:
            skipped_before = {row[0] for row in await cursor.fetchall()}
        rows = [r for r in rows if r[0] not in skipped_before]
        if not rows:
            await self._db.commit()
            return

        migrated_msgs = 0
        saved_bytes = 0

        async def _strip_data_uri(value: str) -> tuple[str, int]:
            """把 data:...;base64,<payload> 落盘成资产文件，返回 (新 url, 释放字节)。

            非 data URI 或落盘失败时原样返回，释放字节为 0。
            save_image 会做 base64 解码 + PIL 解码/缩放/长图切分，都是 CPU 密集的同步
            操作，必须丢到线程里执行——否则存量用户首次启动时会卡住事件循环。
            """
            if not value.startswith("data:"):
                return value, 0
            header, _, payload = value.partition(",")
            if not payload or "base64" not in header:
                return value, 0
            try:
                media_type = header[len("data:"):].split(";", 1)[0] or "image/png"
                segments = await asyncio.to_thread(save_image, sid, 0, payload, media_type)
                if not segments:
                    return value, 0
                rel_path, _ = segments[0]
                return f"assets/images/{rel_path}", len(value)
            except Exception:
                return value, 0

        async def _convert(cards: list) -> tuple[list, int]:
            """把卡片里内联的 base64 图片落盘；返回 (新列表, 释放字节数)。

            兼容两种形态：图片卡片的 url 字段，以及搜索卡片把 base64 塞进
            snippet 等文本字段的情况（历史脏数据）。
            """
            out = []
            freed = 0
            for card in cards:
                if not isinstance(card, dict):
                    out.append(card)
                    continue
                new_card = None
                for key, val in card.items():
                    if not (isinstance(val, str) and val.startswith("data:image")):
                        continue
                    new_val, f = await _strip_data_uri(val)
                    if not f:
                        continue
                    if new_card is None:
                        new_card = dict(card)
                    new_card[key] = new_val
                    freed += f
                if new_card is None:
                    out.append(card)
                    continue
                # 图片卡片的 url 落盘后补一个空 local_path，保持与实时产出结构一致
                if "local_path" in new_card and not new_card.get("local_path"):
                    new_card["local_path"] = ""
                out.append(new_card)
            return out, freed

        for msg_id, sid, cards_json, steps_json in rows:
            changed = False
            new_cards_s = cards_json
            new_steps_s = steps_json
            freed = 0

            if cards_json:
                try:
                    cards = _json.loads(cards_json)
                    if isinstance(cards, list):
                        converted, f = await _convert(cards)
                        if f:
                            new_cards_s = _json.dumps(converted, ensure_ascii=False)
                            freed += f
                            changed = True
                except Exception:
                    pass

            if steps_json:
                try:
                    steps = _json.loads(steps_json)
                    if isinstance(steps, list):
                        steps_changed = False
                        for step in steps:
                            if isinstance(step, dict) and isinstance(step.get("cards"), list):
                                converted, f = await _convert(step["cards"])
                                if f:
                                    step["cards"] = converted
                                    freed += f
                                    steps_changed = True
                        if steps_changed:
                            new_steps_s = _json.dumps(steps, ensure_ascii=False)
                            changed = True
                except Exception:
                    pass

            if not changed:
                # 结构上迁移不了（base64 藏在当前解析不支持的字段里）：
                # 记下来，下次启动直接跳过，别再为它读几十 MB。
                try:
                    await self._db.execute(
                        "INSERT OR IGNORE INTO inline_image_migration_skipped(message_id, skipped_at) "
                        "VALUES(?, ?)",
                        (msg_id, time.time()),
                    )
                except Exception:
                    pass
                continue
            try:
                await self._db.execute(
                    "UPDATE messages SET cards=?, tool_steps=? WHERE id=?",
                    (new_cards_s, new_steps_s, msg_id),
                )
                migrated_msgs += 1
                saved_bytes += freed
            except Exception:
                continue  # 单行失败不影响其它行

        if migrated_msgs:
            await self._db.commit()
            logger.info(
                "[SessionStore] Migrated inline image cards: %d messages, freed %.1f MB",
                migrated_msgs, saved_bytes / 1024 / 1024,
            )


    def _should_persist_intermediate(self, msg: Message) -> bool:
        return msg.role == "assistant" and bool(msg.tool_steps or (msg.thought and msg.thought.strip()))


    async def _ensure_intermediate_blob(self, session_id: str, message_id: int, msg: Message) -> int:
        if not self._should_persist_intermediate(msg):
            return 0
        from ethan.core.paths import user_intermediate_dir

        content = _build_intermediate_markdown(msg)
        if len(content.strip()) <= len("# 过程记录"):
            return 0
        base_dir = user_intermediate_dir() / session_id
        base_dir.mkdir(parents=True, exist_ok=True)
        file_path = base_dir / _slug_message_id(message_id)
        file_path.write_text(content, encoding="utf-8")
        preview = _intermediate_preview(content)
        size_bytes = file_path.stat().st_size
        async with self._db.execute("SELECT intermediate_blob_id FROM messages WHERE id=?", (message_id,)) as cursor:
            row = await cursor.fetchone()
        existing_blob_id = int(row[0] or 0) if row else 0
        if existing_blob_id:
            await self._db.execute(
                "UPDATE message_intermediate_blobs SET file_path=?, format='markdown', size_bytes=?, preview_text=?, updated_at=? WHERE id=?",
                (str(file_path), size_bytes, preview, time.time(), existing_blob_id),
            )
            await self._db.commit()
            return existing_blob_id
        cursor = await self._db.execute(
            "INSERT INTO message_intermediate_blobs (message_id, session_id, kind, file_path, format, size_bytes, preview_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message_id,
                session_id,
                "process",
                str(file_path),
                "markdown",
                size_bytes,
                preview,
                time.time(),
                time.time(),
            ),
        )
        blob_id = cursor.lastrowid
        await self._db.execute("UPDATE messages SET intermediate_blob_id=? WHERE id=?", (blob_id, message_id))
        await self._db.commit()
        return blob_id


    async def _delete_intermediate_blob_for_message(self, row_id: int) -> None:
        async with self._db.execute("SELECT intermediate_blob_id FROM messages WHERE id=?", (row_id,)) as cursor:
            row = await cursor.fetchone()
        blob_id = int(row[0] or 0) if row else 0
        if not blob_id:
            return
        async with self._db.execute(
            "SELECT file_path FROM message_intermediate_blobs WHERE id=?", (blob_id,)
        ) as cursor:
            row = await cursor.fetchone()
        file_path = Path(row[0]) if row and row[0] else None
        await self._db.execute("DELETE FROM message_intermediate_blobs WHERE id=?", (blob_id,))
        await self._db.commit()
        if file_path:
            file_path.unlink(missing_ok=True)
            try:
                if file_path.parent.exists() and not any(file_path.parent.iterdir()):
                    file_path.parent.rmdir()
            except OSError:
                pass


    async def load_intermediate_blob(self, row_id: int) -> dict | None:
        async with self._db.execute(
            "SELECT b.id, b.file_path, b.format, b.size_bytes, b.preview_text, b.kind FROM messages m JOIN message_intermediate_blobs b ON m.intermediate_blob_id = b.id WHERE m.id=? AND m.intermediate_blob_id IS NOT NULL AND m.intermediate_blob_id != 0",
            (row_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        path = Path(row[1])
        if not path.exists():
            return {
                "id": row[0],
                "missing": True,
                "format": row[2],
                "size_bytes": row[3],
                "preview_text": row[4],
                "kind": row[5],
            }
        return {
            "id": row[0],
            "format": row[2],
            "size_bytes": row[3],
            "preview_text": row[4],
            "kind": row[5],
            "content": path.read_text(encoding="utf-8"),
            "missing": False,
        }


    async def load_session_cards(self, session_id: str) -> list[dict] | None:
        """只取 messages 的 cards 列（files 路由构建交付授权集合用）。

        避免 load() 全量加载消息 + 反序列化 9 个无关 JSON 列。
        返回 None 表示 session 不存在；否则返回所有卡片 dict 的扁平列表。
        """
        import json

        async with self._db.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)) as cursor:
            if not await cursor.fetchone():
                return None

        cards: list[dict] = []
        async with self._db.execute(
            "SELECT cards FROM messages WHERE session_id = ? AND cards IS NOT NULL",
            (session_id,),
        ) as cursor:
            async for (cards_json,) in cursor:
                try:
                    for c in json.loads(cards_json):
                        if isinstance(c, dict):
                            cards.append(c)
                except Exception:
                    continue
        return cards
