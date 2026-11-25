"""Local cheap-check regression tests; no watchdog or real provider calls."""
import asyncio
import json

from ethan.core.heartbeat_changes import LocalChangeGate
from ethan.scheduler.heartbeat import Heartbeat


def manifest(tmp_path):
    (tmp_path / "system").mkdir()
    (tmp_path / "input.md").write_text("initial")
    (tmp_path / "system" / "heartbeat-checks.json").write_text(json.dumps({"paths": ["input.md"]}))


def test_first_tick_unchanged_then_changed(tmp_path):
    manifest(tmp_path)
    gate = LocalChangeGate()
    assert gate.changed(tmp_path, "task")
    gate.commit(tmp_path)
    assert not gate.changed(tmp_path, "task")
    (tmp_path / "input.md").write_text("updated")
    assert gate.changed(tmp_path, "task")
    gate.commit(tmp_path)
    assert not gate.changed(tmp_path, "task")
    assert gate.changed(tmp_path, "updated task")


def test_failure_retries_and_legacy_not_suppressed(tmp_path, caplog):
    gate = LocalChangeGate()
    assert gate.changed(tmp_path, "remote polling task")
    gate.commit(tmp_path)
    assert gate.changed(tmp_path, "remote polling task")
    manifest(tmp_path)
    assert gate.changed(tmp_path, "task")
    # No commit means a failed model run still retries the same local change.
    assert gate.changed(tmp_path, "task")
    gate.commit(tmp_path)
    (tmp_path / "system" / "heartbeat-checks.json").write_text('{"paths":["missing.md"]}')
    assert gate.changed(tmp_path, "task")
    assert "Local checks failed" in caplog.text


def test_manifest_malformed_fallback(tmp_path, caplog):
    manifest(tmp_path)
    gate = LocalChangeGate()
    for content in ('[]', '{"paths":[]}', '{"paths":["system"]}', '{"paths":[1]}', 'not JSON'):
        (tmp_path / "system" / "heartbeat-checks.json").write_text(content)
        assert gate.changed(tmp_path, "task")
    assert "legacy periodic fallback" in caplog.text


def test_scheduler_optional_check_and_failure_fallback(caplog):
    calls = []
    hb = Heartbeat()
    hb.register(lambda: calls.append("legacy"))
    hb.register(lambda: calls.append("unchanged"), lambda: False)
    async def changed():
        return True
    async def cb():
        calls.append("changed")
    hb.register(cb, changed)
    def failed():
        raise OSError("cheap check failure")
    hb.register(lambda: calls.append("fallback"), failed)
    asyncio.run(hb._tick())
    assert calls == ["legacy", "changed", "fallback"]
    assert "change check failed" in caplog.text


def test_real_heartbeat_gate_and_owner_restoration(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from ethan.core.agent import UsageStats
    from ethan.core.context import ETHAN_SESSION_ID, ETHAN_USER_ID
    from ethan.core.services import heartbeat as hb

    manifest(tmp_path)
    (tmp_path / "system" / "heartbeat.md").write_text("check local input")
    monkeypatch.setattr(hb, "_local_change_gate", LocalChangeGate())
    cfg = SimpleNamespace(defaults=SimpleNamespace(workspace=str(tmp_path), model="fake",
                                                  heartbeat=SimpleNamespace(model=None)))
    monkeypatch.setattr("ethan.core.config.get_config", lambda: cfg)
    monkeypatch.setattr("ethan.core.users.get_user_store", lambda: SimpleNamespace(get_admin_user_id=lambda: ""))
    calls = []
    class Agent:
        usage = UsageStats()
        async def stream_chat(self, messages):
            calls.append("run")
            assert ETHAN_USER_ID.get() == ""
            assert ETHAN_SESSION_ID.get() == "hb-session"
            yield "done"
    def create_agent(**kwargs):
        assert ETHAN_USER_ID.get() == ""
        return Agent()
    monkeypatch.setattr("ethan.core.agent_factory.create_agent", create_agent)
    class Store:
        async def find_today_session(self, source):
            assert source == "heartbeat"
            assert ETHAN_USER_ID.get() == ""
            return SimpleNamespace(id="hb-session", title="[心跳] fake")
        async def save_message(self, *args):
            pass
        async def touch(self, *args):
            pass
    async def get_store():
        return Store()
    monkeypatch.setattr("ethan.memory.session.get_session_store", get_store)
    async def run():
        ut = ETHAN_USER_ID.set("another-user")
        st = ETHAN_SESSION_ID.set("another-session")
        try:
            await hb._run_heartbeat_md()
            await hb._run_heartbeat_md()
            assert calls == ["run"]
            (tmp_path / "input.md").write_text("changed")
            await hb._run_heartbeat_md()
            assert calls == ["run", "run"]
            assert ETHAN_USER_ID.get() == "another-user"
            assert ETHAN_SESSION_ID.get() == "another-session"
        finally:
            ETHAN_SESSION_ID.reset(st)
            ETHAN_USER_ID.reset(ut)
    asyncio.run(run())
