---
name: task-and-schedule-manager
version: 2.0.0
description: >
  统一任务与日程管理入口。当用户说"提醒我"、"待办"、"创建任务"时，先判断谁干活，再路由到对应机制：
  ① 自己的活 → 滴答清单（dida-task，DIDA_ENABLED=true 时优先）；
  ② 别人的活 → 飞书任务（lark-task）；
  ③ Agent 的活 → schedule_create（定时任务）；
  ④ 多阶段周期 → 时间线引擎（timelines.yaml）。
  本技能同时承载定时任务管理和时间线引擎两大核心能力。
trigger: "提醒我|待办|创建任务|设个提醒|记一下|帮我记|定时任务|定时提醒|每天提醒|每周提醒|周期性任务|一次性任务|分配任务|schedule|cron|时间线|timelines|绩效周期|OKR周期|季度汇报|配置周期|加节点|更新时间线|导出时间线|备份时间线|导入时间线|恢复时间线|同步时间线|时间线节点|截止日期|DDL|跳过阶段|推进阶段|暂停时间线|恢复时间线|时间信号|识别时间|电话里说|通话记录|妙记|会议纪要|到点提醒|交付提醒|巡检|例行|我的任务|看看任务"
author: Ethan Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  ethan:
    tags: [Schedule, Timeline, Task, Reminder, Automation, Routing]
    fast_path: true
---

# 任务与日程管理 (Task & Schedule Manager)

**统一路由入口**——用户说任何与"任务/待办/提醒/日程"相关的话，先到这里判断路由，再分流到对应机制。

## ⚡ 快速路由（最优先，命中即执行）

当用户说「提醒我」「待办」「创建任务」「记一下」等词时，**先判断谁干活**：

| 路径 | 条件 | 去哪 | 工具 |
|------|------|------|------|
| **A. 自己的活** | 用户自己的待办/提醒，没有@别人 | → `dida-task` 技能 | `dida_task_create`（DIDA_ENABLED=true 时） |
| **B. 别人的活** | 消息里有@某人、或"分配给XX"、"让XX做" | → `lark-task` 技能 | `lark-cli task +create` |
| **C. Agent 的活** | 需要到点后 agent 自动处理（查日历、生成摘要、跑分析） | → `schedule_create` | 本技能直接执行 |
| **D. 多阶段周期** | 绩效季、OKR、产品发布等多阶段编排 | → 时间线引擎 | 本技能直接执行 |

### 路由判断规则

1. **有@人名/分配语气** → 路径 B（飞书任务）
2. **需要 agent 到点干活** → 路径 C（schedule_create）
3. **多阶段周期事件** → 路径 D（时间线引擎）
4. **以上都不是，就是用户自己的待办** → 路径 A（滴答清单）
5. **不确定时** → 问用户："需要我到点自动处理，还是只设个待办提醒你？"

### 路径 A：自己的活 → 滴答清单

用户说「记一下周五交报告」「提醒我买牛奶」「帮我加个待办」时，转交 `dida-task` 技能：

1. `skill_read dida-task` 获取详细指引
2. 按 dida-task 的快速路径执行

**快速直接调用**（不需读 skill，DIDA_ENABLED=true 时）：
- 创建：`dida_task_create(title, project, due_date, tags, priority, ...)`
  - tag 必带 `work` 或 `life`
  - priority 按用户偏好规则（详见 dida-task 技能「优先级判定」）：
    - 一般任务 → `1`（低，默认）
    - 无关紧要/可做可不做/不确定 → `0`（不设）
    - 很重要、要引起重视 → `3`（中，不要太多）
    - 非常紧急、不做后果严重 → `5`（高，不要随便用）
- 查询：`dida_task_list(keyword, tags, status, ...)`
- 完成：`dida_task_complete(project, task_id)`

### 路径 B：别人的活 → 飞书任务

用户说「@张三周五前完成接口」「分配给XX」时，转交 `lark-task` 技能：

1. `skill_read lark-task` 获取详细指引
2. 按 lark-task 的快速路径执行

### 路径 C：Agent 的活 → schedule_create

用户说「每天8点发日程摘要」「每周五自动检查进度」时，**直接调用 `schedule_create`**：

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

### 路径 D：多阶段周期 → 时间线引擎

