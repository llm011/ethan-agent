# 时间线引擎 SOP

本文档描述 Agent 如何解析 `timelines.yaml` 配置，将声明式时间线"编译"为具体的定时任务。

## 架构概览

```
timelines.yaml (声明式配置)
        │
        ▼
┌─────────────────────────────┐
│  Timeline Engine (本 SOP)    │
│  1. resolve_anchors          │
│  2. determine_current_phase  │
│  3. expand_actions           │
│  4. sync_scheduler           │
│  5. lifecycle_manage         │
└─────────────────────────────┘
        │
        ▼
Scheduler (统一定时任务池)
  ├── one_off 任务
  ├── recurring 任务
  └── timeline 任务 (带 source 标记)
```

## Step 1: 解析锚点 (resolve_anchors)

从 `timelines.yaml` 中每个时间线的 `schedule` 字段计算**本周期**和**下一周期**的具体日期。

### 输入

```yaml
schedule:
  anchor: "07-01"          # MM-DD 格式
  recurrence: yearly       # yearly / semi_annual / quarterly / monthly
```

### 解析逻辑

```
给定 today：
1. 将 anchor 解析为 本年的 MM-DD → candidate
2. 计算该时间线最早阶段的 offset_start（如 -5m）
3. 如果 candidate + 最后阶段的 offset_end < today：
   → 本周期已结束，candidate = 下一个周期的 anchor
4. 否则 candidate 就是本周期的 anchor_date
```

### 多锚点

如果 `anchor` 是数组（如 `["01-01", "04-01", "07-01", "10-01"]`），取距 today 最近且周期未完全结束的那个。

### 输出

```
anchor_date: 2026-07-01
cycle_label: "2026-H1"  # 可选，用于展示
next_anchor: 2027-01-15
```

## Step 2: 判断当前阶段 (determine_current_phase)

根据 today 和 anchor_date，确定处于哪个 phase。

```
对每个 phase：
  phase_start = anchor_date + parse_offset(phase.offset_start)
  phase_end = anchor_date + parse_offset(phase.offset_end)
  
  if phase_start <= today <= phase_end:
    current_phase = phase
    break

如果 today 不在任何 phase 内 → 该时间线处于"休眠"状态
```

### 状态展示

```
📅 半年绩效考核
   状态：日常收集期（2026-02-01 ~ 2026-06-17）
   下一阶段：集中汇总期，06-17 开始

📅 全年绩效考核
   状态：休眠中
   下一节点：2026-12-25 启动汇总
```

## Step 3: 展开动作 (expand_actions)

将每个 phase 内的 actions 展开为具体的 scheduler 任务。

### once 类型

```yaml
- type: once
  offset: "-2w"
  message: "绩效季将至..."
  target: self
```

展开为：
```
fire_at = anchor_date + parse_offset("-2w") = 2026-06-17
→ 创建 one-off scheduler 任务
  name: "timeline_perf_semi_annual_集中汇总期_once_1"
  fire_at: "2026-06-17 10:00"
  message: "绩效季将至..."
  metadata:
    category: timeline
    source_timeline: perf_semi_annual
    source_phase: "集中汇总期"
    scene: work
```

### recurring 类型

```yaml
- type: recurring
  cron: "0 10 * * 5"
  message: "本周有没有值得记录的团队 case？"
  target: self
```

展开为：
```
active_from = anchor_date + parse_offset(phase.offset_start)
active_until = anchor_date + parse_offset(phase.offset_end)
→ 创建带生效窗口的 recurring scheduler 任务
  name: "timeline_perf_semi_annual_日常收集期_recurring_1"
  cron: "0 10 * * 5"
  active_from: "2026-02-01"
  active_until: "2026-06-17"
  message: "本周有没有值得记录的团队 case？"
  metadata:
    category: timeline
    source_timeline: perf_semi_annual
    source_phase: "日常收集期"
    scene: work
```

## Step 4: 同步到 Scheduler (sync_scheduler)

### 同步策略

```
1. 读取 scheduler 中所有 category=timeline 的任务
2. 对比 expand_actions 生成的任务列表
3. 新增：配置中有但 scheduler 中没有的
4. 删除：scheduler 中有但配置中已不存在/已过期的
5. 更新：message 或 cron 发生变化的
```

### 去重标识

每个 timeline 任务的唯一 ID 由以下组合生成：
```
{timeline_id}_{phase_name}_{action_type}_{action_index}_{cycle_anchor}
```

### 防重复触发

- 已触发的 once 类型任务标记为 `fired`，不再创建
- 通过记录文件 `~/.ethan/work/.timeline_state.json` 跟踪：

