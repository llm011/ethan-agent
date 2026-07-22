---
name: schedule-manager
version: 1.0.0
description: >
  定时任务与时间线管理技能。覆盖两大场景：
  ① 定时任务 — 创建/列出/暂停/删除一次性与周期性任务，支持 scene 隔离与筛选；
  ② 时间线引擎 — 用声明式 timelines.yaml 批量生成周期性多阶段任务，支持 lifecycle 管理。
trigger: "定时任务|定时提醒|每天提醒|每周提醒|设个提醒|提醒我|周期性任务|一次性任务|schedule|cron|时间线|timelines|绩效周期|OKR周期|季度汇报|配置周期|加节点|更新时间线|导出时间线|备份时间线|导入时间线|恢复时间线|同步时间线|时间线节点|截止日期|DDL|跳过阶段|推进阶段|暂停时间线|恢复时间线"
author: Ethan Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  ethan:
    tags: [Schedule, Timeline, Task, Reminder, Automation]
---

# 定时任务与时间线 (Schedule Manager)

管理两类时间对象：**定时任务**（离散的提醒/自动化）和**时间线**（声明式的周期编排）。

## ⚡ 快速路径（优先匹配，命中即执行，勿绕路）

### 创建定时任务

当用户说「提醒我明天 10 点 xxx」「每周五下午 xxx」「设个提醒」时，**不要读 references/、不要读源码**，直接调用 `schedule_create`：

1. 从消息提取 `{job_id, title, prompt, cron/interval, scene}`
2. 调用 `schedule_create`：
   - `job_id`: 简短英文/拼音
   - `title`: 中文标题
   - `prompt`: 触发时发送的内容
   - `cron`: 5 段式（min hour day month weekday），周几用 mon-sun
   - `category`: 一次性用 `one_off`，周期性用 `recurring`
   - `scene`: `work` / `life`（默认 `work`）
3. 回复确认：任务名、触发时间、所属 scene

**总计最多 2 步**：提取 → schedule_create。

### 列出定时任务

当用户说「看看定时任务」「我有哪些提醒」时，调用 `schedule_list`：

- 不带参数：列出全部
- `scene=work`：只看工作场景
- `category=one_off`：只看一次性任务

### 更新时间线节点

当用户说「更新时间线」「加个时间线节点」「截止日期是X」时：

**先判断节点类型**：

- **A. 绝对日期的一次性截止节点**（如「7/23 23:59 自评截止」）→ 用 `schedule_create` 建提醒（`category=one_off`）
- **B. 调整时间线阶段配置**（如「把集中汇总期提前到 -3w」）→ 直接编辑 `~/.ethan/{scene}/timelines.yaml`

**路径②步骤**：读 timelines.yaml → 改 phase/offset → 写回 → 提示「可说『同步时间线』立即生效」。

**🚫 禁令**：
- 不读 `references/timeline-engine.md`（SOP 细节用不到）
- 不读 `/app/ethan/scheduler/` 下任何源码
- 不 `knowledge_search`、不 `web_search`、不 `fd_find`
- 不重复读 `timelines.yaml`（路径②读一次即可）

## 🎯 两大核心场景

### 场景 A：定时任务

离散的提醒和自动化任务，通过 `schedule_create` 工具创建。

**能力**：
1. **一次性任务** (`one_off`) — 执行一次后自动删除（如：明天提醒开会）
2. **周期性任务** (`recurring`) — 按 cron 重复（如：每周五发周报）
3. **scene 隔离** — 任务归属 `work`/`life` 等 scene，互不干扰
4. **筛选查询** — `schedule_list` 支持按 scene/category 筛选

**工具**：
- `schedule_create` — 创建任务（参数：job_id, title, prompt, cron/interval_minutes, category, scene, end_date）
- `schedule_list` — 列出任务（参数：scene, category 筛选）
- `schedule_delete` — 删除任务
- `schedule_patch` — 暂停/恢复/重命名/改 prompt

### 场景 B：时间线引擎

声明式批量任务生成器，适合**多阶段周期事件**（绩效季、OKR、产品发布、团建筹备）。

**核心价值**（schedule_create 替代不了的）：
1. **批量生成** — 一条配置 = N 阶段 × M 动作 = N×M 个任务，自动生成
2. **相对时间编排** — action 用 offset 相对锚点（`-2w`/`+1d`），改锚点全调整
3. **阶段概念** — 收集→汇总→撰写→校准→沟通，每阶段不同动作
4. **lifecycle 管理** — `skip_phase`/`advance_phase`/`pause`/`resume`/`cleanup`
5. **周期轮转** — 本周期结束自动准备下一周期，无需手动重建

