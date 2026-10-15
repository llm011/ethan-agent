"""定时任务网络故障延迟重跑：零产出的网络类错误按 _NET_RETRY_DELAYS 退避重跑，
已产出内容 / 非网络错误不重跑。"""
import asyncio

import pytest

import ethan.tools.builtin.schedule as sched_mod
from ethan.providers.base import Message, MidstreamBreakError


class _FakeAgent:
    """按脚本逐次表现：每个 create_agent 调用取下一个行为。"""

    def __init__(self, behavior):
        self._behavior = behavior
        self.runtime_context = ""
        self.session_id = ""
        from types import SimpleNamespace

        self.usage = SimpleNamespace(input_tokens=0, output_tokens=0, cache_tokens=0)
        self.model = "fake"

        class _P:
            model = "fake"

        self._provider = _P()

    async def stream_chat(self, messages):
        if self._behavior == "net_fail":
            raise MidstreamBreakError(
                "上游连接失败：trae error 502: <urlopen error [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE]>"
            )
        if self._behavior == "bad_request":
            raise ValueError("Error code: 400 - invalid request")
        if self._behavior == "partial_then_fail":
            yield "半截输出"
            raise MidstreamBreakError("connection reset")
        yield "任务完成"


def _run(tmp_path, monkeypatch, behaviors):
    monkeypatch.setenv("ETHAN_HOME", str(tmp_path))
    monkeypatch.setattr(sched_mod, "_NET_RETRY_DELAYS", (0, 0, 0))
    monkeypatch.setattr(sched_mod, "_server_loop", None)

    created = []
    script = iter(behaviors)

    def _fake_create_agent(*a, **kw):
        ag = _FakeAgent(next(script))
        created.append(ag)
        return ag

    monkeypatch.setattr("ethan.core.agent_factory.create_agent", _fake_create_agent)
    monkeypatch.setattr(
        "ethan.interface.routers.tasks._maybe_consolidate", lambda *a, **kw: asyncio.sleep(0)
    )

    from ethan.memory.session import SessionStore

    db = tmp_path / "s.db"
    monkeypatch.setattr("ethan.core.paths.user_sessions_db_path", lambda: db)

    # 同步跑 thread fallback 路径，便于断言
    import threading

    class _SyncThread:
        def __init__(self, target, daemon=None):
            self._t = target

        def start(self):
            self._t()

    monkeypatch.setattr(threading, "Thread", _SyncThread)

    sched_mod.fire_schedule_job("s_test_netretry", "跑个任务", title="测试")

    async def _load():
        s = SessionStore(db_path=db)
        await s.init()
        sess = await s.load("s_test_netretry")
        await s.close()
        return sess.messages

    return created, asyncio.run(_load())


def _assistant(msgs: list[Message]) -> list[str]:
    return [m.content for m in msgs if m.role == "assistant"]


def test_net_error_retries_then_succeeds(tmp_path, monkeypatch):
    created, msgs = _run(tmp_path, monkeypatch, ["net_fail", "net_fail", "ok"])
    assert len(created) == 3  # 每次重跑都重建 agent
    assert _assistant(msgs) == ["任务完成"]


def test_net_error_gives_up_after_all_delays(tmp_path, monkeypatch):
    created, msgs = _run(tmp_path, monkeypatch, ["net_fail"] * 4)
    assert len(created) == 4  # 首次 + 3 次延迟重跑
    out = _assistant(msgs)
    assert len(out) == 1 and "定时任务后台执行失败" in out[0]


def test_non_network_error_not_retried(tmp_path, monkeypatch):
    created, msgs = _run(tmp_path, monkeypatch, ["bad_request", "ok"])
    assert len(created) == 1
    assert "定时任务后台执行失败" in _assistant(msgs)[0]


def test_partial_output_not_retried(tmp_path, monkeypatch):
    """已产出内容再失败不重跑：避免重复执行带副作用的任务。"""
    created, msgs = _run(tmp_path, monkeypatch, ["partial_then_fail", "ok"])
    assert len(created) == 1
    out = _assistant(msgs)
    assert "半截输出" in out[0] and "定时任务后台执行失败" in out[0]


def test_is_network_error_classification():
    assert sched_mod._is_network_error(MidstreamBreakError("x"))
    assert not sched_mod._is_network_error(ValueError("Error code: 400 - bad"))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
