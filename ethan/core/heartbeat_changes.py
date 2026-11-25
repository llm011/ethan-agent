"""Cheap opt-in local heartbeat gate; never infer remote state from heartbeat.md alone."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalChangeGate:
    """Fingerprint only explicitly configured local files. Commit after successful execution.

    No manifest means legacy periodic behavior: remote polling/time-based tasks cannot
    safely be suppressed using only the task-definition file's modification time.
    """

    def __init__(self):
        self._previous: dict[str, str] = {}
        self._pending: dict[str, str] = {}

    def changed(self, workspace: Path, heartbeat_content: str) -> bool:
        key = str(workspace.resolve())
        manifest = workspace / "system" / "heartbeat-checks.json"
        try:
            if not manifest.exists():
                logger.debug("[Heartbeat] No local checks configured; legacy periodic fallback")
                return True
            with manifest.open("rb") as stream:
                raw = stream.read(16385)
            if len(raw) > 16384:
                raise ValueError("checks manifest exceeds 16 KiB")
            config = json.loads(raw)
            if not isinstance(config, dict) or set(config) != {"paths"}:
                raise ValueError("expected paths manifest")
            paths = config["paths"]
            if not isinstance(paths, list) or not 1 <= len(paths) <= 32:
                raise ValueError("expected 1..32 local file paths")
            digest = hashlib.sha256(raw + heartbeat_content.encode())
            for value in paths:
                if not isinstance(value, str) or not value or len(value) > 1024:
                    raise ValueError("invalid local path")
                path = Path(value)
                if not path.is_absolute():
                    path = workspace / path
                # stat-based change detection is cheap even for large files.
                stat = path.stat()
                if not path.is_file():
                    raise ValueError("checks only support regular files")
                digest.update(str(path.resolve()).encode())
                digest.update(str((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)).encode())
            fingerprint = digest.hexdigest()
            self._pending[key] = fingerprint
            if self._previous.get(key) == fingerprint:
                logger.info("[Heartbeat] Local checks unchanged; model wake skipped")
                return False
            return True  # first configured tick remains compatible
        except Exception:
            self._pending.pop(key, None)
            logger.warning("[Heartbeat] Local checks failed; legacy periodic fallback", exc_info=True)
            return True

    def commit(self, workspace: Path) -> None:
        key = str(workspace.resolve())
        if key in self._pending:
            self._previous[key] = self._pending.pop(key)