**使用流程**：
1. 编辑 `~/.ethan/{scene}/timelines.yaml`（配置 anchor + phases + actions）
2. 说「同步时间线」→ Engine 编译配置为具体定时任务
3. 生成的任务和手动创建的平等展示在时间轴上

**lifecycle 操作**：
| 指令 | 效果 |
|---|---|
| 「跳过这个阶段」 | 跳过当前 phase 所有未触发任务 |
| 「推进到下一阶段」 | 立即触发下一 phase 首个任务 |
| 「暂停时间线」 | 暂停该 timeline 所有任务 |
| 「恢复时间线」 | 恢复该 timeline 所有任务 |
| 「清理时间线」 | 删除该 timeline 所有任务（保留 state） |

详见 `references/timeline-engine.md`。

## 📁 数据存储

### Scene 目录隔离

数据按 scene 隔离存储在 `~/.ethan/{scene}/` 下，预置 `work` 和 `life`：

```
~/.ethan/
├── work/                    # 工作场景（默认）
│   ├── timelines.yaml       # 时间线配置（绩效周期、OKR 等）
│   ├── .timeline_state.json # 时间线运行状态（按 scene 独立）
│   └── exports/             # 导出文件
│       └── timelines-{YYYY-MM-DD}.yaml
└── life/                    # 生活/创业场景（与 work 完全隔离）
    ├── timelines.yaml       # 独立时间线
    ├── .timeline_state.json # 独立运行状态
    └── ...
```

**Scene 隔离规则**：

| 规则 | 说明 |
|---|---|
| 目录即 scene | `timelines.yaml` 放在哪个 scene 目录就属于哪个 scene |
| 运行状态隔离 | 每个 scene 独立的 `.timeline_state.json`，互不影响 |
| 预置 scene | `work` 和 `life` 首次启动自动创建 |
| 其他 scene | `health`/`study`/`finance` 按需自建目录即可被发现 |
| 定时任务 | `schedule_create` 创建时带 `scene` 字段，归属对应 scene |

### 定时任务的来源

定时任务有两种来源，在 UI 上平等展示：

1. **手动创建** — 通过 `schedule_create` 工具，带 `category`（one_off/recurring）
2. **时间线生成** — 由 timelines.yaml 编译而来，带 `source_timeline` 和 `source_phase` 标记

时间线生成的任务不是独立分类，它本质是 once 或 recurring，只是带有来源标记。

## 🏷️ 场景标签

所有任务都带 scene 字段（`work`/`life`/`health`/`study`/`finance`/`social`），用于隔离和筛选。详见 `references/scenes.md`。

## 📤 导出/导入时间线

用户说「导出时间线」「备份时间线」「导入时间线」时：

- **导出**：将某 scene 的 `timelines.yaml` + `.timeline_state.json` 打包为 YAML/JSON
- **导入**：读取导出文件，校验格式，写入指定 scene，可选 dry_run 和 merge 模式

详见 `references/timeline-engine.md` 中「导出与迁移」章节。

## ⚙️ 首次配置

1. `work` 和 `life` 目录首次启动自动创建
2. （可选）复制 `templates/timelines.yaml.example` → `~/.ethan/{scene}/timelines.yaml`，配置时间线
3. 开始使用——`schedule_create` 直接可用，时间线需配置 yaml 后同步

## 🔗 关联技能

| 技能 | 联动方式 |
|---|---|
| `team-manager` | 时间线常用于绩效周期，people 日志记录由 team-manager 管理 |
| `lark-task` | 时间线动作可创建飞书任务 |
| `lark-im` | 定时任务触发时通过飞书发送消息 |
| `lark-calendar` | 时间线可选同步到飞书日历（`sync_to_lark: true`） |

## ⚠️ 约束

- **cron 周几用名称**：APScheduler 的数字 weekday 约定与标准 cron 不同，用 `mon-sun` 而非 `1-5`
- **时间线配置需校验**：导入或手动编辑 timelines.yaml 后，Engine 会校验格式（anchor 合法、offset_start <= offset_end 等）
- **不越权**：Agent 不自行修改用户已确认的 DDL 或取消任务
