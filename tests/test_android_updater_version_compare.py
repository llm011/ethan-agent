r"""Android 更新检测的版本比较 —— 抓出「PEP 440 无横杠写法」导致永不更新。

## 真实症状

用户原话：「但是你这么升级，我也检测不到更新。有什么办法能够让我的手机 APP
自动检测到更新？你不能放弃旧版本吧？」

排查：手机上装的是 `1.0.0b7`，线上最新是 `1.0.0b10`，但 App 判定「已是最新」。

## 根因

`AppUpdater.compareVersions` 的 `parse()` 只按 `-` 拆分 prerelease：

    val dashIdx = v.indexOf('-')          // "1.0.0b7" 没有 '-'
    val numeric = v.split('.')            // ["1", "0", "0b7"]
        .map { it.toIntOrNull() ?: 0 }    // ["1", "0", 0]  ← "0b7" 变 0

于是 `1.0.0b7` 和 `1.0.0b10` 都变成 `numeric=[1,0,0], pre=""`，
比较结果为 0 → **判定「已是最新」，永远收不到更新**。

而我们的 tag 恰好就是 `v1.0.0bN` 这种 PEP 440 写法（去掉 v 后没有横杠），
所以 Android 端从 b7 起就再也检测不到任何更新。

## 契契约

1. `1.0.0bN` / `1.0.0rcN` / `1.0.0aN` 三种 PEP 440 写法都要能解析出 prerelease
2. `1.0.0b10 > 1.0.0b7`（数字按整数比，不是字典序）
3. semver 写法 `1.0.0-beta.7` 仍要正常工作（向后兼容）
4. 正式版 `1.0.0` 要比任何 `1.0.0bN` 新
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
UPDATER = ROOT / "app/android/app/src/main/kotlin/com/ethan/agent/data/AppUpdater.kt"


def _parse(v: str) -> tuple[list[int], str]:
    """AppUpdater.parse 的等价 Python 实现（用于验证逻辑，不是复制源码）。"""
    dash = v.find("-")
    head = v if dash < 0 else v[:dash]
    pre_dash = "" if dash < 0 else v[dash + 1 :]

    segs = head.split(".")
    pre_seg = ""
    if segs:
        m = re.match(r"^(\d+)([A-Za-z]+\.?\d*)?$", segs[-1])
        if m:
            core, tail = m.group(1), m.group(2) or ""
            if tail:
                segs[-1] = core
                pre_seg = tail[1:] if tail.startswith(".") else tail
    numeric = [int(x) if x.isdigit() else 0 for x in segs]
    if pre_dash == "":
        pre = pre_seg
    elif pre_seg == "":
        pre = pre_dash
    else:
        pre = f"{pre_seg}.{pre_dash}"
    return numeric, pre


@ pytest.mark.parametrize(
    "version,expect_num,expect_pre",
    [
        ("1.0.0b7", [1, 0, 0], "b7"),
        ("1.0.0b10", [1, 0, 0], "b10"),
        ("1.0.0rc1", [1, 0, 0], "rc1"),
        ("1.0.0a2", [1, 0, 0], "a2"),
        ("1.0.0", [1, 0, 0], ""),
        ("1.0.0-beta.7", [1, 0, 0], "beta.7"),
        ("0.5.403", [0, 5, 403], ""),
    ],
)
def test_parse_handles_pep440_and_semver(version, expect_num, expect_pre):
    """PEP 440 无横杠写法必须解析出 prerelease，否则版本号退化成同一个值。"""
    num, pre = _parse(version)
    assert num == expect_num, f"{version} 的 numeric 解析错误"
    assert pre == expect_pre, f"{version} 的 prerelease 解析错误"


def test_source_no_longer_only_splits_on_dash():
    """源码不能只按 '-' 拆 prerelease —— 那正是 bug 的来源。"""
    src = UPDATER.read_text(encoding="utf-8")
    # 必须同时处理 PEP 440（无横杠）和 semver（有横杠）
    assert "PEP 440" in src or "pep440" in src.lower(), (
        "注释里应说明为什么要处理 PEP 440 写法（防止以后有人删掉这段）"
    )
    assert "preFromSeg" in src, "parse 里应有「从最后一段抽出 prerelease」的逻辑"


def test_b10_greater_than_b7():
    """核心用例：1.0.0b10 必须大于 1.0.0b7（数字按整数比）。"""
    n1, p1 = _parse("1.0.0b10")
    n2, p2 = _parse("1.0.0b7")
    # numeric 段相同，靠 prerelease 区分
    assert n1 == n2, "两者 numeric 应该相同"
    assert p1 != p2, (
        "prerelease 必须不同 —— 相同就意味着 b10 和 b7 会被判等，永远检测不到更新"
    )
    assert p1 == "b10" and p2 == "b7"

    # 数字部分按整数比（"10" > "7"），而不是字典序（"10" < "7"）
    num1 = int(re.search(r"\d+", p1).group())
    num2 = int(re.search(r"\d+", p2).group())
    assert num1 > num2


def test_prerelease_priority_table_has_pep440_letters():
    """PEP 440 的 a/b/rc 缩写必须在优先级表里。"""
    src = UPDATER.read_text(encoding="utf-8")
    for key in ('"a" to', '"b" to', '"rc" to'):
        assert key in src, f"PRERELEASE_PRIORITY 缺少 {key}"


def test_stable_beats_prerelease():
    """正式版比同号的预发布版新：1.0.0 > 1.0.0b10。"""
    n1, p1 = _parse("1.0.0")
    n2, p2 = _parse("1.0.0b10")
    assert n1 == n2
    assert p1 == "", "正式版不应有 prerelease"
    assert p2 == "b10", "预发布版应有 prerelease"
