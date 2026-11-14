#!/usr/bin/env python3
"""把 dsh-tui 的配色对齐到 Ghostty 的 Gruvbox Material Dark，并让 faint 字可读。

背景（实测，不是猜的）：

1. 旧配色是 dsh-tui 出厂 `dark` 主题（暖灰底 + 雾蓝强调色），跟 Ghostty 的
   Gruvbox 完全不是一个色系，这是「配色感觉不太对」的来源。
2. dsh-tui 有 285 处 `dimColor: true`（SGR 2 faint）。faint 的实际表现是**终端
   把字色往自己的底色里混**，而 dsh-tui 默认请求 OSC 11 来问「终端底色」。
   herdr 的终端内核不回答 OSC 11，于是 dsh-tui 回落到纯黑 `rgb(0,0,0)`，
   faint 在 #282828 的 Gruvbox 底上又被压一轮，这才是「经常有字看不太清」。
3. 新建的上下文进度条在空闲段用了写死的 `#E8E8E8` 浅灰填充，Dark 主题下
   是整块白条。这一点只能改 npm 包里的产物 JS（没有主题键暴露 freeFill），
   所以单独做成开关（默认不打补丁）。

本脚本做三件事，全部可重复执行（幂等）：

A. `~/.dsh-tui/themes/gruvbox-material-dark.json`：从 `base: dark` 覆盖出
   Gruvbox 调色板（正文 #d4be98、背景 #1d2021 系）。任何一条覆盖都要过对比度
   门槛（正文 ≥ 4.5，faint 字 ≥ 4.0），不达标就报错退出，不写半成品。
B. `~/.dsh/profiles/tui/cordis.patch.yml` 重写 `dsh-tui` 块（幂等、带 marker）。
   默认 `fullscreen: true`：alt-screen 布局稳定，不会出现 inline 主屏模式下
   每帧追加/回滚行造成的底部空白和抖动，选中色走主题键 `selectionBg`。
   `--inline` 才写 `fullscreen: false`：inline 下 dsh-tui 不跑 OSC 11 探测，
   faint 直接用 SGR 2（终端自己混），可读性由 A 的高对比色板兜住，但代价是
   主屏布局在 pane 尺寸变化时容易重排。块里其余键放 `!!js` 转发，与包自带
   patch 的语义一致（patch 是整块替换，漏写的键会丢）。
C. `--bar-free-fill <#rrggbb>`：可选。把 dsh-tui 产物里写死的空闲段填充色
   换成同色板里的深色，并备份原文件；传 `--revert` 还原。

用法：

    uv run scripts/setup_dsh_tui_theme.py                # A + B（fullscreen）
    uv run scripts/setup_dsh_tui_theme.py --inline       # A + B（inline 主屏）
    uv run scripts/setup_dsh_tui_theme.py --bar-free-fill '#3c3836'
    uv run scripts/setup_dsh_tui_theme.py --revert       # 只还原 C
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
THEMES_DIR = HOME / ".dsh-tui" / "themes"
THEME_NAME = "gruvbox-material-dark"
THEME_PATH = THEMES_DIR / f"{THEME_NAME}.json"
PROFILE_PATCH = HOME / ".dsh" / "profiles" / "tui" / "cordis.patch.yml"

# Gruvbox Material Dark 的终端底色；Ghostty 里 background = #282828，dsh 里按
# 终端最深处 #1d2021 计算对比度（Herbr 侧 pane 底是 canvas #1d2021）。
TERMINAL_BG = "#1d2021"

# 与 herdr 主题（~/.config/herdr-app/themes/gruvbox-material-dark.json）同源。
THEME_TEXT = {
    "name": THEME_NAME,
    "displayName": "Gruvbox Material Dark",
    "base": "dark",
    "colors": {
        "accent": "#7daea3",
        "accentShimmer": "#89b482",
        "activity": "#7daea3",
        "activityShimmer": "#89b482",
        "promptBorder": "#504945",
        "promptBorderShimmer": "#7daea3",
        "permission": "#7daea3",
        "permissionShimmer": "#89b482",
        "ide": "#7daea3",
        "text": "#d4be98",
        "inverseText": "#1d2021",
        "inactive": "#a89984",
        "inactiveShimmer": "#bdae93",
        "subtle": "#928374",
        "suggestion": "#7daea3",
        "remember": "#d3869b",
        "success": "#a9b665",
        "error": "#ea6962",
        "warning": "#d8a657",
        "warningShimmer": "#e3b168",
        "merged": "#d3869b",
        "autoAccept": "#d3869b",
        "planMode": "#89b482",
        "toolCardBackground": "#32302f",
        "toolCardBackgroundDim": "#282828",
        "toolNameMutate": "#d8a657",
        "toolNameExec": "#7daea3",
        "selectionBg": "#45403d",
        "userMessageBackground": "#32302f",
        "userMessageBackgroundHover": "#3c3836",
        "messageActionsBackground": "#3c3836",
        "inputBackground": "#32302f",
        "bashMessageBackgroundColor": "#32302f",
        "memoryBackgroundColor": "#32302f",
        "bashBorder": "#d3869b",
        "diffAdded": "#2b3326",
        "diffRemoved": "#3b2a26",
        "diffAddedDimmed": "#24291f",
        "diffRemovedDimmed": "#2e2420",
        "diffAddedWord": "#a9b665",
        "diffRemovedWord": "#ea6962",
        "syntaxKeyword": "#ea6962",
        "syntaxString": "#a9b665",
        "syntaxComment": "#928374",
        "syntaxNumber": "#d3869b",
        "syntaxFunction": "#a9b665",
        "syntaxType": "#d8a657",
        "syntaxVariable": "#d4be98",
        "syntaxOperator": "#89b482",
        "syntaxPunctuation": "#bdae93",
        "syntaxConstant": "#d3869b",
        "professionalBlue": "#7daea3",
        "chromeYellow": "#d8a657",
        "contextBarSystem": "#3c3836",
        "contextBarPrompt": "#665c54",
        "contextBarAssistant": "#928374",
        "contextBarThinking": "#7daea3",
        "contextBarTools": "#d3869b",
        "ignition": "#d8a657",
        "ignitionDim": "#3c3836",
        "rate_limit_fill": "#a9b665",
        "rate_limit_empty": "#3c3836",
    },
}

# 正文/淡字必须达标的键 -> 最低对比度（WCAG 2.1，背景取 TERMINAL_BG）。
CONTRAST_FLOOR = {
    "text": 7.0,        # 正文，尽量拉高
    "inactive": 5.0,    # faint 的基础墨色（dimColor 走的正是它）
    "subtle": 4.0,
    "accent": 5.0,
    "success": 5.0,
    "error": 4.5,
    "warning": 5.0,
}

DEFAULT_FULLSCREEN = True

PROFILE_HEADER = """\
# dsh-tui 显示配置（scripts/setup_dsh_tui_theme.py 写入，可重复执行）。
#
# fullscreen 默认保持 true（alt-screen）：布局稳定，不会有 inline 模式下
# 主屏追加/回滚导致的底部空白与抖动，应用内选中走主题键 selectionBg。
# 传 --inline 才切到 inline 主屏——它会关掉 OSC 11 探测（herdr 不回答该查询，
# 回落纯黑会让 SGR 2 faint 再压一轮），但代价是每帧往主屏追加行，pane 尺寸
# 变化时容易看到重排/抖动。
#
# patch 是整块替换，下面每一项都从包自带 patch 原样转发（!!js 在加载时求值），
# 漏写的键等于删掉。
"""

PROFILE_ROW_TEMPLATE = """\
- id: dsh-tui
  config:
    fullscreen: {fullscreen}
    provider: deepseek-official
    terminalImages: true
    effort: max
    preset: !!js process.env.DSH_TUI_PRESET ?? undefined
    workspace: !!js process.env.DSH_TUI_WORKSPACE_TARGET ?? undefined
    sessionId: !!js process.env.DSH_TUI_RESUME_SESSION ?? undefined
    backend: !!js process.env.DSH_TUI_BACKEND || undefined
