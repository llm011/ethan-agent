r"""system/*.md 每周体检 —— 只报告不动手。

## 为什么是「只报告」

手工拆分过一次（34K → 14K），发现自动判断不可靠：

| 章节 | 按标题看像 | 实际是 |
|---|---|---|
| `生图公共池限流（2026-10-21）` | 带日期的日志 | 活规则：3张/60秒、降级链 |
| `画图技能定型（2026-10-21）` | 带日期的日志 | 模型清单与路由配置 |
| `cua-driver 直接调用（2026-08-28）` | 带日期的日志 | 绕过工具的操作路径 |

它们标题像事件记录，内容却是操作规范。误归档的代价是 **agent 在某个任务上
悄悄做错**（表现是「这次没做好」而非报错），比多花几千 token 严重得多。

所以这个模块只算账、只打日志，把决定权留给人。

## 契约

1. 按 7 天节流，每天被调用也只做事一次
2. 低于阈值不产生任何告警（避免噪音）
3. 超阈值时报告文件、体积、以及**最大的几个章节**（帮人快速定位）
4. **绝不修改任何 system 文件**（纯读）
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """隔离 system_dir 与状态文件，避免动真实数据。"""
    import ethan.core.paths as paths_mod
    import ethan.core.services.system_files_check as mod

    sdir = tmp_path / "system"
    sdir.mkdir()
    state = tmp_path / "state"

    monkeypatch.setattr(paths_mod, "system_dir", lambda: sdir)
    monkeypatch.setattr(mod, "_state_path", lambda: state / "check.json")
    return mod, sdir, state


def _write(p: Path, sections: int, chars_each: int) -> None:
    body = []
    for i in range(sections):
        body.append(f"## 章节 {i}\n" + ("x" * chars_each) + "\n\n")
    p.write_text("# 标题\n\n" + "".join(body), encoding="utf-8")


# ── 节流 ─────────────────────────────────────────────────────


def test_skips_within_interval(isolated):
    """7 天内重复调用不应做事。"""
    mod, sdir, _ = isolated
    _write(sdir / "tools.md", 5, 10_000)

    first = mod.check_system_files(force=True)
    assert first is not None

    # 立刻再查（不 force）→ 应跳过
    assert mod.check_system_files() is None


def test_force_bypasses_interval(isolated):
    mod, sdir, _ = isolated
    _write(sdir / "tools.md", 5, 10_000)
    mod.check_system_files(force=True)
    assert mod.check_system_files(force=True) is not None


def test_interval_is_one_week(isolated):
    """周期常量必须是 7 天 —— 改小了会天天打扰，改大了失去意义。"""
    mod, _, _ = isolated
    assert mod.CHECK_INTERVAL_SECONDS == 7 * 24 * 3600


# ── 阈值 ─────────────────────────────────────────────────────


def test_no_warning_below_threshold(isolated):
    mod, sdir, _ = isolated
    _write(sdir / "tools.md", 2, 1_000)   # 远低于阈值

    r = mod.check_system_files(force=True)
    assert r is not None
    assert r["items"] == []


def test_warns_above_threshold(isolated):
    mod, sdir, _ = isolated
    # 造一个明显超 WARN_CHARS 的文件
    _write(sdir / "tools.md", 10, mod.WARN_CHARS // 5)

    r = mod.check_system_files(force=True)
    assert r["items"], "超阈值应产生告警项"
    item = r["items"][0]
    assert item["file"] == "tools.md"
    assert item["chars"] >= mod.WARN_CHARS
    assert item["level"] in ("warn", "urgent")


def test_urgent_level_for_very_large(isolated):
    mod, sdir, _ = isolated
    _write(sdir / "tools.md", 10, mod.URGENT_CHARS // 5)

    r = mod.check_system_files(force=True)
    assert r["items"][0]["level"] == "urgent"


def test_reports_top_sections(isolated):
    """要报出最大的几个章节 —— 否则人不知道该看哪。"""
    mod, sdir, _ = isolated
    # 一大一小两节
    (sdir / "tools.md").write_text(
        "# 头\n\n## 小章节\n" + "a" * 100 + "\n\n## 大章节\n" + "b" * (mod.WARN_CHARS) + "\n",
        encoding="utf-8",
    )
    r = mod.check_system_files(force=True)
    tops = r["items"][0]["top_sections"]
    assert tops, "应给出最大章节列表"
    assert "大章节" in tops[0]["title"], "最大的那节应排第一"


# ── 纯读，不改文件 ───────────────────────────────────────────


def test_does_not_modify_system_files(isolated):
    """这个模块绝不能动 system 文件 —— 归档是人的决定。"""
    mod, sdir, _ = isolated
    f = sdir / "tools.md"
    _write(f, 10, mod.WARN_CHARS // 5)
    before = f.read_bytes()
    mtime = f.stat().st_mtime

    mod.check_system_files(force=True)

    assert f.read_bytes() == before, "文件内容被改了"
    assert f.stat().st_mtime == mtime, "文件被写过了"


def test_state_file_records_timestamp(isolated):
    """节流靠状态文件，必须能正确读写。"""
    mod, sdir, state = isolated
    _write(sdir / "tools.md", 1, 100)
    before = time.time()
    mod.check_system_files(force=True)

    p = state / "check.json"
    assert p.exists(), "应写入状态文件"
    ts = json.loads(p.read_text())["last_check_ts"]
    assert ts >= before


def test_corrupt_state_treated_as_never_checked(isolated):
    """状态文件坏了不能崩，应当作「从未检查」。"""
    mod, sdir, state = isolated
    _write(sdir / "tools.md", 1, 100)
    state.mkdir(parents=True, exist_ok=True)
    (state / "check.json").write_text("not json at all", encoding="utf-8")

    r = mod.check_system_files(force=True)
    assert r is not None, "坏状态文件不该导致崩溃或跳过"


# ── 接入 ─────────────────────────────────────────────────────


def test_wired_into_midnight_loop():
    """必须挂在每天 0 点的循环里 —— 否则永远不会被调用。"""
    src = (
        Path(__file__).resolve().parent.parent
        / "ethan/core/services/heartbeat.py"
    ).read_text(encoding="utf-8")
    assert "check_system_files" in src, "心跳里没接入体检"
    # 应该在 midnight loop 里（夜间沉淀之后）
    idx = src.index("Midnight consolidation done")
    tail = src[idx : idx + 800]
    assert "check_system_files" in tail, "应挂在夜间沉淀之后"
