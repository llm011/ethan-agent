"""Temporary fixtures only: never start services or call a model."""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "acceptance_observer", ROOT / "scripts/observe_agent_loop_acceptance.py",
)
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "sessions.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
          CREATE TABLE sessions(id TEXT PRIMARY KEY,source TEXT);
          CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,
            created_at REAL,usage TEXT,tool_steps TEXT,status TEXT,content TEXT);
          CREATE TABLE schedule_message_attribution(message_id INTEGER PRIMARY KEY,
            session_id TEXT,job_id TEXT,user_id TEXT);
          CREATE TABLE message_wire_transcripts(message_id INTEGER,session_id TEXT,state TEXT);
          INSERT INTO sessions VALUES('private-session','schedule');
        """)
    return path


def insert(path, row_id, *, at=100, usage=None, steps=None, mapped=True, status="completed"):
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)", (
            row_id, "private-session", "assistant", at,
            json.dumps({"input": 100, "cache": 90}) if usage is None else usage,
            json.dumps([{"state": "done"}]) if steps is None else steps,
            status, "SECRET MESSAGE CONTENT",
        ))
        if mapped:
            db.execute("INSERT INTO schedule_message_attribution VALUES(?,?,?,?)", (
                row_id, "private-session", "private-job", "private-user",
            ))


def observe(path, now=300000, **kwargs):
    return observer.observe(path, 0, now, cost_sql_path=ROOT / "ethan/scheduler/cost.py", **kwargs)


def test_cost_parity_privacy_and_complete_window(db_path):
    for row_id in range(1, 4):
        insert(db_path, row_id)
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO message_wire_transcripts VALUES(?,?,?)", (
            1, "private-session", json.dumps({"transcript": [
                {"role": "assistant", "content": "SECRET WIRE", "reasoning": "secret"},
                {"role": "tool", "content": "PRIVATE RESULT"},
            ]}),
        ))
    before = db_path.read_bytes()
    result = observe(db_path)
    assert result["cost_sql_parity"]["equal"] is True
    assert result["gate"]["quantitative_schedule_checks_pass"] is True
    assert result["gate"]["full_acceptance"] is False
    assert result["wire"][0]["reasoning_chars"] == 6
    assert result["jobs"][0]["job"] == "J1"
    output = json.dumps(result)
    for secret in ["private-session", "private-job", "private-user", "SECRET", "PRIVATE RESULT"]:
        assert secret not in output
    assert db_path.read_bytes() == before


def test_under_window_low_sample_and_future_rows(db_path):
    insert(db_path, 1, at=100)
    insert(db_path, 2, at=999999)
    insert(db_path, 3, at=0)
    insert(db_path, 4, at=200, status="running")
    result = observe(db_path, now=1000)
    assert result["sources"][0]["runs"] == 1
    assert "deployment_window_under_72h" in result["gate"]["reasons"]
    assert "insufficient_schedule_usage_samples" in result["gate"]["reasons"]
    assert result["cost_sql_parity"]["equal"] is True


def test_malformed_json_missing_cache_unmapped_and_errors(db_path):
    insert(db_path, 1, usage="broken", steps="broken", mapped=False)
    insert(db_path, 2, usage='{"input":200}', steps='["invalid",{"state":"error"}]')
    insert(db_path, 3, usage='{"input":1.5,"cache":0.5}', steps='{}')
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO message_wire_transcripts VALUES(?,?,?)", (1, "private-session", "broken"))
        db.execute("INSERT INTO message_wire_transcripts VALUES(?,?,?)", (
            2, "private-session", '{"transcript":["broken",{"role":"assistant"}]}',
        ))
    result = observe(db_path)
    source = result["sources"][0]
    assert source["usage_invalid"] == 1
    assert source["input"] == 201.5
    assert source["cache"] == 0.5
    assert source["cache_field_missing_or_nonnumeric"] == 1
    assert source["tool_errors"] == 1
    assert result["schedule_unattributed_runs"] == 1
    assert result["cost_sql_parity"]["equal"] is True
    assert not result["gate"]["quantitative_schedule_checks_pass"]


def test_missing_readonly_db_does_not_create(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        observe(missing)
    assert not missing.exists()


def test_old_schema_without_mapping_or_status(db_path):
    with sqlite3.connect(db_path) as db:
        db.execute("DROP TABLE schedule_message_attribution")
        db.execute("ALTER TABLE messages DROP COLUMN status")
        db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)", (
            1, "private-session", "assistant", 100, '{"input":100,"cache":90}', '[]', "SECRET",
        ))
    result = observe(db_path)
    assert result["attribution_available"] is False
    assert result["schedule_unattributed_runs"] == 1
    assert result["cost_sql_parity"]["reason"] == "old schema"


def test_reject_future_and_unqualified_datetime(db_path):
    with pytest.raises(ValueError):
        observer.observe(db_path, 200, 100)
    with pytest.raises(Exception, match="explicit UTC offset"):
        observer.timestamp("2026-11-26T05:23:00")
    assert observer.timestamp("2026-11-26T05:23:00+08:00") > 0


def test_cache_out_of_range_is_not_accepted(db_path):
    for row_id in range(1, 4):
        insert(db_path, row_id, usage='{"input":10,"cache":20}')
    result = observe(db_path)
    assert result["sources"][0]["cache_out_of_range"] == 3
    assert "incomplete_or_invalid_usage_coverage" in result["gate"]["reasons"]


def test_unknown_source_does_not_leak_identity(db_path):
    insert(db_path, 1)
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE sessions SET source='secret-owner-name'")
    result = observe(db_path)
    assert result["sources"][0]["source"] == "other"
    assert "secret-owner-name" not in json.dumps(result)


def test_connection_closes_after_exception(db_path, monkeypatch):
    real_connect = sqlite3.connect
    opened = []
    def tracked_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection
    def interrupted_columns(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(observer.sqlite3, "connect", tracked_connect)
    monkeypatch.setattr(observer, "columns", interrupted_columns)
    with pytest.raises(KeyboardInterrupt):
        observe(db_path)
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


def test_main_sigint_and_failure_output(tmp_path, monkeypatch, capsys):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(observer, "observe", interrupted)
    assert observer.main(["--since", "2026-11-26T05:23:00+08:00"]) == 130
    def failed(*args, **kwargs):
        raise sqlite3.OperationalError("secret database identity")
    monkeypatch.setattr(observer, "observe", failed)
    assert observer.main(["--since", "2026-11-26T05:23:00+08:00"]) == 1
    assert "secret" not in capsys.readouterr().out
