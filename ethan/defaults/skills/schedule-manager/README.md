# Schedule Manager

定时任务与时间线管理技能，覆盖两大场景：**定时任务**和**时间线引擎**。

## 适用人群

需要定时提醒、周期性自动化、或多阶段周期事件编排的所有用户。

## 两大场景

### 1. 定时任务

离散的提醒和自动化，通过 `schedule_create` 创建。

**类型**：
- **一次性** (`one_off`) — 执行一次后自动删除（明天提醒开会）
- **周期性** (`recurring`) — 按 cron 重复（每周五发周报）

**特性**：
- scene 隔离（work/life/health/...），互不干扰
- `schedule_list` 支持按 scene/category 筛选
- 支持暂停/恢复/重命名/改 prompt

### 2. 时间线引擎

声明式批量任务生成器，适合**多阶段周期事件**（绩效季、OKR、产品发布）。

**核心价值**：
- 一条配置 = N 阶段 × M 动作 = N×M 个任务，自动生成
- action 用 offset 相对锚点，改锚点全调整
- 支持 lifecycle 管理（skip/advance/pause/resume/cleanup）
- 周期轮转自动重建

**定位**：timelines.yaml 是一种声明式任务表示格式，可导出/导入。生成的任务和手动创建的平等展示，不是独立分类。

## 快速开始

### 1. 安装

重启 Ethan Agent 即可，技能自动同步到 `~/.ethan/skills/`，`~/.ethan/work/` 和 `~/.ethan/life/` 目录自动创建。

### 2. 创建定时任务

直接用自然语言：

| 场景 | 示例 |
|---|---|
| 一次性提醒 | 「提醒我明天 10 点开会」 |
| 周期性提醒 | 「每周五下午 5 点发周报」 |
| 查看任务 | 「看看我工作上的定时任务」 |
| 暂停任务 | 「暂停 xxx 任务」 |

### 3. 配置时间线（可选）

编辑 `~/.ethan/{scene}/timelines.yaml`，或直接告诉 Agent：

> 「每年 7 月开始半年绩效，前置 2 周汇总提醒」

Agent 会自动解析并生成配置，然后说「同步时间线」即可生效。

### 4. 时间线 lifecycle

| 指令 | 效果 |
|---|---|
| 「跳过这个阶段」 | 跳过当前 phase 所有未触发任务 |
| 「推进到下一阶段」 | 立即触发下一 phase 首个任务 |
| 「暂停时间线」 | 暂停该 timeline 所有任务 |
| 「导出时间线」 | 备份配置和状态 |

## 数据存储

数据按 scene 隔离存储在 `~/.ethan/{scene}/` 下，预置 `work` 和 `life`：

```
~/.ethan/
├── work/                    # 工作场景（默认）
│   ├── timelines.yaml       # 时间线配置
│   ├── .timeline_state.json # 时间线运行状态（按 scene 独立）
│   └── exports/             # 导出文件
└── life/                    # 生活/创业场景（与 work 完全隔离）
    ├── timelines.yaml       # 独立时间线
    ├── .timeline_state.json # 独立运行状态
    └── ...
```

**Scene 隔离规则**：
- **目录即 scene**：`timelines.yaml` 放在哪个 scene 目录就属于哪个 scene
- **运行状态隔离**：每个 scene 独立的 `.timeline_state.json`
- **预置 scene**：`work` 和 `life` 首次启动自动创建
- **其他 scene**：`health`/`study`/`finance` 按需自建目录即可被发现
- **定时任务**：`schedule_create` 创建时带 `scene` 字段

## 定时任务的来源

定时任务有两种来源，在 UI 上平等展示：

| 来源 | 标记 | 说明 |
|---|---|---|
| 手动创建 | `category` (one_off/recurring) | 通过 `schedule_create` 工具 |
| 时间线生成 | `source_timeline` + `source_phase` | 由 timelines.yaml 编译而来 |

时间线生成的任务本质是 once 或 recurring，只是带有来源标记，不是独立分类。

## 场景标签

所有任务都带 scene 字段：`work` / `life` / `health` / `study` / `finance` / `social`

Agent 根据内容自动推断，无法推断时会询问。详见 `references/scenes.md`。

## 关联技能

| 技能 | 用途 |
|---|---|
| `team-manager` | 时间线常用于绩效周期，people 日志由 team-manager 管理 |
| `lark-task` | 时间线动作可创建飞书任务 |
| `lark-im` | 定时任务触发时通过飞书发送消息 |
| `lark-calendar` | 时间线可选同步到飞书日历（`sync_to_lark: true`） |

## 设计原则

- **timelines.yaml 是格式不是分类**：生成的任务和手动创建的平等，不占独立 category
- **声明式优于命令式**：配置描述规则，Engine 运行时计算具体日期
- **配置与状态分离**：timelines.yaml 永远有效，.timeline_state.json 可重置可迁移
- **scene 隔离**：work/life 数据完全隔离，避免信息泄露
