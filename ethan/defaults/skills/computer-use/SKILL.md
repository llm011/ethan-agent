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

**调用任何 computer_use 操作前，先检查 cua-driver 是否在运行：**

```bash
cua-driver status
```

- **正常输出**（含 running/active）→ 直接跳到操作部分
- **command not found** 或错误 → 执行以下安装命令（需要用户同意），完成后再继续：

```bash
curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh | bash && cua-driver install
```

安装完毕后验证：`cua-driver status`

## 使用原则

1. **先截图，再行动**：每次操作前先调 `screenshot` 看当前屏幕，找准坐标
2. **操作后再截图验证**：点击/输入后截一张确认效果
3. **坐标以像素为单位**，原点左上角。先用 `get_screen_size` 了解屏幕尺寸

## 操作速查

| 操作 | action | 必填参数 |
|------|--------|----------|
| 截图 | `screenshot` | — |
| 获取屏幕尺寸 | `get_screen_size` | — |
| 左键点击 | `click` | x, y |
| 双击 | `double_click` | x, y |
| 右键点击 | `right_click` | x, y |
| 移动光标 | `move` | x, y |
| 拖拽 | `drag` | x, y, end_x, end_y |
| 输入文字 | `type` | text |
| 按键 | `press` | key（如 "Return", "Escape"） |
| 组合键 | `hotkey` | keys（如 ["cmd", "c"]） |
| 滚动 | `scroll` | x, y, direction, clicks |
| 打开 URL/文件 | `open` | target |
| 启动应用 | `launch` | target（应用名，如 "Safari"） |

## 典型流程

```
# 打开浏览器访问网址
computer_use(action="launch", target="Safari")
computer_use(action="screenshot")                         # 确认已打开
computer_use(action="hotkey", keys=["cmd", "l"])          # 聚焦地址栏
computer_use(action="type", text="https://example.com\n")
computer_use(action="screenshot")                         # 确认加载
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

- 截图需要视觉模型（如 claude-sonnet）才能解读图片内容
- 操作的是真实桌面，执行前告知用户可能影响当前窗口
- 坐标因分辨率/缩放不同而变化，每次操作前重新截图定位

