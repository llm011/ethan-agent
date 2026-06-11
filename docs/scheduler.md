# 调度器设计文档

## 概述

Ethan 内置定时任务系统，让 agent 能按计划执行任务：定时提醒、定期检查、心跳回顾等。基于 APScheduler 实现，Job 持久化到 SQLite，重启后自动恢复。

---

## 架构

```
┌──────────────────────────────────────────┐
│ ethan schedule list/remove/pause/resume  │  CLI 命令
├──────────────────────────────────────────┤
│ Scheduler                                │  ethan/scheduler/cron.py
│   ├── BackgroundScheduler (APScheduler)  │
│   ├── SQLAlchemyJobStore (SQLite 持久化) │
│   └── CronTrigger / IntervalTrigger      │
├──────────────────────────────────────────┤
│ ~/.ethan/scheduler.db                    │  持久化存储
└──────────────────────────────────────────┘
```

---

## 两种调度模式

### Cron（定时）

标准 5 段 cron 表达式：`分 时 日 月 周`

```python
scheduler.add_cron("morning-check", func, "0 9 * * *")  # 每天 9:00
scheduler.add_cron("weekly", func, "0 10 * * 1")        # 每周一 10:00
```

### Interval（间隔）

```python
scheduler.add_interval("heartbeat", func, minutes=30)   # 每 30 分钟
scheduler.add_interval("check", func, hours=1)          # 每小时
```

---

## 持久化

使用 SQLAlchemy + SQLite（`~/.ethan/scheduler.db`）。

APScheduler 的 SQLAlchemyJobStore 会序列化 Job 对象到数据库。重启进程后调用 `scheduler.start()` 会自动恢复所有 pending jobs。

---

## CLI 命令

```bash
ethan schedule list              # 列出所有任务
ethan schedule remove <id>       # 删除任务
ethan schedule pause <id>        # 暂停
ethan schedule resume <id>       # 恢复
```

---

## 未来规划

### Heartbeat 心跳机制

定期（如每小时）触发 agent 回顾：
- 检查是否有待办事项到期
- 持久记忆是否需要整理
- 是否有定时提醒要发送

### Agent 自主创建任务

让 LLM 通过 tool call 创建定时任务：

```python
class ScheduleTool(BaseTool):
    name = "schedule_task"
    description = "Create a scheduled task"
    ...
```

用户说"每天早上 9 点提醒我喝水"，agent 自动调用 schedule_task 创建 cron job。
