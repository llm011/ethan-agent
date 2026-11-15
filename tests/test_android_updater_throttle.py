r"""Android 更新检查的节流策略 —— 不能把新版本锁在静默期里。

## 真实症状

用户原话：「没有自动更新」（手机上装的 b12，线上已是 b13）。

## 根因（两个叠加）

1. **节流 4 小时**：
   ```kotlin
   private const val CHECK_INTERVAL_MS = 4 * 60 * 60 * 1000L // 4 小时
   ```
   而发版往往比这更密 —— 实测 b13 比 b12 只晚 **1.5 小时**发布。
   用户装完 b12 启动过一次（记下检查时间），之后 4 小时内再启动都不会检查。

2. **时间戳记在检查开头**：
   ```kotlin
   suspend fun checkForUpdate() = withContext(IO) {
       prefs.edit().putLong(KEY_LAST_CHECK, now).apply()   // ← 第一行
       ...
   ```
   不管成功失败都算「查过了」。一次网络抖动就能把用户锁进下一轮静默期。

## 契约

1. 节流间隔不能太长（发版可能 1-2 小时一次）
2. 时间戳只在**成功的**检查后记录
3. 失败必须允许立刻重试
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPDATER = ROOT / "app/android/app/src/main/kotlin/com/ethan/agent/data/AppUpdater.kt"


def _src() -> str:
    return UPDATER.read_text(encoding="utf-8")


def _interval_minutes() -> int:
    """从源码里解析出节流间隔（分钟）。"""
    m = re.search(r"CHECK_INTERVAL_MS\s*=\s*(\d+)\s*\*\s*60\s*\*\s*1000L", _src())
    assert m, "找不到 CHECK_INTERVAL_MS 定义"
    return int(m.group(1))


def test_throttle_interval_is_short_enough():
    """节流间隔要短于典型发版间隔。

    b13 比 b12 晚 1.5 小时。如果节流是 4 小时，那 1.5 小时后发布的新版本
    用户要等到 4 小时后的下次自动检查才能发现。

    30 分钟是合理折中：一次请求几 KB，不会显著耗电/耗流。
    """
    minutes = _interval_minutes()
    assert minutes <= 60, (
        f"节流间隔 {minutes} 分钟太长。发版可能 1-2 小时一次，"
        f"建议 ≤60 分钟（当前实现是 30）"
    )
    assert minutes >= 10, f"节流间隔 {minutes} 分钟太短，会频繁请求 GitHub API"


def test_timestamp_not_marked_at_check_start():
    """不能在检查一开始就记录时间戳。

    那样失败也会被当成「查过了」，一次网络抖动就锁住用户。
    """
    src = _src()
    # 找 checkForUpdate 函数体开头
    idx = src.index("suspend fun checkForUpdate()")
    head = src[idx : idx + 600]
    # try 之后紧跟的第一条语句不能是写 last_check_ts
    after_try = head.split("try {", 1)[1] if "try {" in head else ""
    first_stmts = [ln.strip() for ln in after_try.splitlines() if ln.strip()][:3]
    assert not any("KEY_LAST_CHECK" in s for s in first_stmts), (
        "checkForUpdate 开头就记时间戳了 —— 失败也会被算作「已检查」。"
        "应只在拿到确定结论（有更新/已是最新）后调用 markChecked()"
    )


def test_timestamp_marked_on_success_paths():
    """有更新 / 已是最新 两条成功路径都要记时间戳。"""
    src = _src()
    assert "markChecked()" in src, "缺少 markChecked 辅助方法"

    # UpToDate 前应有 markChecked
    up_idx = src.index("CheckResult.UpToDate")
    before = src[max(0, up_idx - 500) : up_idx]
    assert "markChecked()" in before, "UpToDate 分支应记录检查时间"

    # UpdateAvailable 前也应有
    avail_idx = src.index("CheckResult.UpdateAvailable(")
    before2 = src[max(0, avail_idx - 300) : avail_idx]
    assert "markChecked()" in before2, "UpdateAvailable 分支应记录检查时间"


def test_failure_paths_do_not_mark():
    """失败路径（错误返回）不能记时间戳。"""
    src = _src()
    # 所有 CheckResult.Error 的返回点，其前面 300 字符内不该有 markChecked
    for m in re.finditer(r"return@withContext CheckResult\.Error", src):
        before = src[max(0, m.start() - 300) : m.start()]
        # 允许同一函数里更早的 markChecked，但紧邻的语句不能是它
        last_lines = [ln.strip() for ln in before.splitlines()[-2:]]
        assert not any("markChecked()" in ln for ln in last_lines), (
            f"错误分支前紧邻 markChecked()，这会让失败也算作已检查\n位置: {m.start()}"
        )


def test_manual_check_ignores_throttle():
    """手动检查不受节流限制 —— 用户主动点了就必须真的去查。"""
    vm = (ROOT / "app/android/shared/src/commonMain/kotlin/com/ethan/agent/shared/viewmodel/UpdateViewModel.kt").read_text(encoding="utf-8")
    # autoCheck 里才有 shouldCheck 闸门；checkForUpdate 里不该有
    idx = vm.index("fun checkForUpdate(")
    body = vm[idx : idx + 500]
    assert "shouldCheck()" not in body, (
        "checkForUpdate 里不该有 shouldCheck 闸门 —— 手动检查必须无视节流"
    )
