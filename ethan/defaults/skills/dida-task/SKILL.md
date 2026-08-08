---
name: dida-task
version: 1.0.0
description: >
  滴答清单（Dida365 / TickTick）个人 TODO 管理技能。
  覆盖任务的创建、查询、完成、更新，以及清单/标签/习惯/专注/倒数日的管理。
  用于管理用户自己的待办事项，与飞书任务（管别人）和 schedule（agent 自动执行）形成互补。
trigger: "滴答清单|滴答|记一下|帮我记|TODO|待办|我的任务|完成任务|买了什么|提醒我买|个人待办|dida|ticktick|习惯打卡|专注|番茄|倒数日"
author: Ethan Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  ethan:
    tags: [TODO, Task, Personal, Dida, TickTick]
    bins: ["dida"]
    cliHelp: "dida --help"
    channels: ["lark", "wechat", "web"]
    category: discoverable
---

# 滴答清单 (Dida Task)

管理用户**个人** TODO 任务——自己的活儿，不分 work 和 life，用 tag 区分。

## 定位（与其他任务机制的区别）

| 机制 | 谁干活 | 典型场景 |
|------|--------|---------|
| **滴答清单（本技能）** | **自己** | "提醒我周五交报告"、"记一下周末买牛奶" |
| 飞书任务（lark-task） | **别人** | "@张三周五前完成接口联调" |
| schedule（schedule_create） | **Agent** | "每天8点发日程摘要"、"每周五自动检查进度" |

## ⚡ 快速路径（优先匹配，命中即执行）

### 创建任务

用户说「记一下xxx」「提醒我周五xxx」「帮我加个待办」时：

1. 提取：`{title, due_date, priority, tags, project, content, repeat, reminders}`
2. 判断 tag：
   - 工作相关 → `tags: "work"`
   - 生活相关 → `tags: "life"`
   - 用户明确说了 tag → 用用户指定的
   - 不确定 → 默认 `work`
3. 判断 project（清单）：
   - 工作相关 → 用户工作清单（如「工作日常」）
   - 生活相关 → 用户生活清单（如「日常」）
   - 不确定 → 不传 project，任务进默认收件箱
4. 调用 `dida_task_create`
5. 回复确认：任务标题、截止时间、标签

**总计最多 2 步**：提取 → dida_task_create。

### 查询任务

用户说「我有哪些任务」「看看我的待办」时，调用 `dida_task_list`：
- 不带参数 → 列出全部未完成
- `tags: "work"` → 只看工作
- `tags: "life"` → 只看生活
- `keyword: "xxx"` → 搜索关键词

### 完成任务

用户说「xxx 做完了」「完成那个任务」时：
1. 先 `dida_task_list` 找到任务获取 project_id 和 task_id
2. 调用 `dida_task_complete(project, task_id)`

## 🛠️ 可用工具

### 任务管理（Python 工具，DIDA_ENABLED=true 时注册）

| 工具 | 用途 |
|------|------|
| `dida_project_list` | 列出所有清单/项目，获取 project_id |
| `dida_task_create` | 创建任务（title, project, content, due_date, priority, tags, reminders, repeat） |
| `dida_task_list` | 查询任务（keyword, projects, tags, status, due_from, due_to） |
| `dida_task_complete` | 完成任务（project, task_id） |

### CLI 命令（通过 shell 工具调用，功能更全）

以下命令在 Python 工具不满足时，通过 `shell` 执行 `dida` CLI：

#### 任务

```bash
# 创建任务
dida task create --title "买牛奶" --project <id> --due-date "2026-08-09T09:00:00Z" --tags "life" --priority 0 --json

# 更新任务（含子任务、重复规则等高级字段）
dida task update <taskId> --title "新标题" --priority 5 --tags "work,紧急" --items "[\"子任务1\",\"子任务2\"]" --json

# 搜索任务
dida task search "关键词" --tags "work" --status 0 --json

# 列出已完成任务
dida task completed --start-date "2026-08-01T00:00:00Z" --end-date "2026-08-31T23:59:59Z" --json

# 在清单间移动任务
dida task move --from <projectId> --to <projectId> --task <taskId> --json

# 任务评论
dida task comment list <projectId> <taskId> --json
dida task comment add <projectId> <taskId> --content "评论内容"
dida task comment delete <projectId> <taskId> <commentId>
```

