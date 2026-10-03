"""会话归档 — 把 N 天前的旧会话备份成独立 SQLite 文件，并从主库移除。

产品入口：设置 → 数据管理（web/desktop 双端）。用户选「1 个月 / 3 个月 / 半年」，
先预览命中的会话数与时间范围，确认后执行归档。

归档文件放 ``archive/`` 目录，沿用 rotate 的日期跨度命名
``sessions.{start}~{end}.db``，后续「恢复」功能用
``ethan.memory.session.list_archived_dbs()`` 统一列出（含 rotate 产生的整库归档），
时间范围直接从文件名解析，无需额外元数据文件。

实现要点：
- 快照用 ``VACUUM INTO``（原子、不受并发连接影响），再从副本里删掉「留下」的
  会话，得到只含旧会话的归档库 —— 归档库 schema 与主库永远一致，恢复时
  无需关心列差异。
- 主库删除与快照各自按同一谓词求值：快照后重新活跃的会话（被继续聊、
  置顶）会留在主库不删 —— 宁可归档里多一份副本（恢复时去重），不可丢数据。
- 置顶会话（pinned_at > 0）视为用户显式「保留在手边」，永不归档。
- intermediate blob 的落盘文件（user_intermediate_dir）不移动不删除，
  归档后仍在原位，恢复后立即可访问。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 允许的归档档位（天）。不开放任意天数：设置页就这三档，同时挡住 days=0 误删全库。
ARCHIVE_DAY_CHOICES = (30, 90, 180)

# 归档谓词：updated_at 早于 cutoff 且未置顶。快照与主库删除共用。
_KEEP_NONE_SQL = "updated_at < ? AND pinned_at = 0"


def validate_days(days: int) -> None:
    if days not in ARCHIVE_DAY_CHOICES:
        raise ValueError(f"days 必须是 {ARCHIVE_DAY_CHOICES} 之一，收到 {days}")


def _fmt_date(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


async def preview_archive(store, days: int) -> dict[str, Any]:
    """预览：days 天前会有多少会话/消息被归档，时间范围如何。

    不做任何写操作，供前端确认弹窗展示。
    """
    validate_days(days)
    cutoff = time.time() - days * 86400
    db = store._db
    async with db.execute(
        f"SELECT COUNT(*), COALESCE(MIN(created_at), 0), COALESCE(MAX(updated_at), 0) "
        f"FROM sessions WHERE {_KEEP_NONE_SQL}",
        (cutoff,),
    ) as cursor:
        row = await cursor.fetchone()
    session_count, oldest_ts, newest_ts = row
    message_count = 0
    if session_count:
        async with db.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id IN "
            f"(SELECT id FROM sessions WHERE {_KEEP_NONE_SQL})",
            (cutoff,),
        ) as cursor:
            message_count = (await cursor.fetchone())[0]
    return {
        "days": days,
        "cutoff_ts": cutoff,
        "cutoff_date": _fmt_date(cutoff),
        "session_count": session_count,
        "message_count": message_count,
        "oldest_date": _fmt_date(oldest_ts) if session_count else None,
        "newest_date": _fmt_date(newest_ts) if session_count else None,
    }


async def archive_old_sessions(store, days: int) -> dict[str, Any]:
    """把 days 天前的未置顶会话快照进 archive/ 下的独立 db，再从主库删除。

    返回归档统计；没有命中任何会话时 ``archived_sessions`` 为 0、不产出文件。
    """
    validate_days(days)
    db = store._db
    cutoff = time.time() - days * 86400

    from ethan.core.paths import user_session_archive_dir

    archive_dir = user_session_archive_dir()

    # ── 1. 快照整个主库到临时文件（VACUUM INTO 不能在事务内跑） ──
    archive_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = archive_dir / f".archive-tmp-{int(time.time() * 1000)}.db"
    try:
        quoted = str(tmp_path).replace("'", "''")
        await db.execute(f"VACUUM INTO '{quoted}'")

        # ── 2. 副本里删掉「留下」的会话 → 只含旧会话的归档库 ──
        import aiosqlite

        arch = await aiosqlite.connect(str(tmp_path))
        try:
            await arch.execute("PRAGMA foreign_keys=ON")
            await arch.execute(
                "DELETE FROM messages WHERE session_id IN "
                "(SELECT id FROM sessions WHERE updated_at >= ? OR pinned_at > 0)",
                (cutoff,),
            )
            await arch.execute(
                "DELETE FROM message_intermediate_blobs WHERE session_id IN "
                "(SELECT id FROM sessions WHERE updated_at >= ? OR pinned_at > 0)",
                (cutoff,),
            )
            await arch.execute(
                "DELETE FROM sessions WHERE updated_at >= ? OR pinned_at > 0", (cutoff,)
            )
            await arch.commit()
            async with arch.execute(
                "SELECT COUNT(*) FROM sessions"
            ) as cursor:
                archived_sessions = (await cursor.fetchone())[0]
            async with arch.execute(
                "SELECT COUNT(*) FROM messages"
            ) as cursor:
                archived_messages = (await cursor.fetchone())[0]
            if archived_sessions:
                async with arch.execute(
                    "SELECT MIN(created_at), MAX(updated_at) FROM sessions"
                ) as cursor:
                    oldest_ts, newest_ts = await cursor.fetchone()
            else:
                oldest_ts = newest_ts = None
        finally:
            await arch.close()

        if not archived_sessions:
            # 没有命中：不产出空归档文件
            tmp_path.unlink(missing_ok=True)
            return {
                "archived_sessions": 0,
                "archived_messages": 0,
                "archive_file": None,
                "start_date": None,
                "end_date": None,
                "size_bytes": 0,
            }

        # ── 3. 主库按同一谓词删除（此刻重新活跃的会话自动留下，宁重勿丢） ──
        await db.execute(
            "DELETE FROM messages WHERE session_id IN "
            f"(SELECT id FROM sessions WHERE {_KEEP_NONE_SQL})",
            (cutoff,),
        )
        await db.execute(
            "DELETE FROM message_intermediate_blobs WHERE session_id IN "
            f"(SELECT id FROM sessions WHERE {_KEEP_NONE_SQL})",
            (cutoff,),
        )
        cursor = await db.execute(
            f"DELETE FROM sessions WHERE {_KEEP_NONE_SQL}", (cutoff,)
        )
        removed_sessions = cursor.rowcount
        await db.commit()

        # ── 4. 命名 + 落位：sessions.{start}~{end}.db，重名加序号 ──
        start_date = _fmt_date(oldest_ts)
        end_date = _fmt_date(newest_ts)
        final_path = archive_dir / f"sessions.{start_date}~{end_date}.db"
        counter = 1
        while final_path.exists():
            final_path = archive_dir / f"sessions.{start_date}~{end_date}.{counter}.db"
            counter += 1
        tmp_path.rename(final_path)

        # ── 5. 回收主库空间（best effort：并发下 VACUUM 可能失败，空页会被复用） ──
        try:
            await db.execute("VACUUM")
        except Exception:
            pass

        size_bytes = final_path.stat().st_size
        logger.info(
            "[SessionArchive] archived %d sessions / %d messages → %s (removed %d from main)",
            archived_sessions, archived_messages, final_path.name, max(removed_sessions, 0),
        )
        return {
            "archived_sessions": archived_sessions,
            "archived_messages": archived_messages,
            "removed_sessions": max(removed_sessions, 0),
            "archive_file": final_path.name,
            "start_date": start_date,
            "end_date": end_date,
            "size_bytes": size_bytes,
        }
    except Exception:
        # 任一步失败：清理临时快照，主库未删（或已删的部分在一个事务里一起回滚），数据不丢
        try:
            tmp_path.unlink(missing_ok=True)
            for ext in ("-wal", "-shm", "-journal"):
                Path(str(tmp_path) + ext).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def list_archives() -> list[dict[str, Any]]:
    """列出 archive/ 下所有归档库（含 rotate 的整库归档），供设置页展示与恢复功能选文件。

    时间范围从文件名解析（sessions.{start}~{end}[.n].db），按起始日期升序。
    """
    from ethan.memory.session import list_archived_dbs

    result = []
    for path, start_date, end_date in list_archived_dbs():
        try:
            stat = path.stat()
            size_bytes = stat.st_size
            mtime = stat.st_mtime
        except OSError:
            size_bytes, mtime = 0, 0.0
        result.append(
            {
                "file": path.name,
                "start_date": start_date,
                "end_date": end_date,
                "size_bytes": size_bytes,
                "created_at": mtime,
            }
        )
    return result
