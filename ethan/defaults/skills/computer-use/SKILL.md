---
name: computer-use
trigger: "截图|操作电脑|控制桌面|鼠标点击|键盘输入|打开应用|打开软件|GUI|桌面自动化|computer use|take screenshot|click|type on screen|open app|desktop|scroll screen|drag"
description: "通过 cua-driver 控制本机 macOS 桌面：截图、鼠标点击/拖拽、键盘输入、滚动、打开 URL/应用等。需要先安装 cua-driver 后台服务。"
channels: ["web", "repl", "lark"]
fast_path: false
---

# computer-use 技能

用 `computer_use` 工具控制本机 macOS 桌面，实现截图、点击、输入、滚动、打开应用等操作。

## 前置条件

cua-driver 后台服务必须在运行。一次性安装：

```bash
curl -fsSL https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh | bash
cua-driver install    # 注册为 launchd 服务，开机自启
```

验证是否就绪：

```bash
cua-driver status
```

## 使用原则

1. **先截图，再行动**：每次操作前先调 `screenshot` 看当前屏幕状态，找到目标坐标
2. **操作后再截图验证**：点击/输入后再截一张，确认效果
3. **坐标以像素为单位**，原点在左上角。可先用 `get_screen_size` 了解屏幕尺寸

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
| 按键 | `press` | key（如 "Return", "Escape", "cmd+c"） |
| 组合键 | `hotkey` | keys（如 ["cmd", "c"]） |
| 滚动 | `scroll` | x, y, direction, clicks |
| 打开 URL/文件 | `open` | target |
| 启动应用 | `launch` | target（应用名，如 "Safari"） |

## 典型流程

### 打开浏览器并访问网址

```
1. computer_use(action="launch", target="Safari")
2. computer_use(action="screenshot")          # 确认 Safari 打开
3. computer_use(action="hotkey", keys=["cmd", "l"])  # 聚焦地址栏
4. computer_use(action="type", text="https://example.com\n")
5. computer_use(action="screenshot")          # 确认页面加载
```

### 在应用里点击某个按钮

```
1. computer_use(action="screenshot")          # 看当前屏幕，找按钮位置
2. computer_use(action="click", x=450, y=320) # 按坐标点击
3. computer_use(action="screenshot")          # 验证结果
```

### 文字输入

```
1. computer_use(action="click", x=300, y=200) # 先点击输入框
2. computer_use(action="type", text="Hello World")
3. computer_use(action="press", key="Return")
```

## 常用快捷键参考

| 效果 | key / keys |
|------|-----------|
| 回车 | `"Return"` |
| 退格 | `"BackSpace"` |
| 复制 | `["cmd", "c"]` |
| 粘贴 | `["cmd", "v"]` |
| 全选 | `["cmd", "a"]` |
| 撤销 | `["cmd", "z"]` |
| 新标签页 | `["cmd", "t"]` |
| 关闭窗口 | `["cmd", "w"]` |

## 注意事项

- cua-driver 未启动时工具会报错，提示安装命令
- 截图是 base64 图片，直接传给模型解读（需要视觉模型）
- 操作的是真实桌面，会影响用户正在使用的窗口；可先告知用户
- 坐标可能因分辨率/缩放比例变化，不同设备需重新截图定位
