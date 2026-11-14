r"""设置页 Tab 列表一致性测试。

「加了 Tab 但页面打不开」是个反复出现的坑：Tab 定义分散在三处，漏一处就静默坏掉。

三处：
  1. `web/components/settings-view.tsx`  —— TabId 联合类型 + TAB_GROUPS（渲染入口）
  2. `web/app/(protected)/settings/[tab]/page.tsx` —— VALID_TABS（静态导出白名单）
  3. `desktop/src/App.tsx` 的 VALID_TABS —— 深链接合法性校验

第 2 处最阴：`output: "export"` 只会为 VALID_TABS 里列出的 tab 生成页面。
漏了不会编译报错，只是 /settings/<新tab> 没有产物——用户点进去 404 或被
打回默认页。实测踩到：加了「AI 内核」「语音」两个 Tab，忘了同步这一处，
用户点内核设置直接被跳回 chat。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WEB_VIEW = ROOT / "web/components/settings-view.tsx"
WEB_PAGE = ROOT / "web/app/(protected)/settings/[tab]/page.tsx"
DESKTOP_APP = ROOT / "desktop/src/App.tsx"


def _read(p: Path) -> str:
    assert p.exists(), f"找不到 {p}"
    return p.read_text(encoding="utf-8")


def _tabid_union() -> list[str]:
    """从 settings-view.tsx 的 `type TabId = "a" | "b" | ...` 提取全部 tab。"""
    src = _read(WEB_VIEW)
    m = re.search(r"type TabId\s*=\s*([^;]+);", src)
    assert m, "没找到 TabId 类型定义"
    return re.findall(r'"([a-z0-9-]+)"', m.group(1))


def _valid_tabs(path: Path) -> list[str]:
    src = _read(path)
    m = re.search(r"VALID_TABS\s*=\s*\[([^\]]+)\]", src)
    assert m, f"{path.name} 里没找到 VALID_TABS"
    return re.findall(r'"([a-z0-9-]+)"', m.group(1))


def test_web_static_export_covers_all_tabs():
    """静态导出白名单必须覆盖渲染层声明的全部 tab。

    这一条就是「点内核设置跳回 chat」的直接回归测试。
    """
    declared = set(_tabid_union())
    exported = set(_valid_tabs(WEB_PAGE))
    missing = sorted(declared - exported)
    assert not missing, (
        f"这些 Tab 在 settings-view.tsx 里声明了，但静态导出白名单没有——"
        f"访问 /settings/<tab> 会 404 或被打回默认页：{missing}"
    )


def test_desktop_deeplink_covers_all_tabs():
    """Desktop 的深链接白名单同样要覆盖全部 tab。"""
    declared = set(_tabid_union())
    valid = set(_valid_tabs(DESKTOP_APP))
    missing = sorted(declared - valid)
    assert not missing, (
        f"这些 Tab 在 settings-view.tsx 里声明了，但 desktop VALID_TABS 没有——"
        f"深链接会被替换成 general：{missing}"
    )


def test_kernel_and_voice_tabs_are_reachable():
    """本次新增的两个 Tab 显式断言一次（防止被上面的集合逻辑漏掉）。"""
    for tab in ("kernel", "voice"):
        assert tab in _tabid_union(), f"{tab} 不在 TabId 联合类型里"
        assert tab in _valid_tabs(WEB_PAGE), f"{tab} 不在 web 静态导出白名单里"
        assert tab in _valid_tabs(DESKTOP_APP), f"{tab} 不在 desktop 深链接白名单里"


def test_every_tab_id_has_a_render_branch():
    """每个 TabId 都要有对应的渲染分支，否则点进去是空白页。"""
    src = _read(WEB_VIEW)
    declared = set(_tabid_union())
    rendered = set(re.findall(r'activeTab\s*===\s*"([a-z0-9-]+)"', src))
    missing = sorted(declared - rendered)
    assert not missing, f"这些 Tab 没有渲染分支（点进去会空白）：{missing}"
