"""Tests for browser_* 工具的宽松频率上限（TOOL_FREQ_LIMIT_BROWSER）。

背景：浏览器批量任务（如「搜索 Top10 逐个打开详情页补全指标」）会连续调用
browser_page/browser_tab，参数每次不同。旧逻辑对「同工具不同参数」统一用
TOOL_FREQ_LIMIT_VARIED(6) 的宽松上限（外层由 TOOL_FREQ_LIMIT=8 门控，故最小
熔断轮数为 8），实测抖音/小红书 Top10 抓取常在第 14~22 轮被误判为死循环收尾。

本次给 browser_* 一个更高的 varied 上限 TOOL_FREQ_LIMIT_BROWSER(20)，同时保留：
- 精确重复（STUCK_WINDOW）
- 连续同签名报错（ERROR_WINDOW）
- 完全相同参数的严格频率上限（TOOL_FREQ_LIMIT）
这三条更早刹车的分支不受影响，避免无限放行浪费 token。
"""
from __future__ import annotations

from dataclasses import dataclass

from ethan.core.loop_control import (
    ERROR_WINDOW,
    STUCK_WINDOW,
    TOOL_FREQ_LIMIT,
    TOOL_FREQ_LIMIT_BROWSER,
    LoopMonitor,
)


@dataclass
class _TC:
    name: str
    arguments: dict


def _call(mon: LoopMonitor, name: str, args: dict, err: bool = False) -> None:
    mon.record([_TC(name, args)], err)


def test_non_browser_varied_trips_at_tool_freq_limit():
    """非 browser 工具、参数每次不同 → 在 TOOL_FREQ_LIMIT 轮熔断（varied）。"""
    m = LoopMonitor()
    for i in range(TOOL_FREQ_LIMIT):
        _call(m, "some_tool", {"i": i})
    assert m.is_stuck() is True
    assert m._freq_limit_varied is True


def test_browser_varied_not_stuck_at_old_limit():
    """回归点：browser_page 不同参数在旧上限(8)轮不应熔断（抖音/小红书误砍场景）。"""
    m = LoopMonitor()
    for i in range(TOOL_FREQ_LIMIT):
        _call(m, "browser_page", {"action": "eval", "script": f"s{i}"})
    assert m.is_stuck() is False


def test_browser_varied_trips_at_browser_limit():
    """browser_page 不同参数 → 到 TOOL_FREQ_LIMIT_BROWSER 轮才熔断。"""
    m = LoopMonitor()
    for i in range(TOOL_FREQ_LIMIT_BROWSER):
        _call(m, "browser_page", {"action": "eval", "script": f"s{i}"})
    assert m.is_stuck() is True
    assert m._freq_limit_varied is True


def test_browser_exact_repeat_strict_limit():
    """browser_page 参数完全相同 → 到 TOOL_FREQ_LIMIT 严格熔断，不放宽到 BROWSER 上限。"""
    m = LoopMonitor()
    for _ in range(TOOL_FREQ_LIMIT):
        _call(m, "browser_page", {"action": "eval", "script": "SAME"})
    assert m.is_stuck() is True


def test_browser_consecutive_errors_fast_break():
    """browser 连续同签名报错 → ERROR_WINDOW 快速熔断，不受宽松上限影响。"""
    m = LoopMonitor()
    for _ in range(ERROR_WINDOW):
        _call(m, "browser_page", {"action": "eval", "script": "BAD"}, err=True)
    assert m.is_stuck() is True


def test_browser_exact_repeat_stuck_window():
    """browser 精确重复 → STUCK_WINDOW 熔断（比频率上限更早）。"""
    m = LoopMonitor()
    for _ in range(STUCK_WINDOW):
        _call(m, "browser_page", {"action": "snapshot", "session": "x"})
    assert m.is_stuck() is True