用户说「绩效季配置」「OKR时间线」「产品发布编排」时，见下方[时间线引擎](#场景-b时间线引擎)章节。

---

## 🚫 禁令

- 不读 `references/` 除非用户明确要时间线引擎的高级操作
- 不读 `/app/ethan/scheduler/` 下任何源码
- 不 `knowledge_search`、不 `web_search`、不 `fd_find`
- 路径 A/B 转交后由对应技能处理，本技能不再重复执行

---

## 🎯 核心场景 C：定时任务

离散的提醒和自动化任务，通过 `schedule_create` 工具创建。

### 创建定时任务

当用户说「提醒我明天 10 点 xxx」「每周五下午 xxx」「设个提醒」且判断为路径 C 时：

1. 从消息提取 `{job_id, title, prompt, cron/interval, scene}`
2. 调用 `schedule_create`
3. 回复确认

### 列出定时任务

当用户说「看看定时任务」「我有哪些提醒」时，调用 `schedule_list`：

- 不带参数：列出全部
- `scene=work`：只看工作场景
- `category=one_off`：只看一次性任务

### 定时任务能力

1. **一次性任务** (`one_off`) — 执行一次后自动删除（如：明天提醒开会）
2. **周期性任务** (`recurring`) — 按 cron 重复（如：每周五发周报）
3. **scene 隔离** — 任务归属 `work`/`life` 等 scene，互不干扰
4. **筛选查询** — `schedule_list` 支持按 scene/category 筛选

**工具**：
- `schedule_create` — 创建任务（参数：job_id, title, prompt, cron/interval_minutes, category, scene, end_date）
- `schedule_list` — 列出任务（参数：scene, category 筛选）
- `schedule_delete` — 删除任务
- `schedule_patch` — 暂停/恢复/重命名/改 prompt

### 定时信号识别（从任意内容里抠时间节点）

当对话/电话/妙记/文档/口述里出现时间节点或待办信号时（哪怕用户主要意图是别的），主动识别并列候选：

1. 抽取所有候选信号（时间表达式、解析后日期、事件、来源、置信度）
2. 列出候选清单给用户看
3. 用户回编号确认
4. 对确认的按路由规则判断走路径 A（滴答）还是路径 C（schedule）
5. 回复已创建的提醒

**必须先确认再创建**，模糊时间先问。people-kb / work-notes / team-manager 发现时间信号都转交到这条路径。详见 `references/signal-recognition.md`。

---

## 🎯 核心场景 D：时间线引擎

声明式批量任务生成器，适合**多阶段周期事件**（绩效季、OKR、产品发布、团建筹备）。

**核心价值**（schedule_create 替代不了的）：
1. **批量生成** — 一条配置 = N 阶段 × M 动作 = N×M 个任务，自动生成
2. **相对时间编排** — action 用 offset 相对锚点（`-2w`/`+1d`），改锚点全调整
3. **阶段概念** — 收集→汇总→撰写→校准→沟通，每阶段不同动作
4. **lifecycle 管理** — `skip_phase`/`advance_phase`/`pause`/`resume`/`cleanup`
5. **周期轮转** — 本周期结束自动准备下一周期，无需手动重建

### 更新时间线节点

当用户说「更新时间线」「加个时间线节点」「截止日期是X」时：

**先判断节点类型**：
- **A. 绝对日期的一次性截止节点**（如「7/23 23:59 自评截止」）→ 用 `schedule_create` 建提醒（`category=one_off`）
- **B. 调整时间线阶段配置**（如「把集中汇总期提前到 -3w」）→ 直接编辑 `~/.ethan/{scene}/timelines.yaml`

**路径 B 步骤**：读 timelines.yaml → 改 phase/offset → 写回 → 提示「可说『同步时间线』立即生效」。

### 使用流程

1. 编辑 `~/.ethan/{scene}/timelines.yaml`（配置 anchor + phases + actions）
2. 说「同步时间线」→ Engine 编译配置为具体定时任务
3. 生成的任务和手动创建的平等展示在时间轴上

### lifecycle 操作

| 指令 | 效果 |
|---|---|
| 「跳过这个阶段」 | 跳过当前 phase 所有未触发任务 |
| 「推进到下一阶段」 | 立即触发下一 phase 首个任务 |
| 「暂停时间线」 | 暂停该 timeline 所有任务 |
| 「恢复时间线」 | 恢复该 timeline 所有任务 |
| 「清理时间线」 | 删除该 timeline 所有任务（保留 state） |

详见 `references/timeline-engine.md`。

---

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

## 🏷️ 场景标签

所有 schedule 任务都带 scene 字段（`work`/`life`/`health`/`study`/`finance`/`social`），用于隔离和筛选。详见 `references/scenes.md`。

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
| `dida-task` | 路径 A——用户自己的待办转交此技能处理（DIDA_ENABLED=true） |
| `lark-task` | 路径 B——@别人的任务转交此技能处理 |
| `team-manager` | 时间线常用于绩效周期；委派节点提醒、群扫描、CR 周度汇总的定时任务由本技能承载 |
| `people-kb` | 含人物的时间信号（生日、约饭）在这里建提醒；人物档案本身归 people-kb |
| `work-notes` | 项目进展中的时间节点转交本技能做信号识别 |
| `lark-im` | 定时任务触发时通过飞书发送消息 |
| `lark-calendar` | 时间线可选同步到飞书日历（`sync_to_lark: true`） |

## ⚠️ 约束

- **cron 周几用名称**：APScheduler 的数字 weekday 约定与标准 cron 不同，用 `mon-sun` 而非 `1-5`
- **时间线配置需校验**：导入或手动编辑 timelines.yaml 后，Engine 会校验格式（anchor 合法、offset_start <= offset_end 等）
- **不越权**：Agent 不自行修改用户已确认的 DDL 或取消任务
- **路由优先**：本技能是路由入口，先判断路径再执行，不要跳过路由直接用 schedule_create
