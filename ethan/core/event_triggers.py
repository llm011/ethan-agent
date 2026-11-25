"""Bounded, authenticated event ingestion; no application auth-token reuse."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


class EventError(ValueError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class EventSettings:
    enabled: bool = False
    github_secret: str = ""
    alert_secret: str = ""
    user_id: str = ""
    repositories: frozenset[str] = frozenset()
    max_body: int = 65536
    max_concurrent: int = 2
    per_minute: int = 10
    db_path: Path = Path("events.db")

    @classmethod
    def from_env(cls) -> EventSettings:
        from ethan.core.config import CONFIG_DIR

        return cls(
            enabled=os.getenv("ETHAN_EVENTS_ENABLED") == "1",
            github_secret=os.getenv("ETHAN_EVENTS_GITHUB_SECRET", ""),
            alert_secret=os.getenv("ETHAN_EVENTS_ALERT_SECRET", ""),
            user_id=os.getenv("ETHAN_EVENTS_USER_ID", ""),
            repositories=frozenset(
                x.strip() for x in os.getenv("ETHAN_EVENTS_GITHUB_REPOSITORIES", "").split(",") if x.strip()
            ),
            db_path=Path(os.getenv("ETHAN_EVENTS_DB") or CONFIG_DIR / "db" / "events.db"),
        )


_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def authenticate(settings: EventSettings, source: str, body: bytes, headers) -> str:
    if not settings.enabled:
        raise EventError(404, "Event ingress disabled")
    if source not in {"github", "alert"}:
        raise EventError(400, "Unsupported event source")
    secret = settings.github_secret if source == "github" else settings.alert_secret
    if len(secret.encode()) < 32:
        raise EventError(503, "Dedicated event secret must contain at least 32 bytes")
    delivery = headers.get("x-github-delivery" if source == "github" else "x-event-delivery", "")
    if not _ID.fullmatch(delivery):
        raise EventError(400, "Invalid delivery id")
    if len(body) > settings.max_body:
        raise EventError(413, "Event body too large")
    if source == "github":
        signed = body
        signature = headers.get("x-hub-signature-256", "")
    else:
        timestamp = headers.get("x-event-timestamp", "")
        try:
            if abs(time.time() - int(timestamp)) > 300:
                raise ValueError
        except ValueError:
            raise EventError(401, "Invalid or expired event timestamp") from None
        # Alert signature binds delivery id and timestamp as well as raw bytes.
        signed = delivery.encode() + b"." + timestamp.encode() + b"." + body
        signature = headers.get("x-event-signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not re.fullmatch(r"sha256=[0-9a-f]{64}", signature) or not hmac.compare_digest(signature, expected):
        raise EventError(401, "Invalid event signature")
    return delivery


def normalize_event(settings: EventSettings, source: str, body: bytes, headers) -> dict:
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        raise EventError(400, "Invalid JSON") from None
    if not isinstance(data, dict):
        raise EventError(400, "Event must be an object")
    if source == "github":
        kind = headers.get("x-github-event", "")
        if kind not in {"push", "workflow_run"}:
            raise EventError(400, "Unsupported GitHub event")
        repository = data.get("repository")
        repo = repository.get("full_name") if isinstance(repository, dict) else None
        if not isinstance(repo, str) or repo not in settings.repositories:
            raise EventError(403, "Repository not allowed")
        if kind == "push":
            ref, after = data.get("ref"), data.get("after")
            if not isinstance(ref, str) or not ref.startswith("refs/") or len(ref) > 256:
                raise EventError(400, "Invalid push ref")
            if not isinstance(after, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", after):
                raise EventError(400, "Invalid push commit")
            return {"type": "github.push", "repository": repo, "ref": ref, "after": after}
        run = data.get("workflow_run")
        if data.get("action") != "completed" or not isinstance(run, dict):
            raise EventError(400, "Only completed workflow_run is supported")
        if not isinstance(run.get("conclusion"), str) or run.get("conclusion") not in {
            "success", "failure", "neutral", "cancelled", "skipped", "timed_out", "action_required", "stale",
        } or type(run.get("id")) is not int or run["id"] <= 0:
            raise EventError(400, "Invalid workflow run")
        return {"type": "github.workflow_run", "repository": repo,
                "run_id": run["id"], "conclusion": run["conclusion"]}
    if data.get("type") != "alert" or not isinstance(data.get("status"), str) or data.get("status") not in {"firing", "resolved"}:
        raise EventError(400, "Unsupported alert event")
    # Explicit schema: do not transport arbitrary commands, URLs, identity or role fields.
    if set(data) - {"type", "status", "name", "severity", "summary"}:
        raise EventError(400, "Unknown alert fields")
    result = {"type": "alert", "status": data["status"]}
    for field, maximum in (("name", 128), ("severity", 32), ("summary", 2000)):
        value = data.get(field, "")
        if not isinstance(value, str) or len(value) > maximum:
            raise EventError(400, "Invalid alert field")
        result[field] = value
    if not result["name"]:
        raise EventError(400, "Alert name required")
    return result


class DeliveryLedger:
    """Separate SQLite ledger: atomic duplicate/rate/concurrency admission across workers.

    Reservations never expire automatically: crashes need explicit operator recovery,
    avoiding double execution after a lease expires during a long generation.
    """

    def __init__(self, settings: EventSettings):
        self.settings = settings

    def _connect(self):
        self.settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.settings.db_path, timeout=2)
        db.execute("CREATE TABLE IF NOT EXISTS deliveries (source TEXT, delivery TEXT, "
                   "created REAL, state TEXT, session_id TEXT DEFAULT '', PRIMARY KEY(source, delivery))")
        db.commit()
        return db

    def claim(self, source: str, delivery: str) -> dict | None:
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state, session_id FROM deliveries WHERE source=? AND delivery=?",
                             (source, delivery)).fetchone()
            if row:
                return {"status": "duplicate", "state": row[0], "session_id": row[1]}
            active = db.execute("SELECT count(*) FROM deliveries WHERE state='running'").fetchone()[0]
            recent = db.execute("SELECT count(*) FROM deliveries WHERE created>?", (time.time() - 60,)).fetchone()[0]
            if active >= self.settings.max_concurrent or recent >= self.settings.per_minute:
                raise EventError(429, "Event admission limit reached")
            db.execute("INSERT INTO deliveries(source, delivery, created, state) VALUES (?, ?, ?, 'running')",
                       (source, delivery, time.time()))
            db.commit()
            return None
        finally:
            db.close()

    def update(self, source: str, delivery: str, state: str, session_id: str = "") -> None:
        db = self._connect()
        try:
            db.execute("UPDATE deliveries SET state=?, session_id=? WHERE source=? AND delivery=?",
                       (state, session_id, source, delivery))
            db.commit()
        finally:
            db.close()
