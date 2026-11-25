"""Schedule cost reporting: exact persisted-message attribution, no title inference."""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from contextlib import closing
from pathlib import Path

logger = logging.getLogger(__name__)
WINDOW_SECONDS = 7 * 86400

# Both the session identity and profile owner are checked even though each profile
# has its own DB. An attribution survives job session rotation and job renaming.
COST_SQL = """
WITH selected AS (
    SELECT a.job_id, m.usage, m.tool_steps
    FROM schedule_message_attribution a
    JOIN messages m ON m.id = a.message_id AND m.session_id = a.session_id
    JOIN sessions s ON s.id = m.session_id
    WHERE a.user_id = ? AND a.job_id IN (SELECT value FROM json_each(?))
      AND s.source = 'schedule' AND m.role = 'assistant'
      AND COALESCE(m.status, 'completed') NOT IN ('running', 'pending')
      AND m.created_at > ? AND m.created_at <= ?
), parsed AS (
    SELECT job_id,
      CASE WHEN json_valid(usage) THEN usage ELSE '{}' END AS u,
      CASE WHEN json_valid(tool_steps) THEN tool_steps ELSE '[]' END AS steps
    FROM selected
), measured AS (
    SELECT job_id,
      CASE WHEN json_type(u, '$.input') IN ('integer', 'real')
                 AND json_extract(u, '$.input') > 0
           THEN json_extract(u, '$.input') ELSE 0 END AS input,
      CASE WHEN json_type(u, '$.input') IN ('integer', 'real')
                 AND json_extract(u, '$.input') > 0
                 AND json_type(u, '$.cache') IN ('integer', 'real')
           THEN json_extract(u, '$.cache') ELSE 0 END AS cache,
      CASE WHEN json_type(steps) = 'array' THEN json_array_length(steps) ELSE 0 END AS step_count
    FROM parsed
)
SELECT job_id, count(*), sum(input), sum(cache), avg(step_count),
       sum(input > 0)
FROM measured GROUP BY job_id
"""


async def save_attributed_message(store, session_id, message, progress_id, job_id, user_id):
    """Commit the final assistant and exact attribution together, or neither.

    The store's dedicated transaction owns serialization and metadata. Errors
    propagate to the schedule failure handler instead of silently losing billing.
    """
    message_id = await store.save_schedule_message(
        session_id, message, progress_id, job_id, user_id,
    )
    return message_id


def _read_costs(db_path: Path, job_ids: list[str], user_id: str, now: float) -> dict:
    result = {
        job_id: dict(window_days=7, run_count=0, input_tokens=0, cache_tokens=0,
                     cache_hit_rate=None, average_steps=None, usage_run_count=0,
                     attribution='message', unattributed_runs=0)
        for job_id in job_ids
    }
    if not db_path.exists():
        return result
    # mode=ro must not create a missing DB; query_only also guards future changes.
    with closing(sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        db.execute('PRAGMA query_only = ON')
        has_mapping = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            ('schedule_message_attribution',),
        ).fetchone()
        cutoff = now - WINDOW_SECONDS
        gap_sql = """
            SELECT count(*) FROM messages m JOIN sessions s ON s.id=m.session_id
            WHERE s.source='schedule' AND m.role='assistant'
              AND COALESCE(m.status, 'completed') NOT IN ('running', 'pending')
              AND m.created_at > ? AND m.created_at <= ?
        """
        if has_mapping:
            gap_sql += " AND NOT EXISTS (SELECT 1 FROM schedule_message_attribution a WHERE a.message_id=m.id AND a.session_id=m.session_id)"
            gap_params = (cutoff, now)
        else:
            gap_params = (cutoff, now)
        gaps = db.execute(gap_sql, gap_params).fetchone()[0]
        for cost in result.values():
            # Profile-wide gap: cannot assign unknown rows to individual jobs.
            cost['unattributed_runs'] = gaps
        if has_mapping and job_ids:
            for job_id, runs, inputs, cached, steps, usage_runs in db.execute(
                COST_SQL, (user_id, json.dumps(job_ids), cutoff, now),
            ):
                result[job_id].update(
                    run_count=runs, input_tokens=inputs, cache_tokens=cached,
                    cache_hit_rate=round(100 * cached / inputs, 1) if inputs else None,
                    average_steps=round(steps, 1), usage_run_count=usage_runs,
                )
    return result


async def get_costs(job_ids: list[str], user_id: str) -> dict:
    """Read only the authenticated profile's active sessions DB, off the event loop."""
    from ethan.core.paths import user_data_dir

    path = user_data_dir() / 'db' / 'sessions.db'
    return await asyncio.to_thread(_read_costs, path, job_ids, user_id, time.time())
