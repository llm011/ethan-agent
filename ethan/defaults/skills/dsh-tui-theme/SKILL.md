---
name: dsh-tui-theme
description: "修复 dsh-tui（DeepSeek harness TUI）在 Herdr/Ghostty 等终端里的配色与可读性问题：字太暗看不清（faint 字二次变暗）、hover 底部上下文进度条出现白块/蓝块、选中文字底色和字色一样导致看不清、升级 dsh-tui 后界面配色回退。当用户说「dsh 里字看不清」「dsh 白块」「dsh 选中看不清」「dsh 升级后配色又变了」「修一下 dsh tui 配色」时使用。"
trigger: "dsh|deepseek harness|白块|看不清|太暗|faint|hover|选中|进度条|上下文条|status bar|配色"
version: 0.1.0
---

# dsh-tui-theme

把 `dsh-tui` 的配色对齐到 Ghostty / Herdr 在用的 Gruvbox Material Dark，并修掉几个**没有主题键、只能改包内产物 JS** 的硬编码颜色。

> 本技能是「同一套修法」的沉淀：正文写判断路径和坑，具体命令都在 `references/`。
> **升级 dsh-tui 后的标准动作只有一条**（见下方「升级后」）。

## 先判断是哪一类问题

| 现象 | 根因 | 做法 |
|------|------|------|
| faint / 次要文字太暗，看不清 | dsh-tui 有几百处 `dimColor: true`；它会用 OSC 11 问终端底色，herdr 不回答 → 回落纯黑 → faint 被混两轮 | 跑修复脚本（主题 + 关 fullscreen） |
| hover 底部状态条出现**大白块 / 蓝块** | 上下文进度条 free 段**没有主题键**，颜色写死在包里两处 | `--bar-free-fill` 打补丁 |
| **选中文字后底色和字色一样**，字看不见 | 选中覆盖层的底色来自主题键 `selectionBg`；浅色底 + 浅色字（如蓝色斜体 `/restart`）= 看不清。注意：关掉 fullscreen（inline 模式）后**选中是终端自己画的**，dsh 的 `selectionBg` 根本不生效 | 先确认是不是 inline 模式（见下） |
| 升级 `dsh-tui` 后配色全回退 | npm 升级会覆盖被打过补丁的产物 JS；包外文件（主题、profile）不受影响 | 重跑脚本 |
| 整个界面颜色怪（不是 dsh 的锅） | Herdr 自己的主题 | 改 `~/.config/herdr-app/themes/*.json` + `layouts/*.json`，与本技能无关 |

## 升级后（最常用的一条）

```bash
cd /Volumes/SSDExt/code/life/ethan-agent
uv run scripts/setup_dsh_tui_theme.py --bar-free-fill '#3c3836'
```

脚本输出里每一行都要看：

- `已是 #3c3836，跳过` → 正常（幂等）
- `部分文件没打上补丁，包版本可能已改` → **必须处理**：新版改了结构，脚本退出码非 0。把报错贴给用户，然后按下文「硬编码色块又变了怎么找」重新定位。
- 两条路径里如果仓库不在 `/Volumes/SSDExt/...`，先 `pwd` 确认在 ethan-agent 主仓库（`git rev-parse --show-toplevel`），别在旧拷贝里跑。

跑完提醒用户：`/restart` 或退出重开 dsh 会话才生效。

## 三类修复的原理（判断时用）

### 1. faint 字变暗 → 主题 + inline 模式

- 主题文件：`~/.dsh-tui/themes/gruvbox-material-dark.json`，当前生效主题在 `~/.dsh-tui/theme.json`（`{"theme": "..."}`）。
- 判断是否生效：`cat ~/.dsh-tui/theme.json`，再 `cat ~/.dsh-tui/settings.json` 看 `fullscreen` 是否为 `false`。
- **`/theme` 命令的自动补全按回车不会提交**，不要靠它切换；持久化偏好 + 重启最稳。
- inline 模式（`fullscreen: false`）下 dsh 不跑 OSC 11，faint 交给终端混，可读性靠主题的高对比色板兜住。
- 脚本每次都会重写过 `cordis.patch.yml` 的 `dsh-tui` 块（幂等，带 marker），不要手动编辑那块。

### 2. 进度条 free 段白/蓝块 → 两处硬编码，必须都改

**没有主题键**。两个来源：

| 文件（相对包根） | 位置 | 作用 |
|---|---|---|
| `lib/types/screens/StatusMetrics.js` | `export const FREE_SEGMENT_FILL = "#…"` | 进度条本体、ANSI 路径、图例的 free 块 |
| `lib/types/screens/StatusLine.js` | `barColors` 里 `freeFill: "#…"` | **运行时优先，覆盖常量**；hover 图例也用它 |

只改一个的症状：条是深色、图例仍然是蓝色。之前的实测顺序是「以为只有常量 → 改完还是白/蓝 → 截图像素采样发现整条是 `#2E3440`（StatusLine 的品牌色）」——所以**遇到改完没生效，先像素采样看实际颜色值，再 grep 这个值**。

### 3. 选中看不清 → 先分清谁在画

- **inline 模式（当前配置）**：alt-screen 关闭，选中是 **终端**（Herdr/Ghostty）画的，dsh 的 `selectionBg` 无关。此时「底色≈字色」是终端配色问题，改 Herdr 主题 `selection` / Ghostty 的 selection 颜色；`/Volumes/...` 仓库里的脚本改不到它。
- **fullscreen 模式**：dsh 自己画选中，颜色来自主题键 `selectionBg`（`lib/types/ink/screen.js` 的 `withSelectionBg`，替换背景、保留前景）。要改就改主题 JSON 的 `selectionBg`，**不用打补丁**。
- 排错捷径：选中一块含彩色文字的区域，像素采样选中框底色；如果底色跟 dsh 主题里的 `selectionBg` 一致 → dsh 在画；如果跟 Herdr 主题的 `selection` 一致 → 终端在画。

## 硬编码色块又变了怎么找（新版结构变化时）

```bash
PKG=$(npm root -g)/@deepseek-harness-tui/dsh-tui
grep -rn "FREE_SEGMENT_FILL\|freeFill" "$PKG/lib"
grep -rn "selectionBg" "$PKG/lib" | grep -v '\.d\.ts'
grep -n "selectionBg\|选中" "$PKG/guide/dsh-tui-guide/themes.md"   # 官方主题键文档
```

- 官方主题键文档在包里：`$PKG/guide/dsh-tui-guide/themes.md`（中文）/ `themes.en.md`。**先查有没有主题键可用**，有就用主题 JSON，别打补丁。
- 只有确认「没有主题键」时才改包内 JS，并且必须保持脚本的三个约定：改动前存 `.orig` 备份、写双引号便于幂等、`--revert` 能还原。
- 包路径判断：`npm root -g` 优先，退回 `~/.nvm/versions/node/v*/lib/node_modules`。

## 约束

- **不要在 `/Volumes/SSDExt/code/life/buddy-proxy` 或其它仓库里改**；脚本只写用户 home 下的 dsh 配置 + 当前 npm 全局包。
- 改完必须实际跑一遍脚本并看**退出码**（`echo $?`），不能只看输出文字。
- 用户问「升级后会不会丢」时如实回答：主题和 profile 在包外不丢；包内 JS 补丁会丢，重跑一条命令即可。
- 需要更多细节（完整修复流程、验证步骤、历史 bug 记录）时用 `skill_read` 读 `references/dsh-tui-colors.md`。
