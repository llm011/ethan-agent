# 调度器设计文档

用户管理的定时任务系统，让 Agent 能按计划执行周期性任务。基于 APScheduler 实现，Job 持久化到 SQLite，重启后自动恢复。

> 注意：与系统内部的心跳机制（`heartbeat.py`）不同，Scheduler 管理的是用户主动创建的业务任务（定时提醒、定期汇报等）。两者独立运行，互不干扰。→ 详见 [heartbeat.md](./heartbeat.md)

---

## 架构

```
┌──────────────────────────────────────────┐
│ ethan schedule list/remove/pause/resume  │  CLI 命令
├──────────────────────────────────────────┤
│ schedule_create / list / remove Tools    │  LLM 可直接调用
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
scheduler.add_interval("water-reminder", func, minutes=30)  # 每 30 分钟
scheduler.add_interval("check", func, hours=1)              # 每小时
```

---

## Agent 自主创建任务

用户说"每天早上 9 点提醒我喝水"，LLM 通过 `schedule_create` tool 自动创建 cron job：

```python
schedule_create(
    job_id="morning-reminder",
    prompt="提醒我喝水",
    cron="0 9 * * *"
)
```

执行时会创建专属 Session，执行结果保存在该 Session 中，可在 Web UI 的「定时任务」页查看。

---

## 持久化

使用 SQLAlchemy + SQLite（`~/.ethan/scheduler.db`）。APScheduler 的 SQLAlchemyJobStore 序列化 Job 到数据库，重启后自动恢复所有 pending jobs。

---

## CLI 命令

```bash
ethan schedule list              # 列出所有任务
ethan schedule remove <id>       # 删除任务
ethan schedule pause <id>        # 暂停
ethan schedule resume <id>       # 恢复
```

Web UI 的 `/schedule` 页面提供相同操作。
