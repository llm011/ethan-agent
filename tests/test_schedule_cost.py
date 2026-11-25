"""Synthetic data only: SQL parity, exact attribution and authenticated UI contract."""
import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from ethan.scheduler.cost import _read_costs, save_attributed_message


def _record_attribution(db_path, message_id, session_id, job_id, user_id):
    """Fixture setup only; production writes use the store's atomic interface."""
    with sqlite3.connect(db_path) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute("CREATE TABLE IF NOT EXISTS schedule_message_attribution (message_id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, job_id TEXT NOT NULL, user_id TEXT NOT NULL, FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE)")
        db.execute('CREATE INDEX IF NOT EXISTS idx_schedule_cost_job ON schedule_message_attribution(user_id,job_id)')
        db.execute('INSERT OR IGNORE INTO schedule_message_attribution VALUES(?,?,?,?)', (message_id, session_id, job_id, user_id))


@pytest.fixture
def cost_db(tmp_path):
    path = tmp_path / 'sessions.db'
    with sqlite3.connect(path) as db:
        db.executescript((Path(__file__).parent / 'fixtures/schedule_cost.sql').read_text())
    for mid, sid, job, uid in [
        (1, 'old', 'a', ''), (2, 'new', 'a', ''), (3, 'new', 'a', ''),
        (4, 'new', 'a', ''), (5, 'shared', 'a', ''), (6, 'shared', 'b', ''),
        (7, 'shared', 'a', 'other'), (8, 'new', 'a', ''), (9, 'new', 'a', ''),
        (10, 'new', 'a', ''), (11, 'new', 'a', ''), (13, 'web', 'a', ''),
        (14, 'new', 'a', ''),
    ]:
        _record_attribution(path, mid, sid, job, uid)
    return path


def test_fixture_matches_plan_sql_and_average_steps(cost_db):
    costs = _read_costs(cost_db, ['a', 'b'], '', 1000000)
    a = costs['a']
    assert a['run_count'] == 5  # no-usage + malformed usage still represent runs
    assert a['input_tokens'] == 3100
    assert a['cache_tokens'] == 1010
    assert a['average_steps'] == 1.2
    assert a['cache_hit_rate'] == 32.6
    assert a['usage_run_count'] == 3
    assert costs['b']['run_count'] == 1
    assert costs['b']['input_tokens'] == 900  # shared session not double-attributed
    with sqlite3.connect(cost_db) as db:
        # Plan section 2 SQL, constrained to the exact job's message set.
        row = db.execute("""
            SELECT sum(json_extract(usage,'$.input')), sum(json_extract(usage,'$.cache'))
            FROM messages WHERE role='assistant' AND usage IS NOT NULL AND json_valid(usage)
              AND json_extract(usage,'$.input') > 0 AND created_at > ? AND created_at <= ?
              AND id IN (SELECT message_id FROM schedule_message_attribution WHERE job_id=? AND user_id=?)
              AND session_id IN (SELECT id FROM sessions WHERE source='schedule')
              AND status NOT IN ('running','pending')
        """, (395200, 1000000, 'a', '')).fetchone()
    assert row == (a['input_tokens'], a['cache_tokens'])


def test_profile_owner_sql_and_unknown_history(cost_db):
    costs = _read_costs(cost_db, ['a', "x'); DROP TABLE messages;--"], '', 1000000)
    assert costs['a']['unattributed_runs'] == 1  # other owner's rows are not disclosed as gaps
    assert costs["x'); DROP TABLE messages;--"]['run_count'] == 0
    assert _read_costs(cost_db, ['a'], 'other', 1000000)['a']['input_tokens'] == 700
    # Persistent IDs retain old and new sessions, independent of job title/current kwargs.
    _record_attribution(cost_db, 1, 'old', 'b', '')
    assert _read_costs(cost_db, ['a'], '', 1000000)['a']['input_tokens'] == 3100


def test_read_does_not_create_or_write(tmp_path, cost_db):
    missing = tmp_path / 'absent.db'
    assert _read_costs(missing, ['a'], '', 1000000)['a']['run_count'] == 0
    assert not missing.exists()
    before = cost_db.read_bytes()
    _read_costs(cost_db, ['a'], '', 1000000)
    assert cost_db.read_bytes() == before


def test_no_mapping_means_unknown_not_guessed(tmp_path):
    path = tmp_path / 'old.db'
    with sqlite3.connect(path) as db:
        db.executescript((Path(__file__).parent / 'fixtures/schedule_cost.sql').read_text())
    a = _read_costs(path, ['a'], '', 1000000)['a']
    assert a['run_count'] == 0
    assert a['unattributed_runs'] == 8
    assert a['cache_hit_rate'] is None
    assert a['average_steps'] is None


