#!/usr/bin/env python3
"""Aggregate-only deployment observer. No model, service imports, or DB writes.

Example (deployment time must include an offset):
  python scripts/observe_agent_loop_acceptance.py --since 2026-11-26T05:23:00+08:00
Default: one JSON report to stdout. Optional bounded --samples/--interval polling
never installs cron, enables events, or reads message content/user memory.
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

SOURCES = {
    "schedule", "heartbeat", "api", "web", "desktop", "dsh", "mcp", "lark",
    "browser-extension", "event", "cli",
}
WINDOW_SECONDS = 72 * 3600


def timestamp(value: str) -> float:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("time requires an explicit UTC offset")
    return parsed.timestamp()


def columns(db: sqlite3.Connection, table: str) -> set[str]:
    # Only internal, constant table names reach this function.
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def source_name(value: str) -> str:
    return value if value in SOURCES else "other"


def rate(cache: float, inputs: float) -> float | None:
    return round(100 * cache / inputs, 2) if inputs else None


def cost_sql_literal(path: Path) -> str:
    """Read the actual COST_SQL literal without importing any application code."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "COST_SQL"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and value.lstrip().upper().startswith("WITH "):
                return value
    raise ValueError("COST_SQL literal unavailable")


def observe(db_path: Path, since: float, now: float, min_runs: int = 3,
            cost_sql_path: Path | None = None) -> dict:
    if not all(math.isfinite(value) for value in (since, now)) or since > now:
        raise ValueError("deployment must be finite and not in the future")
    if min_runs < 1:
        raise ValueError("minimum runs must be positive")
    report = {
        "window": {
            "since": datetime.fromtimestamp(since, timezone.utc).isoformat(),
            "until": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "elapsed_hours": round((now - since) / 3600, 3),
            "complete_72h": now - since >= WINDOW_SECONDS,
        },
        "scope": "active DB only; persisted aggregate usage, not all provider billing",
        "sources": [], "jobs": [], "wire": [],
        "job_labels": "sample-local aliases; not stable identities across observations",
    }
    # Resolving does not create the DB. mode=ro refuses missing files; do not use
    # application path helpers (some migrate/create production assets).
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True,
                                 timeout=2)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")  # A consistent snapshot for every metric/parity query.
        mc = columns(db, "messages")
        if not {"id", "session_id", "role", "created_at", "usage", "tool_steps"} <= mc:
            raise ValueError("unsupported messages schema")
        has_mapping = bool(columns(db, "schedule_message_attribution"))
        status = "COALESCE(m.status,'completed')" if "status" in mc else "'completed'"
        # Missing and malformed JSON remain visible in coverage, never guessed.
        common = f"""
        WITH selected AS (
          SELECT m.id,m.session_id,s.source,{status} status,
            CASE WHEN json_valid(m.usage) THEN m.usage ELSE '{{}}' END u,
            CASE WHEN json_valid(m.tool_steps) THEN m.tool_steps ELSE '[]' END steps,
            m.usage IS NULL usage_missing,
            m.usage IS NOT NULL AND NOT json_valid(m.usage) usage_invalid
          FROM messages m JOIN sessions s ON s.id=m.session_id
          WHERE m.role='assistant' AND m.created_at>? AND m.created_at<=?
            AND {status} NOT IN ('running','pending')
        ), measured AS (
          SELECT *,CASE WHEN json_type(u,'$.input') IN ('integer','real')
            AND json_extract(u,'$.input')>0 THEN json_extract(u,'$.input') ELSE 0 END input,
            CASE WHEN json_type(u,'$.input') IN ('integer','real')
            AND json_extract(u,'$.input')>0
            AND json_type(u,'$.cache') IN ('integer','real')
            THEN json_extract(u,'$.cache') ELSE 0 END cache,
            CASE WHEN json_type(steps)='array' THEN json_array_length(steps) ELSE 0 END step_count,
            CASE WHEN json_type(steps)='array' THEN
              (SELECT count(*) FROM json_each(steps) t
               WHERE CASE WHEN json_valid(t.value) THEN json_extract(t.value,'$.state') END='error')
              ELSE 0 END errors
          FROM selected
        )
        """
        metrics = """count(*),sum(input>0),sum(input),sum(cache),sum(step_count),sum(errors),
          sum(usage_missing),sum(usage_invalid),sum(input>0 AND cache=0),
          sum(input>0 AND json_type(u,'$.cache') NOT IN ('integer','real')),
          sum(input>0 AND json_type(u,'$.cache') IS NULL),
          sum(cache<0 OR cache>input)"""
        raw_sources = db.execute(common + f"SELECT source,{metrics} FROM measured GROUP BY source",
                                 (since, now)).fetchall()
        merged: dict[str, list] = {}
        for name, *values in raw_sources:
            dest = merged.setdefault(source_name(name), [0] * len(values))
            for index, value in enumerate(values):
                dest[index] += value or 0
        for name, v in sorted(merged.items()):
            runs, usage_runs, inputs, cache, steps, errors, missing, invalid, zero, bad_cache, absent_cache, bad_values = v
            report["sources"].append({
                "source": name, "runs": runs, "usage_runs": usage_runs,
                "input": inputs, "cache": cache, "hit_pct": rate(cache, inputs),
                "steps": steps, "average_steps": round(steps / runs, 2),
                "tool_errors": errors, "tool_error_pct": rate(errors, steps),
                "usage_missing": missing, "usage_invalid": invalid,
                "zero_cache_runs": zero,
                "cache_field_missing_or_nonnumeric": bad_cache + absent_cache,
                "cache_out_of_range": bad_values,
            })
        total = sum(v[2] for v in merged.values())
        hb = merged.get("heartbeat", [0, 0, 0])[2]
        report["recorded_heartbeat_input_pct"] = rate(hb, total)
        report["attribution_available"] = has_mapping
        if has_mapping:
            # Internal owner/job IDs never leave the process. Group by owner too,
            # so duplicate job IDs across profiles cannot merge their costs.
            sql = common + f"""SELECT a.user_id,a.job_id,{metrics}
              FROM measured JOIN schedule_message_attribution a
              ON a.message_id=measured.id AND a.session_id=measured.session_id
              WHERE source='schedule' GROUP BY a.user_id,a.job_id ORDER BY a.user_id,a.job_id"""
            job_rows = db.execute(sql, (since, now)).fetchall()
            expected = {}
            for index, (owner, job, *v) in enumerate(job_rows, 1):
                runs, usage_runs, inputs, cache, steps, errors = v[:6]
                report["jobs"].append({
                    "job": f"J{index}", "runs": runs, "usage_runs": usage_runs,
                    "input": inputs, "cache": cache, "hit_pct": rate(cache, inputs),
                    "average_steps": round(steps / runs, 2), "steps": steps,
                    "tool_errors": errors, "usage_missing": v[6], "usage_invalid": v[7],
                })
                expected[(owner, job)] = (runs, inputs, cache, steps / runs, usage_runs)
            gaps = db.execute(common + """SELECT count(*) FROM measured WHERE source='schedule'
              AND NOT EXISTS(SELECT 1 FROM schedule_message_attribution a
              WHERE a.message_id=measured.id AND a.session_id=measured.session_id)""",
                              (since, now)).fetchone()[0]
            report["schedule_unattributed_runs"] = gaps
            if cost_sql_path is not None:
                actual_sql = cost_sql_literal(cost_sql_path)
                actual = {}
                for owner in {key[0] for key in expected}:
                    jobs = [key[1] for key in expected if key[0] == owner]
                    for job, *v in db.execute(actual_sql, (owner, json.dumps(jobs), since, now)):
                        actual[(owner, job)] = tuple(v)
                report["cost_sql_parity"] = {
                    "window": "same explicit observation window, not UI rolling seven days",
                    "jobs_tested": len(expected), "equal": actual == expected,
                }
        else:
            report["schedule_unattributed_runs"] = merged.get("schedule", [0])[0]
            report["cost_sql_parity"] = {"available": False, "reason": "old schema"}
        if columns(db, "message_wire_transcripts"):
            wire_sql = f"""SELECT json_extract(t.value,'$.role'),count(*),
              sum(length(COALESCE(json_extract(t.value,'$.reasoning'),''))),
              sum(length(COALESCE(json_extract(t.value,'$.reasoning'),''))>0),
              sum(json_type(t.value,'$.usage') IS NOT NULL),
              sum(json_type(t.value,'$.model') IS NOT NULL)
              FROM message_wire_transcripts w JOIN messages m
              ON m.id=w.message_id AND m.session_id=w.session_id
              JOIN json_each(CASE WHEN json_valid(w.state) THEN
                CASE WHEN json_type(w.state,'$.transcript')='array'
                THEN json_extract(w.state,'$.transcript') ELSE '[]' END ELSE '[]' END) t
              WHERE m.role='assistant' AND m.created_at>? AND m.created_at<=?
                AND {status} NOT IN ('running','pending') AND json_valid(t.value)
                AND json_type(t.value)='object' GROUP BY 1"""
            report["wire"] = [{
                "role": role if role in {"assistant", "tool", "user", "system"} else "other",
                "messages": count, "reasoning_chars": chars, "nonempty_reasoning": nonempty,
                "usage_fields": usage, "model_fields": model,
            } for role, count, chars, nonempty, usage, model in db.execute(wire_sql, (since, now))]
        schedule = next((v for v in report["sources"] if v["source"] == "schedule"), None)
        reasons = []
        if not report["window"]["complete_72h"]:
            reasons.append("deployment_window_under_72h")
        if schedule is None or schedule["usage_runs"] < min_runs:
            reasons.append("insufficient_schedule_usage_samples")
        if schedule is None or schedule["hit_pct"] is None or schedule["hit_pct"] < 80:
            reasons.append("schedule_cache_below_80pct_or_unmeasured")
        if schedule is None or schedule["tool_error_pct"] is None or schedule["tool_error_pct"] > 1:
            reasons.append("tool_errors_above_1pct_or_unmeasured")
        if schedule and (schedule["usage_runs"] != schedule["runs"]
                         or schedule["cache_field_missing_or_nonnumeric"]
                         or schedule["cache_out_of_range"]):
            reasons.append("incomplete_or_invalid_usage_coverage")
        if report["schedule_unattributed_runs"]:
            reasons.append("incomplete_schedule_attribution")
        report["gate"] = {
            "quantitative_schedule_checks_pass": not reasons, "reasons": reasons,
            "minimum_usage_runs": min_runs,
            "full_acceptance": False,
            "remaining": "identify approved scraping-job cohort; compare baseline steps and quality; "
                         "raw provider cache presence/route not persisted, cannot explain zero cache",
        }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path.home() / ".ethan/db/sessions.db")
    parser.add_argument("--since", type=timestamp, required=True)
    parser.add_argument("--until", type=timestamp, help="fixed sample end, must not be in the future")
    parser.add_argument("--min-runs", type=int, default=3, help="sampling floor, not a statistical guarantee")
    parser.add_argument("--samples", type=int, default=1, help="bounded observations, default one")
    parser.add_argument("--interval", type=float, default=3600, help="seconds between bounded samples")
    parser.add_argument("--cost-sql", type=Path,
                        default=Path(__file__).resolve().parents[1] / "ethan/scheduler/cost.py")
    args = parser.parse_args(argv)
    if args.samples < 1 or args.samples > 168 or not math.isfinite(args.interval) or args.interval < 1:
        parser.error("samples must be 1..168 and interval must be finite and >=1")
    if args.until is not None and (args.until > time.time() or args.samples != 1):
        parser.error("--until must not be in future and requires one sample")
    try:
        for index in range(args.samples):
            report = observe(args.db, args.since, args.until if args.until is not None else time.time(),
                             args.min_runs, args.cost_sql)
            print(json.dumps(report, ensure_ascii=False, allow_nan=False), flush=True)
            if index + 1 < args.samples:
                time.sleep(args.interval)  # No DB connection held while waiting.
    except KeyboardInterrupt:
        return 130
    except (sqlite3.Error, ValueError, OSError, SyntaxError):
        # SQLite/errors may embed private paths or IDs. Emit only a stable code.
        print(json.dumps({"error": "observation_failed", "db_modified": False}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
