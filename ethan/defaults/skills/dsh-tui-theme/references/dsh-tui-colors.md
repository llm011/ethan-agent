# dsh-tui 配色修复：完整细节

本文是 `dsh-tui-theme` 技能的参考文档，记录修复脚本的行为、验证方法、已踩过的坑。命令以 macOS + nvm + zsh 为准。

## 环境事实（实践过的版本）

| 项 | 值 |
|---|---|
| dsh-tui | v0.19.0，`npm i -g @deepseek-harness-tui/dsh-tui` |
| 包根 | `$(npm root -g)/@deepseek-harness-tui/dsh-tui`（本机 `/Users/<user>/.nvm/versions/node/v24.22.1/lib/node_modules/…`） |
| 可执行 | `<nvm bin>/dsh tui` |
| 主题目录 | `~/.dsh-tui/themes/*.json` |
| 当前主题 | `~/.dsh-tui/theme.json` → `{"theme": "<name>"}` |
| 偏好 | `~/.dsh-tui/settings.json` → `values.fullscreen` / `values.lang` |
| profile patch | `~/.dsh/profiles/tui/cordis.patch.yml` |
| 主题键文档 | `<包根>/guide/dsh-tui-guide/themes.md`（中文）、`themes.en.md` |
| 注意 | 另一个包 `@deepseek-ai/dsh@0.2.2-rc.1` 与本技能**无关** |

## 修复脚本 `scripts/setup_dsh_tui_theme.py`

在 ethan-agent 仓库里（main 已含）。三件事，全部幂等：

```bash
uv run scripts/setup_dsh_tui_theme.py                          # A + B
uv run scripts/setup_dsh_tui_theme.py --bar-free-fill '#3c3836' # A + B + C
uv run scripts/setup_dsh_tui_theme.py --revert                  # 只还原 C
uv run scripts/setup_dsh_tui_theme.py --skip-profile            # 不动 cordis.patch.yml
echo $?                                                          # 必须看退出码
```

### A. 主题

写 `~/.dsh-tui/themes/gruvbox-material-dark.json`：`base: dark` + Gruvbox 覆盖色。

- 每条覆盖要过对比度门槛（正文 ≥ 4.5、faint 字 ≥ 4.0，`text` on `toolCardBackground` ≥ 6.0），不达标**直接报错退出、不写半成品**。
- 对比度按 `TERMINAL_BG = #1d2021` 算（Herdr pane 的 canvas 底色），不是 Ghostty 的 `#282828`。

### B. profile patch

重写 `~/.dsh/profiles/tui/cordis.patch.yml` 里带 marker 的 `- id: dsh-tui` 块，核心是 `fullscreen: false`。

- patch 语义是**整块替换**，所以块里其余键必须用 `!!js` 原样转发（`provider` / `terminalImages` / `effort` / `preset` / `workspace` / `sessionId` / `backend`），漏写就丢配置。
- 定位方式：从 marker 到最后一行 `backend: !!js process.env.DSH_TUI_BACKEND || undefined`。找不到锚点会 `SystemExit` 并提示「文件可能被手改过」，不会覆盖。

### C. bar free 段补丁

见正文「两处硬编码」。要点：

- 两个文件都改：`StatusMetrics.js`（常量）+ `StatusLine.js`（`barColors.freeFill`，运行时优先）。
- 写双引号 `"#3c3836"`，正则 `['"]#[0-9A-Fa-f]{6}['"]` 引号无关，重跑时 `patched == text` → 打印「已是 …，跳过」。
- 首次改动前 `shutil.copy2` 存 `*.orig`；`--revert` 从 `.orig` 还原并删备份。
- 目标文件不存在或锚点找不到 → 记入 failures，函数返回 1，`main` 返回非 0 退出码。
- `#3c3836` 和输入框底色 `#32302f` 视觉上几乎一样，这是「看起来没有块」的原因；想更明显可换 `#45403d`。

## 验证清单（改完必做）

1. `python3 -c "import ast;ast.parse(open('scripts/setup_dsh_tui_theme.py').read())"` — 语法
2. 跑脚本，**看全输出**：正常路径是「主题已写入 / profile patch 已更新 / 两处已是 … 跳过 / 完成」+ `exit=0`
3. 包内实际值：`grep -n 'FREE_SEGMENT_FILL\|freeFill' <包根>/lib/types/screens/{StatusMetrics,StatusLine}.js`
4. 主题生效：`cat ~/.dsh-tui/theme.json`、`grep fullscreen ~/.dsh-tui/settings.json`
5. 重启 dsh（`/restart` 或重开 tab）后让用户自己 hover 验证
6. 窄窗口里进度条可能整条不显示（`barWidth >= 14` 才画 + inline 截断），别误判成补丁没生效

模拟「新版结构变化」：临时把 `BAR_FREE_FILL_PATTERNS` 换成不存在的文件/锚点，确认返回 1 且不吐栈。

## 已踩过的坑

| 坑 | 现象 | 结论 |
|---|---|---|
| 只改常量 | 条深了、图例仍蓝 | `StatusLine.barColors.freeFill` 运行时覆盖常量 |
| ContextBarView.js 也去 grep `#E8E8E8` | 找不到 → 误报「包版本已改」 | 它 import 常量，不含字面量 |
| 正则要求单引号+分号 | 第一次补丁后重跑报「找不到」 | 用引号无关 `_HEX_QUOTED`，写成双引号 |
| 脚本里失败 return 但 main 不接 | 升级后静默 exit 0 | 已修：`patch_bar_free_fill` 返回 int，main 透传 |
| `hc list --json` | 不支持 | 用 `hc ls` |
| `/theme` 回车 | 不提交 | 改 `theme.json` + 重启 |
| OSC 11 探测 | herdr 不回答 → 回落纯黑 → faint 双重变暗 | 关 fullscreen（inline）绕开 |
| inline 模式选中 | 选中由终端画，主题 `selectionBg` 不生效 | 查 Herdr 主题 `selection` / Ghostty 配置 |

## 升级后为什么会丢 / 怎么不丢

- 主题 JSON、`theme.json`、`settings.json`、`cordis.patch.yml` 都在 **home 下**，npm 升级不动 → 不丢。
- `lib/types/screens/*.js` 属于 npm 包产物 → `npm i -g` 覆盖 → 丢，重跑 `--bar-free-fill`。
- 想彻底不丢，只能等上游暴露主题键（free 段目前没有）；在此之前补丁脚本是唯一手段。

## 与 Herdr 的关系

Herdr 自己的配色在 `~/.config/herdr-app/themes/<name>.json` 与 `~/.config/herdr-app/layouts/<name>.json`（`theme.dark/light` 指定）。终端层（选中、光标、滚动条）的颜色归 Herdr/Ghostty，不归 dsh。**不要**改 Herdr 的 `AGENTS.md`、`*.d.ts`、`frame/`、`layouts/.state/`、`shared.json`、`view.json`、`installed.json`。
