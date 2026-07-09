# macOS 应用自动化

## 触发关键词
滴答清单, 提醒事项, 日历, 备忘录, 待办, 创建会议, 新建笔记, AppleScript, osascript, 自动化

## 核心原则

macOS 应用自动化通过 `osascript` (AppleScript/JXA) 执行。以下是确保成功的关键规则：

### 1. 权限前置检查

在执行任何 `osascript -e 'tell application "XXX"'` 之前，**必须先检查自动化权限**：

```bash
# 检查是否有 Accessibility 权限（Automation 权限无法直接查询）
# 先尝试一个无副作用的命令来探测权限
osascript -e 'tell application "System Events" to return name of first process'
```

如果返回错误（如 "not allowed assistive access"），说明缺少权限，应：
1. 告知用户需要在 系统设置 → 隐私与安全性 → 自动化 中授权
2. **不要重复尝试**同一个会弹权限框的命令

### 2. 超时安全

- shell 工具默认 30 秒超时。对于可能弹框等待用户操作的命令，**设置较短超时**（如 `timeout: 10`）
- 如果命令超时，说明可能卡在权限弹框，直接告知用户检查权限，不要重试

### 3. 推荐的 AppleScript 模式

#### 提醒事项 (Reminders)
```bash
osascript -e '
tell application "Reminders"
  set targetList to list "工作"
  tell targetList
    make new reminder with properties {name:"买菜", due date:date "2026-07-11 09:00:00"}
  end tell
end tell'
```

#### 日历 (Calendar)
```bash
osascript -e '
tell application "Calendar"
  tell calendar "工作"
    set startDate to current date
    set hours of startDate to 14
    set minutes of startDate to 0
    set endDate to startDate + 1 * hours
    make new event with properties {summary:"技术评审会", start date:startDate, end date:endDate}
  end tell
end tell'
```

#### 备忘录 (Notes)
```bash
osascript -e '
tell application "Notes"
  tell account "iCloud"
    make new note at folder "Notes" with properties {name:"会议纪要", body:"<h1>会议纪要</h1><p>内容...</p>"}
  end tell
end tell'
```

#### 滴答清单 (TickTick) — 无原生 AppleScript 支持
滴答清单**不支持** AppleScript。替代方案（按优先级）：
1. **URL Scheme**：`open "ticktick://x-callback-url/add?title=买菜&dueDate=2026-07-11"`
2. **快捷指令**：`shortcuts run "添加滴答任务" --input-type text --input "买菜"`（需预建快捷指令）
3. **Web API**：通过 shell curl 调用滴答清单 Open API（需 token）

### 4. 常见陷阱

| 问题 | 原因 | 解决 |
|------|------|------|
| osascript 挂起 | 权限弹框未处理 | 缩短 timeout + 提示用户授权 |
| "application not running" | App 未启动 | 先 `open -a "AppName"` 再操作 |
| 日期格式错误 | 本地化差异 | 用 `current date` 运算而非硬编码字符串 |
| 列表/日历不存在 | 用户环境不同 | 先查询可用列表再操作 |

### 5. 降级策略

如果 AppleScript 失败：
1. 尝试 **Shortcuts CLI**：`shortcuts run "xxx"`
2. 尝试 **open URL scheme**：`open "appname://..."`
3. 告知用户具体失败原因，建议手动操作

## 工具依赖
activate_tools: shell
