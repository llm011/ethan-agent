# 每日例行情报：heartbeat 检查流程

> 本文件供 heartbeat agent 通过 `skill_read(name="work-notes", file="references/heartbeat.md")` 拉取。
> 当 heartbeat.md 含 `[agent:work-notes]` 任务时，按本流程执行每日例行检查。

## 配置文件：`{workspace}/system/routine-config.json`

首次配置时由 Agent 询问用户后写入：

```json
{
  "enabled": true,
  "workdays": [1, 2, 3, 4, 5],
  "time_range": {"start": "09:00", "end": "19:00"},
  "suggest_windows": {
    "product": ["09:00", "12:00"],
    "reading": ["13:00", "16:00"],
    "reflection": ["16:00", "19:00"]
  },
  "max_reminds_per_day": 2,
  "notify_channel": null
}
```

- `workdays`：工作日（1=周一 … 7=周日），默认周一到周五
- `time_range`：心跳处理例行的时间范围，范围外不提醒
- `suggest_windows`：各类例行的建议时段（提醒只在这些时段内触发）
- `max_reminds_per_day`：每类每日最多提醒次数（默认 2 次：开始时 1 次+临近结束 1 次）
- `notify_channel`：通知渠道，`null` 表示未配置

**通知渠道配置**：Agent 主动询问「要不要配置飞书通知？每天到点提醒你」。用户同意后：
- 询问飞书账号（open_id 或姓名），用 `lark-cli contact +search` 解析成 open_id
- 写入 `notify_channel: {"type": "lark", "open_id": "ou_xxx"}`
- **每次用户使用每日例行功能时，若 `notify_channel` 为 null，都提醒一次**「还没配置通知渠道，要配置吗？」

## 状态文件：`{workspace}/system/routine-state.json`

```json
{
  "date": "2026-08-03",
  "routines": {
    "product":    {"done": false, "remind_count": 0, "skip_reason": null, "last_remind": null, "last_done_time": null},
    "reading":    {"done": false, "remind_count": 0, "skip_reason": null, "last_remind": null, "last_done_time": null},
    "reflection": {"done": false, "remind_count": 0, "skip_reason": null, "last_remind": null, "last_done_time": null}
  }
}
```

## 心跳检查流程（heartbeat 触发时执行）

```
1. 读 routine-config.json，若 enabled=false 或当前不在 workdays/time_range 内 → 跳过
2. 读 routine-state.json：
   a. 若 date != 今天 → 先归档昨天的状态（写入知识库「每日例行回顾」），再初始化今天的新状态
   b. 遍历三类例行，对每一类：
      - 若 done=true 或 skip_reason!=null → 跳过
      - 若当前时间不在 suggest_windows 内 → 跳过
      - 若 remind_count >= max_reminds_per_day → 跳过
      - 否则 → 发提醒，remind_count++，last_remind=当前时间
3. 提醒发送：
   - 若 notify_channel 已配置 → 通过 lark-cli im +send 发飞书消息给主人
   - 若未配置 → 不发通知，但下次用户交互时提醒配置
4. 更新 routine-state.json
```

## 提醒消息格式（飞书）

```
【每日例行提醒】{YYYY-MM-DD}
还没做：产品体验
建议时段：上午 09:00-12:00
回复「产品体验」开始记录，或回复「今天不做产品体验，因为...」跳过
```

## 用户执行例行（更新状态）

用户说「产品体验」/「文档阅读」/「工作梳理」时：
1. 走 SKILL.md 中的执行路径
2. 执行完成后，更新 routine-state.json：`done=true`，`last_done_time=当前时间`
3. 若 notify_channel 未配置，提醒一次「要配置飞书通知吗？」

## 跳过处理

用户说「今天不做 XX，因为 YY」：
- 更新 routine-state.json：`skip_reason="YY"`
- 之后当天不再提醒该类
- 跳过原因会记入每日回顾

## 每日回顾

触发：「每日回顾」/「今天的例行总结」/ 心跳在 time_range 结束前最后一次触发

1. 读 routine-state.json，汇总今日三类完成情况（done / skip_reason / 未做无原因）
2. `knowledge_edit`（append，scene="work"）追加到 `每日例行回顾 - {YYYY-MM}`：
   ```markdown
   ## {MM-DD}
   - 产品体验：✅ {一句话} / ❌ 跳过（{原因}）/ ❌ 未做
   - 文档阅读：✅ {一句话} / ❌ 跳过（{原因}）/ ❌ 未做
   - 工作梳理：✅ {一句话} / ❌ 跳过（{原因}）/ ❌ 未做
   - 明日重点：{1-2 件要跟进的事}
   ```
   条目不存在时先 `knowledge_add`（tags: `["routine", "daily-review", "{YYYY-MM}"]`）

## 跨天重置

心跳在新的一天首次触发时：
1. 归档昨天的状态到知识库（走「每日回顾」流程，若昨天没做回顾）
2. 重置 routine-state.json：`date=今天`，所有 routines 恢复初始状态

## heartbeat 任务注册

配置完成后，Agent 调用 `heartbeat_add` 工具注册心跳任务：

```
heartbeat_add(task_type="agent", task="work-notes")
```

> 工具会在 heartbeat.md 追加一行如 `1  [agent:work-notes]`。
> 若要移除：`heartbeat_remove(task_id=<编号>)`，编号用 `heartbeat_list()` 查。
