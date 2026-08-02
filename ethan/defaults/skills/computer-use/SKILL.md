---
name: computer-use
trigger: "截图|操作电脑|控制桌面|鼠标点击|键盘输入|打开应用|打开软件|GUI|桌面自动化|computer use|take screenshot|click|type on screen|open app|desktop|scroll screen|drag"
description: "通过 cua-driver 控制本机 macOS 桌面：截图、鼠标点击/拖拽、键盘输入、滚动、打开 URL/应用等。cua-driver 未安装时自动帮用户装好。"
channels: ["web", "repl", "lark"]
fast_path: false
---

# computer-use 技能

用 `computer_use` 工具控制本机 macOS 桌面。

## 第一步：确认环境就绪

**Docker 容器环境（存在 /.dockerenv）跳过此步**——cua-driver 运行在宿主机上，
通过 cua-bridge 桥接访问，容器内没有也不需要 cua-driver 命令。直接调用 `computer_use` 即可。

**宿主机原生环境**，先检查 cua-driver 是否在运行：

```bash
cua-driver status
```

- **正常输出**（含 running/active）→ 直接跳到操作部分
- **command not found** 或错误 → 执行以下安装命令（需要用户同意），完成后再继续：

```bash
curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh | bash && cua-driver install
```

安装完毕后验证：`cua-driver status`

## ⚠️ 关键限制：Electron 应用必须前台化

**这是最重要的规则，违反它会导致操作静默失败（返回 ok=True 但实际没生效）。**

### 根因

macOS 的 `CGEventPostToPid`（cua-driver 带 pid 的键盘事件投递机制）对 **Electron 后台窗口**无效：
- 事件被 Electron 的多进程架构静默丢弃
- `hotkey`/`press_key`/`type` 都返回 `ok=True`，但界面没有任何变化
- 这是 macOS + Chromium 的固有限制，不是工具 bug

### 哪些是 Electron 应用

VS Code、TRAE、TRAE Work、Slack、Discord、飞书/Lark（部分）、Cursor、Obsidian、Notion 等。
**判断方法**：应用进程名含 "Helper" 或 `app_name` 在下列列表中，按 Electron 处理。

### 正确做法（必读）

操作 Electron 应用时，**必须先 `activate_app` 前台化，再操作，最后切回原窗口**：

```
1. activate_app(target="TRAE Work CN")   # 前台化（必须）
2. sleep 1~1.5s                           # 等待窗口真正前台化
3. click(x, y)                            # 点击输入框定位光标
4. paste_text(text="...")                 # 粘贴（自动备份+恢复剪贴板）
5. press_key(key="return")                # 发送
```

**不要尝试用 `set_focus(pid)` + 后台 `hotkey` 的组合**——对 Electron 应用无效。
`set_focus` 只设置 CGEvent 投递目标 pid，不改变视觉前台，对 Electron 后台窗口的键盘事件无效。

### 原生应用 vs Electron 应用对照

| 应用类型 | 示例 | 后台操作 | 前台化 |
|---------|------|---------|--------|
| 原生 | TextEdit, Notes, Safari | ✅ `set_focus` + `type` 可后台 | 不需要 |
| Electron | TRAE, VS Code, Slack | ❌ 后台键盘事件被丢弃 | ✅ 必须 `activate_app` |

## 使用原则

1. **先截图，再行动**：每次操作前先调 `screenshot` 看当前屏幕，找准坐标
2. **操作后再截图验证**：点击/输入后截一张确认效果
3. **坐标以像素为单位**，原点左上角。先用 `get_screen_size` 了解屏幕尺寸
4. **Electron 应用必须前台化**：见上方"关键限制"章节
5. **输入文字优先用 paste_text**：`type` 用 CGEventPostToPid 对 Electron 无效；`paste_text`（pbcopy + cmd+v）更可靠

## 操作速查

### 基础操作

| 操作 | action | 必填参数 | 备注 |
|------|--------|----------|------|
| 截图 | `screenshot` | — | 操作前后都截一张 |
| 获取屏幕尺寸 | `get_screen_size` | — | — |
| 左键点击 | `click` | x, y | 可带 pid 定位后台窗口 |
| 双击 | `double_click` | x, y | — |
| 右键点击 | `right_click` | x, y | — |
| 移动光标 | `move` | x, y | — |
| 拖拽 | `drag` | x, y, end_x, end_y | — |
| 滚动 | `scroll` | x, y, direction, clicks | direction: up/down |
| 翻页 | `page` | direction | direction: up/down |
| 缩放截图 | `zoom` | x, y, end_x, end_y | 截取区域并放大 |

### 键盘输入

| 操作 | action | 必填参数 | 备注 |
|------|--------|----------|------|
| 输入文字 | `type` | text | **原生应用用这个** |
| 粘贴文字 | `paste_text` | text | **Electron 应用用这个**（pbcopy+cmd+v，自动备份并恢复原剪贴板，不污染） |
| 按键 | `press` | key | 如 "return", "escape", "delete" |
| 组合键 | `hotkey` | keys | 如 ["cmd", "c"] |