def test_finalize_reuses_progress_id_before_attribution(cost_db):
    class Store:
        _db_path = cost_db
        async def save_schedule_message(self, sid, msg, mid, job, uid):
            assert (mid, sid, job, uid) == (12, 'old', 'a', '')
            _record_attribution(self._db_path, mid, sid, job, uid)
            return mid
        async def touch(self, sid):
            assert sid == 'old'
    asyncio.run(save_attributed_message(Store(), 'old', object(), 12, 'a', ''))
    assert _read_costs(cost_db, ['a'], '', 1000000)['a']['run_count'] == 6


@pytest.mark.parametrize('progress', [False, True])
def test_atomic_finalization_rollback_and_restart(tmp_path, progress):
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message

    async def run():
        store = SessionStore(db_path=tmp_path / 'real.db')
        await store.init()
        try:
            sid = (await store.create('fixture', source='schedule')).id
            mid = await store.save_message(sid, Message(role='assistant', content='', status='running')) if progress else None
            message = Message(role='assistant', content='fixture', usage={'input': 100, 'cache': 30},
                              tool_steps=[{'tool': 'fixture'}])
            # Abort exactly AFTER message INSERT/UPDATE, BEFORE attribution can commit.
            # Setup the schema using an unrelated valid row, then fault the real run.
            seed = await store.save_message(sid, Message(role='user', content='fixture'))
            _record_attribution(store._db_path, seed, sid, 'seed', '')
            with sqlite3.connect(store._db_path) as db:
                db.execute("CREATE TRIGGER fail_cost BEFORE INSERT ON schedule_message_attribution BEGIN SELECT RAISE(ABORT, 'fixture crash window'); END")
            with pytest.raises(sqlite3.IntegrityError):
                await save_attributed_message(store, sid, message, mid, 'job', '')
            # Simulate service restart: read through a new store/connection.
            await store.close()
            store = SessionStore(db_path=tmp_path / 'real.db')
            await store.init()
            with sqlite3.connect(store._db_path) as db:
                assert db.execute("SELECT count(*) FROM messages WHERE role='assistant' AND status='completed'").fetchone()[0] == 0
                if mid:
                    assert db.execute('SELECT status, usage FROM messages WHERE id=?', (mid,)).fetchone() == ('interrupted', None)
                assert db.execute("SELECT count(*) FROM schedule_message_attribution WHERE job_id='job'").fetchone()[0] == 0
                db.execute('DROP TRIGGER fail_cost')
            final_id = await save_attributed_message(store, sid, message, mid, 'job', '')
            if mid:
                assert final_id == mid
            import time
            cost = _read_costs(store._db_path, ['job'], '', time.time())['job']
            assert (cost['run_count'], cost['input_tokens'], cost['cache_tokens']) == (1, 100, 30)
            assert cost['unattributed_runs'] == 0
            with sqlite3.connect(store._db_path) as db:
                assert db.execute("SELECT count(*) FROM messages WHERE role='assistant' AND status='completed'").fetchone()[0] == 1
                assert db.execute("SELECT count(*) FROM schedule_message_attribution WHERE job_id='job'").fetchone()[0] == 1
        finally:
            await store.close()
    asyncio.run(run())


@pytest.mark.parametrize('progress', [False, True])
def test_process_crash_between_message_and_attribution(tmp_path, progress):
    import os
    import subprocess
    import sys

    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message

    path = tmp_path / 'crash.db'
    async def setup():
        store = SessionStore(db_path=path)
        await store.init()
        sid = (await store.create('fixture', source='schedule')).id
        mid = await store.save_message(sid, Message(role='assistant', content='', status='running')) if progress else 0
        await store.close()
        return sid, mid
    sid, mid = asyncio.run(setup())
    script = """
import asyncio, os, sys
from pathlib import Path
import aiosqlite
from ethan.memory.session import SessionStore
from ethan.providers.base import Message
from ethan.scheduler.cost import save_attributed_message
async def run():
    store = SessionStore(db_path=Path(sys.argv[1]))
    await store.init()
    original = aiosqlite.Connection.execute
    def crash(self, sql, *args, **kwargs):
        if sql.lstrip().upper().startswith('INSERT') and 'SCHEDULE_MESSAGE_ATTRIBUTION' in sql.upper():
            os._exit(75)
        return original(self, sql, *args, **kwargs)
    aiosqlite.Connection.execute = crash
    await save_attributed_message(store, sys.argv[2], Message(role='assistant', content='fixture', usage={'input': 100, 'cache': 30}), int(sys.argv[3]) or None, 'job', '')
asyncio.run(run())
"""
    proc = subprocess.run([sys.executable, '-c', script, str(path), sid, str(mid)],
                          env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])},
                          capture_output=True, timeout=20)
    assert proc.returncode == 75, proc.stderr.decode()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM messages WHERE role='assistant' AND status='completed'").fetchone()[0] == 0
        if mid:
            assert db.execute('SELECT status FROM messages WHERE id=?', (mid,)).fetchone()[0] == 'interrupted'
    async def recover():
        store = SessionStore(db_path=path)
        await store.init()
        try:
            await save_attributed_message(store, sid, Message(role='assistant', content='fixture', usage={'input': 100, 'cache': 30}), mid or None, 'job', '')
        finally:
            await store.close()
    asyncio.run(recover())
    import time
    cost = _read_costs(path, ['job'], '', time.time())['job']
    assert (cost['run_count'], cost['input_tokens'], cost['unattributed_runs']) == (1, 100, 0)


