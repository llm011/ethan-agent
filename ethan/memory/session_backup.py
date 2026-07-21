"""sessions.db 自动备份 — 对话结束后 10s 防抖触发，仅保留最新一份备份。"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_timer: threading.Timer | None = None
_DEBOUNCE_S = 10.0


def schedule_backup() -> None:
    """对话结束时调用。10s 内多次调用只触发一次实际备份。"""
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(_DEBOUNCE_S, _do_backup)
        _timer.daemon = True
        _timer.start()


def _list_backups(backup_dir: Path) -> list[Path]:
    """列出真正的备份文件，排除 -shm / -wal 附属文件。

    glob("sessions.db.bak-*") 会误匹配到 sqlite 的 -shm/-wal 附属文件，
    若不过滤会让 latest_backup 取到 0 字节的 -wal，大小判断永远失真。
    """
    return sorted(
        p for p in backup_dir.glob("sessions.db.bak-*")
        if not p.name.endswith(("-shm", "-wal"))
    )


def _quick_check(db_path: Path) -> bool:
    """PRAGMA quick_check 探活：返回 True 表示 db 结构完整。

    quick_check 比 integrity_check 快很多（不校验 B-tree 全量引用），
    适合每次备份前跑一次。注意它不是 100% 覆盖，但能拦住索引错乱、
    页头损坏这类最常见的 corruption——正是双写/异常退出会触发的类型。
    """
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            return bool(row and row[0] == "ok")
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False


# 保留多少份历史备份。曾经是 1 份，但一旦当前 db 损坏，下一次 backup 会
# 用坏库覆盖唯一的好备份——把救命稻草也毁了。改成 2 份留出回滚余地。
_KEEP_BACKUPS = 2


def _do_backup() -> None:
    """实际执行备份。

    安全策略：
    1. 备份前对源 db 做 quick_check，损坏则跳过本次备份（保留旧的好备份）
    2. 用 sqlite3 .backup() 原子拷贝（避开 WAL 中途状态）
    3. 备份后再对目标 db 做 quick_check，校验备份真的可用
    4. 任一校验失败立刻删掉这次产出的新备份，不动旧备份
    5. 保留最近 _KEEP_BACKUPS 份，多的从最旧开始删
    """
    global _timer
    with _lock:
        _timer = None

    try:
        from ethan.core.paths import user_sessions_db_path
        db_path = user_sessions_db_path()
        if not db_path.exists():
            return
        db_size = db_path.stat().st_size
        if db_size == 0:
            return

        # ① 源 db 完整性检查——损坏就绝对不能备份，否则会覆盖好备份
        if not _quick_check(db_path):
            logger.warning(
                "[SessionBackup] source sessions.db failed quick_check; "
                "skip this backup to preserve existing good backup"
            )
            return

        backup_dir = db_path.parent
        # 找到已有备份（格式：sessions.db.bak-YYYYMMDD_HHMM）
        existing_backups = _list_backups(backup_dir)

        # 判断是否需要备份：比已有备份大才备份
        if existing_backups:
            latest_backup = existing_backups[-1]
            backup_size = latest_backup.stat().st_size
            if db_size <= backup_size:
                return  # 没变大，跳过

        # 生成新备份文件名
        now = datetime.now()
        suffix = now.strftime("%Y%m%d_%H%M")
        new_backup = backup_dir / f"sessions.db.bak-{suffix}"

        # ② 用 sqlite3 的 .backup 确保一致性（避免拷贝到 WAL 写入中途的状态）
        import sqlite3
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(new_backup))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        # ③ 备份后校验——若新备份不可用，立刻删除，不动旧备份
        if not _quick_check(new_backup):
            logger.error(
                "[SessionBackup] new backup %s failed quick_check; "
                "removing it, keeping old backups",
                new_backup.name,
            )
            try:
                new_backup.unlink(missing_ok=True)
                for ext in ("-shm", "-wal"):
                    Path(str(new_backup) + ext).unlink(missing_ok=True)
            except OSError:
                pass
            return

        logger.info(
            "[SessionBackup] created %s (%d bytes, quick_check=ok)",
            new_backup.name, db_size,
        )

        # ④ 只保留最近 _KEEP_BACKUPS 份，从最旧开始删
        all_backups = _list_backups(backup_dir)
        surplus = all_backups[:-_KEEP_BACKUPS] if len(all_backups) > _KEEP_BACKUPS else []
        for old in surplus:
            if old == new_backup:
                continue
            try:
                old.unlink()
                # 清理可能残留的 -shm / -wal
                for ext in ("-shm", "-wal"):
                    sib = Path(str(old) + ext)
                    sib.unlink(missing_ok=True)
            except OSError:
                pass

    except Exception:
        logger.exception("[SessionBackup] backup failed")