```json
{
  "perf_semi_annual": {
    "current_anchor": "2026-07-01",
    "fired_actions": [
      "集中汇总期_once_1_2026-06-17",
      "集中汇总期_once_2_2026-06-24"
    ]
  }
}
```

## Step 5: 生命周期管理 (lifecycle_manage)

### 周期轮转

```
当 today > 本周期最后一个 phase 的 end_date：
1. 标记本周期为 completed
2. 清理本周期所有 timeline 任务
3. 计算下一周期 anchor
4. 为下一周期展开新的任务
5. 更新 .timeline_state.json
```

### 手动操作

用户可以：
- 「跳过这个阶段的提醒」→ 标记该 phase 所有未触发 action 为 skipped
- 「提前进入下一阶段」→ 立即触发下一阶段首个 action
- 「暂停绩效时间线」→ 暂停该 timeline 所有 scheduler 任务

## offset 解析规则

| 格式 | 含义 | 示例 |
|---|---|---|
| `-Nm` | 锚点前 N 个月 | `-5m` = 前 5 个月 |
| `-Nw` | 锚点前 N 周 | `-2w` = 前 2 周 |
| `-Nd` | 锚点前 N 天 | `-3d` = 前 3 天 |
| `0d` | 锚点当天 | |
| `+Nd` | 锚点后 N 天 | `+1d` = 后 1 天 |
| `+Nw` | 锚点后 N 周 | `+1w` = 后 1 周 |
| `+Nm` | 锚点后 N 个月 | `+2m` = 后 2 个月 |

## target 解析规则

| 值 | 行为 |
|---|---|
| `self` | 发提醒给管理者自己（通过 scheduler） |
| `all` | 发给 team.yaml 中所有成员 |
| `{姓名}` | 发给指定成员（通过飞书消息） |

## 触发时的执行

当 scheduler 触发一个 timeline 类任务时：

1. **消息发送**：根据 target 发送飞书消息或自提醒
2. **状态更新**：在 `.timeline_state.json` 中记录已触发
3. **联动操作**：某些 message 可以包含指令标记（如 `[ACTION:汇总绩效]`），Agent 识别后主动执行对应操作

## 可选：飞书可视化

时间线可选同步到飞书日历，为每个 phase 创建一个全天事件，便于在飞书日历中查看整个周期。

### 配置

在 `timelines.yaml` 中为需要同步的 timeline 添加 `sync_to_lark: true`：

```yaml
timelines:
  - id: perf_semi_annual
    name: 半年绩效
    sync_to_lark: true    # 开启飞书日历同步
    schedule:
      anchor: "07-01"
      recurrence: yearly
    phases:
      - name: 日常收集期
        offset_start: "-5m"
        offset_end: "-1m"
        ...
```

### 同步行为

调用 `sync_to_lark(timeline_id)` 时：

1. **幂等检查**：读取 `.timeline_state.json` 中的 `lark_sync.anchor`
   - 若与当前周期锚点一致且有 `event_ids` → 跳过（返回 `skipped: true`）
   - 若锚点变化（周期轮转）→ 先删除旧事件，再创建新事件
2. **创建事件**：对每个 phase 调用 `lark-cli calendar +create`
   - 标题：`📅 [{timeline_name}] {phase_name}`
   - 时间：全天事件（start = phase_start 00:00，end = phase_end + 1 天）
   - 描述：列出该阶段所有 actions 的摘要
3. **状态记录**：在 state 中写入 `lark_sync: {anchor, event_ids, synced_at}`

### 清理

调用 `cleanup_lark_resources(timeline_id)` 删除该时间线在飞书日历上的所有已同步事件，并清空 state 中的 `lark_sync` 记录。用于：
- 用户关闭 `sync_to_lark` 后清理残留事件
- 手动请求重新同步前
- 调试/重置

### API

```http
# 同步某条时间线到飞书日历
POST /schedule/timeline/{timeline_id}/sync-lark

# 清理某条时间线的飞书日历事件
POST /schedule/timeline/{timeline_id}/cleanup-lark
```

### 依赖

- 需要安装 lark-cli 并完成 user token 授权（`lark-cli auth login --as user`）
- 需要日历创建权限（calendar.events:create）
- lark-cli 不可用或未授权时，sync_to_lark 会返回 `ok: false` 和 `errors` 列表，但不影响其他功能

## 导出与迁移

时间线配置是**纯声明式**的——`timelines.yaml` 用 `anchor + recurrence` 表达无限周期，而非穷举每一年的具体日期。因此导出即备份配置文件本身。