#### 清单/项目

```bash
dida project list --json           # 列出所有清单
dida project get <projectId> --json
dida project data <projectId> --json  # 含任务与分组
dida project create --name "新清单" --color "#3876E4" --json
dida project update <projectId> --name "改名" --json
dida project delete <projectId>
```

#### 标签

```bash
dida tag list --json               # 列出所有标签
dida tag create --name "新标签" --color "#FF6161" --json
```

#### 习惯

```bash
dida habit list --json             # 列出所有习惯
dida habit get <habitId> --json
dida habit create --title "每日阅读" --json
dida habit update <habitId> --title "新名称" --json
dida habit checkin <habitId> --stamp 20260808 --json
dida habit checkins --start-date "2026-08-01" --end-date "2026-08-31" --json
```

#### 专注（番茄钟）

```bash
dida focus list --start-date "2026-08-01T00:00:00Z" --end-date "2026-08-08T23:59:59Z" --json
dida focus create --duration 1500 --task-id <taskId> --json
dida focus get <focusId> --json
dida focus delete <focusId> --json
```

#### 倒数日

```bash
dida countdown list --json
```

## 📋 参数说明

### 日期格式

所有日期参数使用 ISO 8601 格式：`yyyy-MM-ddTHH:mm:ssZ`

示例：
- `2026-08-09T09:00:00Z` — 8月9日上午9点
- `2026-08-09T00:00:00Z` — 8月9日全天（配合 `--all-day`）

### 优先级

| 值 | 含义 |
|----|------|
| 0 | 无 |
| 1 | 低 |
| 3 | 中 |
| 5 | 高 |

### 重复规则（RRULE）

| 规则 | 示例 |
|------|------|
| 每天 | `RRULE:FREQ=DAILY` |
| 工作日 | `RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR` |
| 每周 | `RRULE:FREQ=WEEKLY` |
| 每月 | `RRULE:FREQ=MONTHLY` |
| 每年 | `RRULE:FREQ=YEARLY` |

### 提醒触发器（reminders）

格式：`TRIGGER:-PT<n><unit>`

| 示例 | 含义 |
|------|------|
| `TRIGGER:-PT0S` | 到点提醒 |
| `TRIGGER:-PT30M` | 提前 30 分钟 |
| `TRIGGER:-PT1H` | 提前 1 小时 |
| `TRIGGER:-P1D` | 提前 1 天 |

多个提醒用逗号分隔：`TRIGGER:-PT1H,TRIGGER:-P1D`

## 🏷️ 标签体系

用户已有标签（通过 `dida tag list` 获取，可能变化）：

**主标签**（必须二选一）：
- `work` — 工作相关
- `life` — 生活相关

**life 子标签**（可选附加）：
- `学习` / `日常` / `晚间任务` / `杂事` / `心灵` / `spacetime` / `startup`

**其他**：
- `bug` / `e1` / `e2` / `e3` / `libra` / `周期提醒` / `定期重要`

创建任务时，主标签（work/life）必须带，子标签可选。

## ⚙️ 首次配置

1. 安装 CLI：`npm install -g @suibiji/dida-cli`
2. 登录：`dida auth login`（浏览器 OAuth）
   - 无浏览器环境：`dida auth token <TOKEN>`（TOKEN 在滴答清单网页版「头像 → 设置 → 账户与安全 → API 口令」创建）
3. 开启环境变量：`DIDA_ENABLED=true`

## 🔗 关联技能

| 技能 | 联动方式 |
|------|---------|
| `task-and-schedule-manager` | 统一任务路由入口——判断"自己的活"后转交本技能 |
| `lark-task` | "别人的活"走飞书任务；本技能管"自己的活" |
| `work-notes` | 工作沉淀中的待办可写入滴答清单 |
| `team-manager` | 团队管理中个人跟进事项写入滴答清单 |

## ⚠️ 约束

- **不越权**：不自动完成用户没确认的任务，不删除任务（除非用户明确要求）
- **tag 必带**：创建任务时必须带 work 或 life 标签
- **project 可选**：不确定放哪个清单时不传 project，进默认收件箱
- **CLI 超时**：dida 命令默认 30s 超时，批量操作注意分批
