"""Tests for 「只读分段读取」豁免 varied 频率熔断。

背景（真实 badcase，会话 s_20261112_1603_c3ca）：深度 review 一个 MR 时，
模型先用 `bytedcli codebase mr diff` 把 diff 拉到 /tmp/mr4522.diff，再用
`sed -n 'a,bp' mr.diff` 逐段读。前 40 轮里 42 次工具调用全部成功、无一次报错，
但 `sed` 被 _effective_tool_name 归成 `shell:sed` 这一个「工具名」，参数各异
→ 命中 TOOL_FREQ_LIMIT_VARIED(6) 的宽松频率分支，第 40 轮被判死循环熔断。
而熔断后的收尾轮模型返回空内容，用户侧表现为「对话莫名中断」。

修复：file_read 与 sed/awk/head/tail/grep 等只读分段读取命令，在「参数各异」
的频率分支里豁免——逐段读新内容本身就是推进。但：
- 精确重复（STUCK_WINDOW）仍会熔断（真在原地读同一段）
- 连续报错（ERROR_WINDOW）仍会熔断
这两条必须保留，否则真的 flail 时会一路跑到 max_iters 烧 token。
"""
from __future__ import annotations

from dataclasses import dataclass

from ethan.core.loop_control import (
    ERROR_WINDOW,
    STUCK_WINDOW,
    TOOL_FREQ_LIMIT,
    TOOL_FREQ_LIMIT_VARIED,
    LoopMonitor,
    _is_read_only_paging,
)


@dataclass
class _TC:
    name: str
    arguments: dict


def _shell(cmd: str) -> _TC:
    return _TC("shell", {"command": cmd})


def _call(mon: LoopMonitor, tc: _TC, err: bool = False) -> None:
    mon.record([tc], err)


def _sed(i: int) -> _TC:
    """模拟逐段读 diff 的第 i 段。"""
    return _shell(f"cd /tmp && sed -n '{i * 250},{i * 250 + 250}p' mr4522.diff")


# ── _is_read_only_paging 判定 ────────────────────────────────────────

def test_read_only_paging_detects_file_read():
    assert _is_read_only_paging(_TC("file_read", {"path": "a", "offset": 10})) is True


def test_read_only_paging_detects_sed_paging():
    assert _is_read_only_paging(_sed(3)) is True


def test_read_only_paging_detects_common_readers():
    for cmd in (
        "head -50 mr.diff",
        "tail -c 4000 log.txt",
        "grep -n 'foo' mr.diff",
        "cat -n mr.diff",
        "awk 'NR>10' mr.diff",
        "rg pattern .",
    ):
        assert _is_read_only_paging(_shell(cmd)) is True, cmd


def test_read_only_paging_rejects_writes_and_actions():
    """非只读命令不能被豁免，否则真的打转也拦不住。"""
    for cmd in (
        "rm -rf /tmp/x",
        "bytedcli codebase mr diff 4522",
        "git commit -m x",
        "python3 train.py",
    ):
        assert _is_read_only_paging(_shell(cmd)) is False, cmd


def test_read_only_paging_rejects_write_options_and_redirects():
    """白名单命令带写文件选项 / 输出重定向时不能豁免（review 反馈的反例）。"""
    for cmd in (
        "sed -i 's/a/b/' f.py",
        "sed --in-place 's/a/b/' f.py",
        "sort -o b.txt a.txt",
        "sed -n '1,5p' a.diff > out.txt",
        "cat a.txt >> log.txt",
        "awk '{print > \"out.txt\"}' a.txt",
        "awk '{system(\"touch /tmp/x\")}' a.txt",
    ):
        assert _is_read_only_paging(_shell(cmd)) is False, cmd


def test_read_only_paging_keeps_harmless_redirects_and_comparisons():
    """2>&1、/dev/null 和引号里的 NR>10 比较不算写操作，别把正常分页误伤。"""
    for cmd in (
        "sed -n '1,5p' a.diff 2>&1",
        "grep -n foo a.diff 2>/dev/null",
        "awk 'NR>10' mr.diff",
        "awk 'x>3 {print}' mr.diff",
    ):
        assert _is_read_only_paging(_shell(cmd)) is True, cmd