### 导出命令

用户说「导出时间线」「备份时间线配置」时：

```
1. 读取 ~/.ethan/work/timelines.yaml
2. 读取 ~/.ethan/work/.timeline_state.json（运行状态）
3. 合并为导出包：
   {
     "version": "1.0",
     "exported_at": "2026-07-21T10:00:00+08:00",
     "config": { ...timelines.yaml 内容（转为 JSON/YAML 均可）... },
     "state": { ...timeline_state.json 内容... }
   }
4. 写出到用户指定位置，默认 ~/.ethan/exports/timelines-{YYYY-MM-DD}.yaml
```

### 导出格式

支持两种格式，用户可指定：
- **YAML**（默认）：人类可读，便于手动编辑
- **JSON**：程序化处理友好，适合跨系统迁移

### 导入/恢复

用户说「导入时间线」「恢复时间线」时：

```
1. 读取导出文件（YAML 或 JSON）
2. 校验 version 兼容性（必须是 1.x）
3. 校验 config 内容（调用 validate_timelines_file）：
   - id 唯一合法
   - anchor MM-DD 格式且日期合法（02-31 会报错）
   - recurrence 必须为 yearly/semi_annual/quarterly/monthly
   - phases 非空、phase.name 必填
   - offset_start <= offset_end
   - action.type 必须为 once/recurring
   - once 必须有 offset、recurring 必须有 5 字段 cron
4. 校验失败 → 直接返回错误列表，不修改任何文件
5. 可选 dry_run：只返回"会发生什么"，不写入
6. 选择写入模式：
   - overwrite（默认）：完全覆盖现有 timelines.yaml
   - merge：按 id 合并，导入的同名 id 覆盖现有，其他保留
7. 写入前自动备份现有配置（带时间戳，不互相覆盖）
8. 可选 restore_state：恢复 .timeline_state.json
9. 可选 sync_after：写入后自动调用 sync_scheduler
```

#### API 调用示例

```http
POST /schedule/timeline-import
{
  "path": "~/.ethan/work/exports/timelines-2026-07-21.yaml",
  "dry_run": true,
  "mode": "merge"
}

# 响应（dry_run）
{
  "ok": true,
  "dry_run": true,
  "validation": {"ok": true, "errors": [], "warnings": [], "timelines_count": 2},
  "mode": "merge",
  "timelines_count": 3,
  "merged_from_existing": 1,
  "state_restored": false
}
```

#### 独立校验

用户说「检查一下这个时间线文件」时，可以单独调用校验：

```http
POST /schedule/timeline-validate
{"path": "/path/to/timelines.yaml"}
```

返回 `{ok, errors, warnings, timelines_count}`，不会修改任何文件。

### 周期性表达设计原则

```
❌ 错误：穷举每年的具体日期
timelines:
  - fire_at: "2026-07-01"
  - fire_at: "2027-07-01"
  - fire_at: "2028-07-01"
  ...

✅ 正确：声明锚点 + 周期，Engine 在运行时计算
schedule:
  anchor: "07-01"
  recurrence: yearly
```

核心理念：
- 配置文件只描述**规则**（什么时候、什么周期、什么动作）
- Engine 负责根据当前日期**实时计算**本周期的具体日期
- `.timeline_state.json` 记录**已发生的事实**（哪些动作已触发）
- 两者分离，配置永远有效，状态可重置可迁移

## 完整流程示例

假设 today = 2026-03-15，配置了半年绩效时间线（anchor: 07-01）：

```
1. resolve_anchors:
   → anchor_date = 2026-07-01（本周期）

2. determine_current_phase:
   → "日常收集期" (offset_start: -5m = 02-01, offset_end: -2w = 06-17)
   → today(03-15) 在范围内 ✓

3. expand_actions:
   → recurring: 每周五 10:00 提醒记 case（active 02-01 ~ 06-17）
   → once: 06-17 汇总提醒（尚未触发）
   → once: 06-24 一周倒计时提醒（尚未触发）
   → once: 06-28 撰写开始提醒（尚未触发）

4. sync_scheduler:
   → 确认 recurring 任务已在 scheduler 中活跃
   → once 任务已注册，等待触发

5. 当前展示:
   📅 半年绩效考核 — 日常收集期
      🔄 每周五 10:00 提醒记 case（进行中）
      ⚡ 06-17 启动汇总（87天后）
      ⚡ 06-24 确认评估完整（94天后）
      ⚡ 06-28 开始撰写评估（98天后）
```
