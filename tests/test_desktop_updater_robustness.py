r"""桌面端更新检查的健壮性契约。

## 真实症状

用户原话：「app 还是没有更新。点了检查也都没有」「点了之后提示正在检查更新，
之后又提示已经是最新版」。

排查发现**不是数据链路问题**（latest.json、签名、版本比较、下载包全都正常），
而是**代码本身会让状态永久卡死**：

1. `checkForUpdate()` 开头：
       if (state === "checking" || state === "downloading" || state === "installing") return;
   一旦某次 `update.download()` 挂起（网络抖动 / CDN 卡住），状态永远停在
   `downloading`，**之后每次点「检查更新」都静默 return**——用户看到的就是
   「点了没反应」。

2. `update.download()` 没有任何超时保护。

3. `downloading` 状态的 UI 只有一条 `pointer-events-none` 的 1.5px 细线、无文字，
   用户根本注意不到。

## 契约

1. 下载必须有超时，超时后能回到可重试状态
2. 状态卡死超过阈值时必须允许重置
3. `downloading` 必须给用户可见的文字反馈
4. 「没更新」必须显式告知，不能静默
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPDATER = ROOT / "desktop/src/lib/use-updater.ts"
TOAST = ROOT / "desktop/src/components/update-toast.tsx"
ABOUT = ROOT / "desktop/src/components/settings/about-tab.tsx"


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── 超时保护 ─────────────────────────────────────────────────


def test_download_has_timeout():
    """`update.download()` 必须被超时包住。

    Tauri 的 download 返回的 Promise 在网络异常时可能永不 settle，
    没有 race 就会永久占用 downloading 状态。
    """
    src = _src(UPDATER)
    assert "DOWNLOAD_TIMEOUT_MS" in src, "缺少下载超时常量"
    assert "Promise.race" in src, "download 必须用 Promise.race 加超时"
    # 确认 race 包的是 downloadPromise
    race_idx = src.index("Promise.race")
    assert "downloadPromise" in src[race_idx : race_idx + 400], (
        "Promise.race 里应该包 downloadPromise"
    )


def test_timeout_is_reasonable():
    """超时不能太短（误杀慢速下载）也不能太长（等于没有）。"""
    src = _src(UPDATER)
    assert "DOWNLOAD_TIMEOUT_MS = 5 * 60_000" in src, (
        "8MB 的桌面更新包，5 分钟超时是合理值；改成别的请说明理由"
    )


# ── 卡死状态自愈 ─────────────────────────────────────────────


def test_stuck_state_guard_exists():
    """状态卡住超过阈值必须能自愈，否则用户永远点不动。"""
    src = _src(UPDATER)
    assert "STUCK_STATE_MS" in src, "缺少卡死判定阈值"
    assert "强制重置" in src or "强制" in src, "卡死后应主动重置状态"


def test_stuck_guard_allows_retry():
    """卡死时不能仍然直接 return —— 必须重置后再继续。"""
    src = _src(UPDATER)
    idx = src.index("STUCK_STATE_MS")
    # 卡死分支里必须有 setState 重置
    tail = src[idx : idx + 1500]
    assert "setState({ state: \"idle\"" in tail, (
        "卡死后应把状态重置为 idle，否则下次检查仍被拦"
    )


def test_ready_state_still_blocks():
    """`ready` / `installed` 是「已下好等重启」，这时重复检查没意义，应继续拦截。"""
    src = _src(UPDATER)
    assert 'if (currentState.state === "ready" || currentState.state === "installed") return;' in src


# ── 用户可见反馈 ─────────────────────────────────────────────


def test_downloading_shows_text_not_just_bar():
    """下载中必须给文字反馈，不能只有一条看不见的细线。"""
    src = _src(TOAST)
    # 找到 downloading 分支
    idx = src.index('state === "downloading"')
    branch = src[idx : idx + 1200]
    assert "正在下载" in branch, "下载中应显示「正在下载」文字"
    assert "pointer-events-none" not in branch, (
        "下载提示不能是 pointer-events-none —— 用户点不到也注意不到"
    )


def test_no_update_is_reported():
    """「没检测到更新」必须显式告知。之前是静默回 idle。"""
    src = _src(UPDATER)
    assert "upToDate" in src, "缺少「已是最新」状态字段"
    assert "没有可用更新" in src, "应记录/展示「没有可用更新」"


def test_about_tab_shows_uptodate():
    src = _src(ABOUT)
    assert "upToDate" in src, "关于页要消费 upToDate"
    assert "已是最新" in src, "关于页应显示「已是最新版本」"


def test_error_state_is_visible():
    """出错必须有可见错误，不能静默吞掉。"""
    src = _src(ABOUT)
    assert "{error &&" in src, "关于页应渲染 error"


# ── 不允许静默返回 ───────────────────────────────────────────


def test_load_updater_failure_is_reported():
    """updater 模块加载失败时不能静默 return。"""
    src = _src(UPDATER)
    idx = src.index("const mod = await loadUpdater();")
    branch = src[idx : idx + 500]
    assert "setState" in branch, "加载失败应设置可见状态，不能静默 return"
