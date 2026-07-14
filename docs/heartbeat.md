# 心跳系统设计文档

系统内部定期执行的维护任务：对长期记忆（facts）做去重合并，运行用户定义的周期性指令（heartbeat.md），并执行决策模式抽取和需求挖掘。

---

## 与 Scheduler 的区别

| 维度 | Scheduler (APScheduler) | Heartbeat |
|------|------------------------|-----------|
| 创建方式 | 用户通过对话或 CLI 主动创建 | 系统自动运行，不暴露给用户管理 |
| 任务内容 | 任意用户业务任务（提醒、报告等） | 系统维护：facts 去重 + heartbeat.md + 决策抽取 + 需求挖掘 |
| 配置项 | job_id / cron / interval_minutes | config.defaults.heartbeat |
| 持久化 | `~/.ethan/scheduler.db` | 不持久化，每次随服务启动 |
| 可见性 | Web UI `/schedule` 页面可见 | 不在调度器页面显示 |

简单说：Scheduler 是给用户用的，Heartbeat 是系统自己的看门狗。

---

## 架构

文件：`ethan/core/heartbeat.py`

![心跳机制架构](./images/heartbeat-arch.jpg)
<!-- diagram-source
```
start_heartbeat()
   │ (asyncio background task)
   ▼
_loop():
   ├── 延迟 60 秒（避免服务刚启动时立即触发）
   └── while True:
       ├── _consolidate_facts()              # facts 去重合并
       ├── _consolidate_profiles()           # 画像分区压缩
       ├── _run_heartbeat_md()               # 执行 heartbeat.md 任务
       ├── _extract_decision_patterns()      # 抽取成功路径 → success_patterns
       ├── _mine_recurring_needs()           # 挖掘重复模式 → suggestions.json
       └── sleep(interval_minutes * 60)
```
-->

---

## 五个维护动作

### 1. Facts 去重（`_consolidate_facts`）

触发条件：`facts.json` 中活跃 fact 数量 ≥ 10。

流程：
1. 读取所有活跃 facts
2. 用廉价模型（Haiku / Flash Lite）对其做合并、去重、矛盾修正
3. 将原有 facts 全部标记为 `superseded`
4. 写入整理后的新 facts（置信度 0.85，source="heartbeat_consolidation"）

廉价模型选取逻辑与 `Consolidator` 相同（见 [memory.md](./memory.md)）。

### 2. 画像分区压缩（`_consolidate_profiles`）

对每个用户的 `user_profile.md` 做每日分区压缩，按 identity / emotion / agreement 三个策略组分别处理。

触发闸门：
- ① 还没到当天触发钟点（`profile_consolidate_hour`）→ 等
- ② 今天已经压过 → 跳过（每天一次）
- ③ 画像自上次压缩后没改动 → 跳过，不空烧 token

每个 section 的 bullet 数 < 4 时跳过（没东西可去重，强模型重写反增幻觉风险）。

### 3. heartbeat.md 任务（`_run_heartbeat_md`）

触发条件：`~/.ethan/system/heartbeat.md` 文件存在且内容非空。

流程：
1. 读取 heartbeat.md 完整内容作为 prompt（前缀 `[Heartbeat] 正在执行系统心跳任务：heartbeat.md`）
2. 启动一个完整 Agent 实例（加载全量工具和 Skills）
3. 用 `stream_chat()` 执行，完整记录工具步骤 / 思考过程 / token usage
4. **每次心跳创建一个独立的 `[心跳] <时间戳>` Session**（如 `[心跳] 2026-06-21 12:33`），便于在 Web 会话列表里独立查看每次心跳的执行过程
5. 仅当 heartbeat.md 有实质内容时才执行（空文件不产生无意义 Session）

heartbeat.md 是一个普通 Markdown 文件，所有内容都作为 prompt 发给 Agent，包括标题行。示例：

```markdown
## 每次心跳任务

检查今天的待办事项是否有到期的，如果有，向知识库添加一条提醒记录。
```

### 4. 决策模式抽取（`_extract_decision_patterns`）

从历史 session 的 tool_steps 中抽取高频成功路径，写入 `playbook.json` 的 `success_patterns` 字段，作为正反馈注入 `<behavioral_guidelines>`。

流程：
1. 取近 20 个活跃 session 的 tool_steps
2. 用 lite 模型归纳 `(场景 | tool1 → tool2 → ...)` 模式
3. 相同 scenario 合并、success_count 累加
4. ≥2 次的写入 `ProcedureStore.add_success_pattern()`

这是"闭环学习"的关键：Agent 越用越聪明，高频操作路径自动固化。

### 5. FDE 需求挖掘（`_mine_recurring_needs`）

从 episodes 中识别 ≥3 次的重复模式，写入 `suggestions.json`，下次对话首轮注入 `<proactive_suggestion>` 提醒 Agent 自然提起。

流程：
1. 取近 30 个 episodes 的 summary + keywords
2. 用 lite 模型识别重复模式
3. ≥3 次的写入 `~/.ethan/memory/suggestions.json`
4. 已标记 `rejected` 的不再重复

**关键约束**：不主动发消息打扰用户，只在下次对话首轮提起。用户拒绝后记入 `rejected`，不再重复。

---

## 配置

在 `~/.ethan/config.yaml` 中：

```yaml
defaults:
  heartbeat:
    enabled: true
    interval_minutes: 10   # 每 10 分钟执行一次
    profile_consolidate_hour: 3  # 画像压缩在凌晨 3 点后触发
```

也可在 Web UI 的「设置」页面修改。

---

## 启动与停止

心跳在 `ethan serve`（FastAPI 服务）启动时通过 `start_heartbeat()` 创建后台 asyncio task。服务关闭时调用 `stop_heartbeat()` 取消 task。

CLI 模式下不启动心跳（心跳更适合长期运行的服务端场景）。

---

## 数据流

![心跳数据流](./images/heartbeat-dataflow.jpg)
<!-- diagram-source
```
[Heartbeat tick]
   │
   ├─ FactStore.get_active() ≥ 10 条？
   │   └─ 是 → LLM 去重 → FactStore 全量替换
   │
   ├─ 到达 profile_consolidate_hour 且画像有改动？
   │   └─ 是 → 分区压缩（identity/emotion/agreement）→ user_profile.md
   │
   ├─ heartbeat.md 有实质内容？
   │   └─ 是 → Agent.stream_chat(heartbeat.md)
   │          → 收集 tool_steps / thought / usage
   │          → 写入新 Session：[心跳] <时间戳>
   │
   ├─ 近 20 个 session 有 tool_steps？
   │   └─ 是 → lite 模型归纳 (场景 → 工具序列)
   │          → ≥2 次的写入 success_patterns
   │
   └─ 近 30 个 episodes 有重复模式？
       └─ 是 → lite 模型识别 ≥3 次的模式
              → 写入 suggestions.json（未拒绝的）
```
-->
