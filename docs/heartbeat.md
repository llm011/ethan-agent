# 心跳系统设计文档

系统内部定期执行的维护任务：对长期记忆（facts）做去重合并，并运行用户定义的周期性指令（heartbeat.md）。

---

## 与 Scheduler 的区别

| 维度 | Scheduler (APScheduler) | Heartbeat |
|------|------------------------|-----------|
| 创建方式 | 用户通过对话或 CLI 主动创建 | 系统自动运行，不暴露给用户管理 |
| 任务内容 | 任意用户业务任务（提醒、报告等） | 系统维护：facts 去重 + heartbeat.md |
| 配置项 | job_id / cron / interval_minutes | config.defaults.heartbeat |
| 持久化 | `~/.ethan/scheduler.db` | 不持久化，每次随服务启动 |
| 可见性 | Web UI `/schedule` 页面可见 | 不在调度器页面显示 |

简单说：Scheduler 是给用户用的，Heartbeat 是系统自己的看门狗。

---

## 架构

文件：`ethan/core/heartbeat.py`

```
start_heartbeat()
   │ (asyncio background task)
   ▼
_loop():
   ├── 延迟 60 秒（避免服务刚启动时立即触发）
   └── while True:
       ├── _consolidate_facts()   # facts 去重合并
       ├── _run_heartbeat_md()    # 执行 heartbeat.md 任务
       └── sleep(interval_minutes * 60)
```

---

## 两个维护动作

### 1. Facts 去重（`_consolidate_facts`）

触发条件：`facts.json` 中活跃 fact 数量 ≥ 10。

流程：
1. 读取所有活跃 facts
2. 用廉价模型（Haiku / Flash Lite）对其做合并、去重、矛盾修正
3. 将原有 facts 全部标记为 `superseded`
4. 写入整理后的新 facts（置信度 0.85，source="heartbeat_consolidation"）

廉价模型选取逻辑与 `Consolidator` 相同（见 [memory.md](./memory.md)）。

### 2. heartbeat.md 任务（`_run_heartbeat_md`）

触发条件：`~/.ethan/system/heartbeat.md` 文件存在且包含非注释内容。

流程：
1. 读取 heartbeat.md 内容作为 prompt
2. 启动一个完整 Agent 实例（加载全量工具和 Skills）
3. 执行 Agent.chat()，结果写入专属的 `[心跳] System` Session
4. 如果 `[心跳] System` Session 不存在则自动创建

heartbeat.md 示例：

```markdown
# 每次心跳任务

检查今天的待办事项是否有到期的，如果有，向知识库添加一条提醒记录。
```

注释行（以 `#` 开头）会被忽略，只有实质性内容行才触发执行。

---

## 配置

在 `~/.ethan/config.yaml` 中：

```yaml
defaults:
  heartbeat:
    enabled: true
    interval_minutes: 10   # 每 10 分钟执行一次
```

也可在 Web UI 的「设置」页面修改。

---

## 启动与停止

心跳在 `ethan serve`（FastAPI 服务）启动时通过 `start_heartbeat()` 创建后台 asyncio task。服务关闭时调用 `stop_heartbeat()` 取消 task。

REPL 模式下不启动心跳（心跳更适合长期运行的服务端场景）。

---

## 数据流

```
[Heartbeat tick]
   │
   ├─ FactStore.get_active() ≥ 10 条？
   │   └─ 是 → LLM 去重 → FactStore 全量替换
   │
   └─ heartbeat.md 有实质内容？
       └─ 是 → Agent.chat(heartbeat.md) → [心跳] System Session
```
