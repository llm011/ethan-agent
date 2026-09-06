"""StreamCollector 工具计时与配对测试。

feed() 是纯同步方法，不需要 pytest-asyncio。用假时钟（monkeypatch 模块级 time）
精确控制 start→done 间隔，验证 duration_ms 计算与 tool_call_id 配对逻辑。
"""
import pytest

import ethan.core.stream_collector as sc
from ethan.core.stream_collector import StreamCollector
from ethan.providers.base import ToolEvent


class FakeClock:
    """可控时钟：monkeypatch 掉 stream_collector.time。"""

    def __init__(self):
        self.now = 1000.0

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    # feed/_handle_tool_event 里所有 time.time() 都走 FakeClock.time
    monkeypatch.setattr(sc.time, "time", c.time)
    return c


def _start(name: str, call_id: str = "", gen_ms: int | None = None, **kw) -> ToolEvent:
    return ToolEvent(tool_name=name, args_summary="", state="start",
                     tool_call_id=call_id, gen_ms=gen_ms, **kw)


def _done(name: str, call_id: str = "", result_preview: str = "ok", **kw) -> ToolEvent:
    return ToolEvent(tool_name=name, args_summary="", state="done",
                     tool_call_id=call_id, result_preview=result_preview, **kw)


def test_basic_start_done_timing_and_gen_ms(clock):
    """基础计时：start→done 的墙钟差落到 duration_ms；gen_ms 保留在 step 上。"""
    c = StreamCollector()
    c.feed(_start("web_search", call_id="c1", gen_ms=850))
    clock.advance(1.5)
    c.feed(_done("web_search", call_id="c1"))

    assert len(c.tool_steps) == 1
    step = c.tool_steps[0]
    assert step["duration_ms"] == 1500
    assert step["gen_ms"] == 850          # done 不覆盖 start 带来的 gen_ms
    assert step["state"] == "done"
    assert step["result_preview"] == "ok"


def test_same_name_concurrent_tools_paired_by_call_id(clock):
    """同名工具并发：按 tool_call_id 精确配对，A/B 各自的 duration 不串。"""
    c = StreamCollector()
    # A start(t0) → B start(t0.25) → A done(t0.75) → B done(t1.25) 乱序完成
    c.feed(_start("shell", call_id="A", gen_ms=100))
    clock.advance(0.25)
    c.feed(_start("shell", call_id="B", gen_ms=100))
    clock.advance(0.5)
    c.feed(_done("shell", call_id="A", result_preview="A-result"))
    clock.advance(0.5)
    c.feed(_done("shell", call_id="B", result_preview="B-result"))

    a, b = c.tool_steps[0], c.tool_steps[1]
    assert a["id"] == "A" and b["id"] == "B"
    assert a["duration_ms"] == 750
    assert b["duration_ms"] == 1000       # 旧逻辑按 tool_name 计时会算成 1250
    assert a["result_preview"] == "A-result"   # 旧逻辑会把 B 的结果错挂在 A 上
    assert b["result_preview"] == "B-result"
    assert all(s["state"] == "done" for s in c.tool_steps)


def test_done_without_start_does_not_crash(clock):
    """done 带未知 tool_call_id（无对应 start）：不崩，兜底 0ms；
    id 匹配不上时回退按名匹配，会关闭最近的同名 running step（兜底语义，与旧逻辑一致）。"""
    c = StreamCollector()
    c.feed(_start("shell", call_id="X"))
    clock.advance(0.125)
    # GHOST 没有对应 start：_times 无记录按当前时间兜底 → duration≈0，
    # 且回退按名匹配到 X 的 running step 并关闭（不崩）
    c.feed(_done("shell", call_id="GHOST"))

    step = c.tool_steps[0]
    assert step["state"] == "done"
    assert step["duration_ms"] == 0       # GHOST key 无计时记录，兜底 0ms

    # 已关闭的 step 不会被重复匹配（X 的 done 再来时无 running 同名 step，静默忽略）
    c.feed(_done("shell", call_id="X"))
    assert len(c.tool_steps) == 1


def test_empty_call_id_falls_back_to_tool_name(clock):
    """空 tool_call_id（旧事件）回退按 tool_name 配对。"""
    c = StreamCollector()
    c.feed(_start("shell"))
    clock.advance(0.2)
    c.feed(_done("shell"))  # 无 call_id

    step = c.tool_steps[0]
    assert step["id"] == ""
    assert step["duration_ms"] == 200
    assert step["state"] == "done"


def test_step_dict_persistence_fields(clock):
    """持久化字段完整：step dict 含 id/gen_ms/duration_ms 等全量键。"""
    c = StreamCollector()
    c.feed(_start("browser_click", call_id="c9", gen_ms=1234,
                  entity_type="browser", entity_id="sess-1"))
    step = c.tool_steps[0]

    for k in ("tool", "id", "args", "intent", "state", "duration_ms", "gen_ms",
              "result_preview", "result_detail", "thought", "sub_steps", "cards",
              "entity_type", "entity_id", "injected"):
        assert k in step, f"missing key: {k}"
    assert step["id"] == "c9"
    assert step["gen_ms"] == 1234
    assert step["duration_ms"] is None    # running 态尚未计时
    assert step["entity_type"] == "browser"

    clock.advance(0.25)
    c.feed(_done("browser_click", call_id="c9"))
    assert c.tool_steps[0]["duration_ms"] == 250