**注意**：cua-driver 的按键方法名是 `press_key`（不是 `press`）。工具内部已做映射，调 `computer_use(action="press")` 即可。

### 窗口管理

| 操作 | action | 必填参数 | 备注 |
|------|--------|----------|------|
| 列出窗口 | `list_windows` | — | 可用 title_filter 过滤 |
| 列出应用 | `list_apps` | — | 可用 title_filter 过滤 |
| 设置焦点 | `set_focus` | pid | 设置 CGEvent 投递目标（仅原生应用有效，Electron 必须用 activate_app） |
| 激活应用 | `activate_app` | target | **osascript activate（macOS 专用），Electron 应用前台化必用** |
| 隐藏应用 | `hide_app` | — | cmd+h |
| 最小化窗口 | `minimize_window` | — | cmd+m |
| 启动应用 | `launch` | target | — |
| 打开 URL | `open` | target | 启动 Safari + 输入 URL |
| 杀掉应用 | `kill_app` | pid | — |

**注意**：macOS 下 cua-driver 的 `bring_to_front` 不可用，前台化窗口必须用 `activate_app`（走 osascript `tell application "X" to activate`）。

### AX 辅助

| 操作 | action | 必填参数 | 备注 |
|------|--------|----------|------|
| 获取 AX 树 | `get_accessibility_tree` | — | Electron 应用通常只暴露菜单栏，内容区缺失 |
| 设置元素值 | `set_value` | element_token, value | AX 方式赋值 |
| 获取光标位置 | `get_cursor_position` | — | — |
| 检查权限 | `check_permissions` | — | accessibility + screen_recording |

## 典型流程

### 原生应用（TextEdit, Notes 等）——可后台操作

```
computer_use(action="list_windows", title_filter="TextEdit")
computer_use(action="set_focus", pid=12345)
computer_use(action="click", x=500, y=500, pid=12345)
computer_use(action="type", text="Hello World", pid=12345)
```

### Electron 应用（TRAE, VS Code, Slack 等）——必须前台化

```
# 1. 找到窗口 pid
computer_use(action="list_windows", title_filter="TRAE Work")

# 2. 前台化（必须！后台操作对 Electron 无效）
computer_use(action="activate_app", target="TRAE Work CN")
# 等待 1~1.5s 让窗口真正前台化

# 3. 点击输入框定位光标
computer_use(action="click", x=900, y=1000, pid=88851)

# 4. 粘贴文字（自动备份+恢复剪贴板）
computer_use(action="paste_text", text="Hello from AI")

# 5. 发送
computer_use(action="press", key="return", pid=88851)

# 6.（可选）切回原窗口
computer_use(action="activate_app", target="原应用名")
```

### 打开浏览器访问网址

```
computer_use(action="launch", target="Safari")
computer_use(action="screenshot")
computer_use(action="hotkey", keys=["cmd", "l"])
computer_use(action="type", text="https://example.com\n")
```

## 常用快捷键

| 效果 | keys |
|------|------|
| 复制 | `["cmd", "c"]` |
| 粘贴 | `["cmd", "v"]` |
| 全选 | `["cmd", "a"]` |
| 新标签页 | `["cmd", "t"]` |
| 关闭窗口 | `["cmd", "w"]` |

## 注意

- **type vs paste_text**：`type` 用 CGEventPostToPid，对 Electron 后台窗口无效（返回 ok=True 但不输入）。Electron 应用必须用 `paste_text` + `activate_app`。
- **activate_app vs set_focus**：`set_focus` 只设置 CGEvent 投递目标 pid，不前台化，对 Electron 无效；`activate_app` 真正前台化窗口（osascript），Electron 必须用这个。
- **paste_text 不污染剪贴板**：内部自动 备份→写入→cmd+v→恢复。
- 截图需要视觉模型（如 claude-sonnet）才能解读图片内容
- 操作的是真实桌面，执行前告知用户可能影响当前窗口
- 坐标因分辨率/缩放不同而变化，每次操作前重新截图定位
- 截图失败时（`screenshot` 带 pid 返回空），尝试不带 pid 截全屏，或用 `get_window_state(pid, window_id)` 获取窗口截图

## 踩坑记录

1. **cua-driver 按键方法名是 `press_key` 不是 `press`**：工具内部已映射，调 `computer_use(action="press")` 即可。直接调 bridge 时用 `press_key`。
2. **cua-driver 所有操作都要求带 pid**：不带 pid 会返回 "Missing required integer field: pid"。`list_windows`/`get_screen_size`/`activate_app`/`set_clipboard`/`get_clipboard`/`restore_clipboard` 等管理类方法除外。
3. **Electron 后台窗口键盘事件被静默丢弃**：`hotkey`/`press_key`/`type` 带 pid 时返回 ok=True 但事件不到达 Electron 后台窗口。必须 `activate_app` 前台化。
4. **macOS 下 cua-driver 的 bring_to_front 不可用**：前台化窗口必须用 `activate_app`（osascript）。
5. **activate_app 超时**：osascript 激活应用可能较慢，bridge 端超时设为 10s，调用后建议 sleep 1~1.5s。