def test_recorder_pending_row_is_claimed_atomically(tmp_path):
    from ethan.core.checkpoint_lifecycle import _pending_final
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message

    async def run():
        store = SessionStore(db_path=tmp_path / 'pending.db')
        await store.init()
        token = None
        try:
            sid = (await store.create('fixture', source='schedule')).id
            mid = await store.save_message(sid, Message(role='assistant', content='', status='running'))
            wire = [Message(role='user', content='fixture'), Message(role='assistant', content='fixture')]
            token = _pending_final.set((str(store._db_path), sid, mid, wire, 'completed'))
            message = Message(role='assistant', content='fixture', usage={'input': 100})
            _record_attribution(store._db_path, mid, sid, 'job', '')
            with sqlite3.connect(store._db_path) as db:
                db.execute('DELETE FROM schedule_message_attribution')
                db.execute("CREATE TRIGGER fail_pending BEFORE INSERT ON schedule_message_attribution BEGIN SELECT RAISE(ABORT, 'fixture pending rollback'); END")
            with pytest.raises(sqlite3.IntegrityError):
                await save_attributed_message(store, sid, message, None, 'job', '')
            assert _pending_final.get()[:3] == (str(store._db_path), sid, mid)
            with sqlite3.connect(store._db_path) as db:
                db.execute('DROP TRIGGER fail_pending')
            assert await save_attributed_message(store, sid, message, None, 'job', '') == mid
            assert _pending_final.get() is None
            with sqlite3.connect(store._db_path) as db:
                assert db.execute("SELECT count(*) FROM messages WHERE role='assistant'").fetchone()[0] == 1
                assert db.execute('SELECT message_id FROM schedule_message_attribution').fetchone()[0] == mid
                assert db.execute('SELECT message_id FROM message_wire_transcripts').fetchone()[0] == mid
            restored = await store.load_wire_transcripts(sid)
            assert [m.role for m in restored[mid]] == ['user', 'assistant']
        finally:
            if token is not None:
                _pending_final.reset(token)
            await store.close()
    asyncio.run(run())


def test_existing_attribution_cannot_be_reassigned(tmp_path):
    from ethan.memory.session import SessionStore
    from ethan.providers.base import Message

    async def run():
        store = SessionStore(db_path=tmp_path / 'conflict.db')
        await store.init()
        try:
            sid = (await store.create('fixture', source='schedule')).id
            msg = Message(role='assistant', content='fixture', usage={'input': 100, 'cache': 30})
            mid = await save_attributed_message(store, sid, msg, None, 'original', '')
            # Same-message retry is idempotent; another job cannot steal the row.
            assert await save_attributed_message(store, sid, msg, mid, 'original', '') == mid
            with pytest.raises(ValueError):
                await save_attributed_message(store, sid, Message(role='assistant', content='changed', usage={'input': 999}), mid, 'other', 'other-user')
            with sqlite3.connect(store._db_path) as db:
                assert db.execute('SELECT job_id,user_id FROM schedule_message_attribution WHERE message_id=?', (mid,)).fetchone() == ('original', '')
                assert db.execute('SELECT content FROM messages WHERE id=?', (mid,)).fetchone()[0] == 'fixture'
        finally:
            await store.close()
    asyncio.run(run())


def test_route_only_returns_authenticated_jobs(monkeypatch):
    from ethan.interface.routers import schedule
    def job(uid, jid):
        return SimpleNamespace(id=jid, kwargs={'user_id': uid}, name=jid,
                               trigger='cron', next_run_time=None)
    jobs = [job('', 'admin'), job('alice', 'a'), job('bob', 'b')]
    monkeypatch.setattr(schedule, 'get_scheduler', lambda: SimpleNamespace(
        _scheduler=SimpleNamespace(get_jobs=lambda: jobs)))
    async def costs(ids, uid):
        assert (ids, uid) == (['a'], 'alice')
        return {'a': {'run_count': 2}}
    monkeypatch.setattr('ethan.scheduler.cost.get_costs', costs)
    response = asyncio.run(schedule.get_schedules('alice'))
    assert [j['id'] for j in response['jobs']] == ['a']
    assert response['jobs'][0]['cost']['run_count'] == 2
