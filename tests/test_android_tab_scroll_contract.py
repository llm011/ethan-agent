r"""Android 设置 Tab 的滚动契约 —— 防止嵌套滚动导致闪退。

## 真实崩溃

用户反馈：「APP 上，我切到内核的设置页里，app 就崩了」。

根因：`SettingsScreen` 的 `HorizontalPager` 给每页提供了一个
`Column(fillMaxSize + verticalScroll())` 作为滚动容器，
而我新增的 `KernelSettings` / `VoiceSettings` **内部又套了一层
`fillMaxSize() + verticalScroll()`**。

Compose 里嵌套 `verticalScroll` 会让内层拿到**无界高度约束**，
测量阶段直接抛异常 → 切到该 Tab 就闪退。

## 契约

设置页的各个 Tab 内容组件**只负责内容，不负责滚动**——
滚动由外层 Pager 统一提供。这条用测试锁住，避免以后又有人加一层。
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_DIR = ROOT / "app/android/app/src/main/kotlin/com/ethan/agent/ui/settings"


def _tab_components() -> list[Path]:
    """设置页目录下所有自成一个 Tab 的 Compose 文件。"""
    return sorted(p for p in SETTINGS_DIR.glob("*.kt"))


def test_settings_screen_owns_the_scroll():
    """外层 SettingsScreen 必须提供滚动容器。

    这是前提：如果外层没有滚动，各 Tab 不滚动就看不了长内容。
    """
    src = (SETTINGS_DIR / "SettingsScreen.kt").read_text(encoding="utf-8")
    assert "verticalScroll" in src, "外层设置页应提供 verticalScroll"
    assert "HorizontalPager" in src, "设置页应按 Pager 组织"


@pytest.mark.parametrize("path", _tab_components(), ids=lambda p: p.name)
def test_tab_components_do_not_scroll_themselves(path: Path):
    """各个 Tab 组件内部不能再用 verticalScroll —— 会与外层形成嵌套。

    注释里提到 verticalScroll（解释为什么不能加）是允许的，
    所以这里只检查**实际调用**：`.verticalScroll(` 或 `verticalScroll(remember...`。
    """
    if path.name == "SettingsScreen.kt":
        pytest.skip("外层容器，本就应该提供滚动")

    src = path.read_text(encoding="utf-8")
    # 去掉注释行再判断，避免把解释性注释当成使用
    code = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith(("//", "*", "/*"))
    )
    assert ".verticalScroll(" not in code, (
        f"{path.name} 内部用了 verticalScroll —— 外层 Pager 已经提供滚动，"
        f"嵌套会导致测量期崩溃（实测踩到）。只保留 fillMaxWidth + padding。"
    )


def test_tab_components_do_not_fill_max_size():
    """Tab 组件不该 fillMaxSize。

    外层已经给了 fillMaxSize 的滚动容器；内层再 fillMaxSize 会
    在滚动容器里形成「子项要求等于父项高度」的矛盾约束。
    用 fillMaxWidth 即可。
    """
    for path in _tab_components():
        if path.name == "SettingsScreen.kt":
            continue
        src = path.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in src.splitlines() if not line.strip().startswith(("//", "*", "/*"))
        )
        assert "fillMaxSize()" not in code, (
            f"{path.name} 用了 fillMaxSize —— Tab 内容在滚动容器里应只声明 fillMaxWidth"
        )