"""

MARKER = "# dsh-tui 显示配置（scripts/setup_dsh_tui_theme.py"


def _srgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    raw = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in raw)


def _luminance(hex_color: str) -> float:
    r, g, b = _srgb(hex_color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def check_contrast() -> list[str]:
    problems = []
    for key, floor in CONTRAST_FLOOR.items():
        color = THEME_TEXT["colors"][key]
        ratio = contrast(color, TERMINAL_BG)
        if ratio < floor:
            problems.append(f"{key} {color} on {TERMINAL_BG} = {ratio:.2f} < {floor}")
    # 工具卡上的正文也要可读。
    ratio = contrast(THEME_TEXT["colors"]["text"], THEME_TEXT["colors"]["toolCardBackground"])
    if ratio < 6.0:
        problems.append(f"text on toolCardBackground = {ratio:.2f} < 6.0")
    return problems


def write_theme() -> None:
    THEMES_DIR.mkdir(parents=True, exist_ok=True)
    THEME_PATH.write_text(json.dumps(THEME_TEXT, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"主题已写入 {THEME_PATH}")


def _profile_row(fullscreen: bool) -> str:
    flag = "true" if fullscreen else "false"
    return PROFILE_HEADER + PROFILE_ROW_TEMPLATE.format(fullscreen=flag)


def _write_profile_patch(fullscreen: bool = DEFAULT_FULLSCREEN) -> None:
    PROFILE_PATCH.parent.mkdir(parents=True, exist_ok=True)
    text = PROFILE_PATCH.read_text(encoding="utf-8") if PROFILE_PATCH.exists() else ""
    row = _profile_row(fullscreen)
    if MARKER in text:
        start = text.index(MARKER)
        # 行区块最后一行是 backend 转发行，之后是下一行 patch 的开头。
        anchor = "backend: !!js process.env.DSH_TUI_BACKEND || undefined\n"
        anchor_at = text.find(anchor, start)
        if anchor_at < 0:
            raise SystemExit(
                f"{PROFILE_PATCH} 里 {MARKER} 之后找不到 backend 转发行，"
                "文件可能被手改过；请先人工确认，脚本不会擅自覆盖"
            )
        end = anchor_at + len(anchor)
        new_text = text[:start] + row + text[end:]
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        new_text = text + "\n" + row
    PROFILE_PATCH.write_text(new_text, encoding="utf-8")
    print(f"profile patch 已更新 {PROFILE_PATCH}（fullscreen: {str(fullscreen).lower()}）")


def _dsh_package_dir() -> Path:
    """定位 dsh-tui 的产物目录。优先 `npm root -g`，再退回 nvm 常见路径。"""
    try:
        root = subprocess.run(
            ["npm", "root", "-g"], capture_output=True, text=True, check=True, timeout=30
        ).stdout.strip()
        candidate = Path(root) / "@deepseek-harness-tui" / "dsh-tui"
        if candidate.is_dir():
            return candidate
    except (OSError, subprocess.SubprocessError):
        pass
    for candidate in (
        HOME / ".nvm" / "versions" / "node",
    ):
        for node_dir in sorted(candidate.glob("v*/lib/node_modules"), reverse=True):
            pkg = node_dir / "@deepseek-harness-tui" / "dsh-tui"
            if pkg.is_dir():
                return pkg
    raise SystemExit("找不到已安装的 @deepseek-harness-tui/dsh-tui，请先安装或用 DSH_TUI_PKG 指定")


# free 段的两个硬编码来源（都没有主题键）：
# - StatusMetrics 的 FREE_SEGMENT_FILL 常量（ContextBarView 进度条本体 + ANSI 路径）；
# - StatusLine 里按品牌写死的 barColors.freeFill（运行时优先，hover 图例也用它）。
# 写入时统一用双引号，方便幂等判断。
_HEX_QUOTED = r"""['"]#[0-9A-Fa-f]{6}['"]"""
BAR_FREE_FILL_PATTERNS = (
    (Path("lib/types/screens/StatusMetrics.js"), rf"(export const FREE_SEGMENT_FILL = ){_HEX_QUOTED}"),
    (Path("lib/types/screens/StatusLine.js"), rf"(freeFill: ){_HEX_QUOTED}"),
)


def patch_bar_free_fill(pkg: Path, fill: str) -> int:
    """把自由段的兜底填充色换成 fill。

    free 段有两个来源、都没有主题键：
    - FREE_SEGMENT_FILL 常量（ContextBarView、ANSI 路径、图例的 free 块）；
    - StatusLine 里按品牌写死的 barColors.freeFill（运行时优先，覆盖常量）。
    两个都改，只改一个会出现「条是深色、图例仍是蓝色」。
    """
    fill = fill.strip()
    if not (fill.startswith("#") and len(fill) in (4, 7)):
        raise SystemExit(f"--bar-free-fill 需要 #rgb / #rrggbb，收到 {fill!r}")

    failures = []
    for rel, pattern in BAR_FREE_FILL_PATTERNS:
        target = pkg / rel
        backup = target.with_suffix(target.suffix + ".orig")
        if not target.is_file():
            failures.append(f"{rel} 不存在（包的目录结构可能已变）")
            continue
        text = target.read_text(encoding="utf-8")
        patched, count = re.subn(pattern, lambda m: f'{m.group(1)}"{fill}"', text)
        if count == 0:
            failures.append(f"{rel} 里找不到可替换的 free 段填充色（模式 {pattern}）")
            continue
        if patched == text:
            print(f"{rel}: 已是 {fill}，跳过")
            continue
        if not backup.exists():
            shutil.copy2(target, backup)
        target.write_text(patched, encoding="utf-8")
        print(f"{rel}: {count} 处 free 段填充 -> '{fill}'（备份 {backup.name}）")

    if failures:
        print("部分文件没打上补丁，包版本可能已改，请人工确认：", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        return 1
    return 0


def revert_bar(pkg: Path) -> None:
    restored = 0
    for rel in (rel for rel, _ in BAR_FREE_FILL_PATTERNS):
        target = pkg / rel
        backup = target.with_suffix(target.suffix + ".orig")
        if backup.exists():
            shutil.copy2(backup, target)
            backup.unlink()
            restored += 1
            print(f"{rel} 已还原")
    if restored == 0:
        print("没有需要还原的备份")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bar-free-fill", metavar="COLOR", help="把上下文进度条空闲段填充色换成 COLOR（需重启 dsh-tui）")
    parser.add_argument("--revert", action="store_true", help="只还原 --bar-free-fill 对 npm 包做的改动")
    parser.add_argument("--skip-profile", action="store_true", help="不改 ~/.dsh/profiles/tui/cordis.patch.yml")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--inline", action="store_true", help="profile 里写 fullscreen: false（inline 主屏；布局可能抖动）")
    group.add_argument("--fullscreen", action="store_true", help="profile 里写 fullscreen: true（默认，alt-screen 布局稳定）")
    args = parser.parse_args()
    fullscreen = not args.inline

    if args.revert:
        revert_bar(_dsh_package_dir())
        return 0

    problems = check_contrast()
    if problems:
        print("对比度不达标，未写入：", file=sys.stderr)
        for line in problems:
            print(f"  - {line}", file=sys.stderr)
        return 1

    write_theme()
    if not args.skip_profile:
        _write_profile_patch(fullscreen)

    if args.bar_free_fill:
        if patch_bar_free_fill(_dsh_package_dir(), args.bar_free_fill) != 0:
            print("bar 补丁未全部生效，见上方原因；主题/profile 部分已写入。", file=sys.stderr)
            return 1

    print("完成。重启 dsh-tui 后生效（/restart 或退出重开）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