def test_sed_in_place_write_loop_still_trips_varied_limit():
    """回归点：连续 30 轮 sed -i（参数各异）不能靠只读豁免一路放到 max_iters。"""
    m = LoopMonitor()
    tripped_at = None
    for i in range(30):
        _call(m, _shell(f"sed -i 's/foo{i}/bar/' f{i}.py"))
        if m.is_stuck() and tripped_at is None:
            tripped_at = i + 1
    # 具体轮次取决于 TOOL_FREQ_LIMIT / VARIED 的组合，只要求确实在有限轮内拦住
    assert tripped_at is not None
    assert tripped_at <= TOOL_FREQ_LIMIT
    assert m._freq_limit_varied is True


def test_read_only_paging_only_last_segment_matters():
    """复合命令只看最后一段，与 _effective_tool_name 的口径一致。"""
    assert _is_read_only_paging(_shell("cd /tmp && sed -n '1,10p' a.diff")) is True
    assert _is_read_only_paging(_shell("cat a.txt && rm a.txt")) is False


def test_read_only_paging_ignores_python_and_file_write():
    assert _is_read_only_paging(_TC("file_write", {"path": "a"})) is False
    assert _is_read_only_paging(_shell("python3 -c 'print(1)'")) is False


# ── 豁免行为（核心回归点） ───────────────────────────────────────────

def test_sed_paging_never_trips_varied_limit():
    """回归点：逐段 sed 读 diff 40 轮（真实 badcase 的规模）不应熔断。"""
    m = LoopMonitor()
    for i in range(40):
        _call(m, _sed(i))
        assert m.is_stuck() is False, f"第 {i + 1} 轮被误判熔断"


def test_file_read_paging_never_trips_varied_limit():
    """file_read 分页读本来就在豁免名单，保持一致。"""
    m = LoopMonitor()
    for i in range(40):
        _call(m, _TC("file_read", {"path": "mr.diff", "offset": i * 100, "limit": 100}))
        assert m.is_stuck() is False


def test_mixed_read_paging_rounds_are_exempt():
    """一轮里全是只读命令（sed + grep 混合）也算只读轮。"""
    m = LoopMonitor()
    for i in range(40):
        m.record([_sed(i), _shell(f"grep -n 'x{i}' mr4522.diff")], False)
        assert m.is_stuck() is False


# ── 豁免不能把真正的卡住放过去 ───────────────────────────────────────

def test_exact_repeat_of_same_sed_still_trips():
    """豁免只针对「参数各异」；同一段反复读仍按 STUCK_WINDOW 熔断。"""
    m = LoopMonitor()
    for _ in range(STUCK_WINDOW):
        _call(m, _sed(2))
    assert m.is_stuck() is True


def test_exact_repeat_of_same_sed_still_trips_freq():
    """同一段读满 TOOL_FREQ_LIMIT 轮 → 精确重复的严格频率分支照旧熔断。"""
    m = LoopMonitor()
    for _ in range(TOOL_FREQ_LIMIT):
        _call(m, _sed(2))
    assert m.is_stuck() is True


def test_read_paging_errors_still_fast_break():
    """同一个 sed 反复报错（文件不存在）→ ERROR_WINDOW 快速熔断，不被豁免影响。"""
    m = LoopMonitor()
    for _ in range(ERROR_WINDOW):
        _call(m, _shell("sed -n '1,10p' /nope.diff"), err=True)
    assert m.is_stuck() is True


def test_mixed_round_with_write_is_not_exempt():
    """一轮里混了写操作 → 该轮不算只读轮，不享受豁免。"""
    m = LoopMonitor()
    for i in range(TOOL_FREQ_LIMIT_VARIED + 2):
        m.record([_sed(i), _shell(f"rm /tmp/f{i}")], False)
    # 有效工具名取第一个（sed），但该轮非全只读 → 应按 varied 熔断
    assert m.is_stuck() is True


def test_non_read_only_varied_still_trips():
    """非只读工具的参数各异场景不受影响（保持既有行为）。"""
    m = LoopMonitor()
    for i in range(TOOL_FREQ_LIMIT):
        _call(m, _shell(f"bytedcli codebase mr diff {i}"))
    assert m.is_stuck() is True
    assert m._freq_limit_varied is True
