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


def _do_backup() -> None:
    """实际执行备份：当前 sessions.db 比已有备份大时，覆盖备份并删旧文件。"""
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

        backup_dir = db_path.parent
        # 找到已有备份（格式：sessions.db.bak-YYYYMMDD_HHMM）
        existing_backups = sorted(backup_dir.glob("sessions.db.bak-*"))

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

        # 用 sqlite3 的 .backup 确保一致性（避免拷贝到 WAL 写入中途的状态）
        import sqlite3
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(new_backup))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        logger.info("[SessionBackup] created %s (%d bytes)", new_backup.name, db_size)

        # 删除旧备份（只保留最新一个）
        for old in existing_backups:
            if old != new_backup:
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
