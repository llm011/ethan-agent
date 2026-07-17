# 心跳系统设计文档

系统内部定期执行的维护任务：画像分区压缩，运行用户定义的周期性指令（heartbeat.md），并执行决策模式抽取和需求挖掘。

---

## 与 Scheduler 的区别

| 维度 | Scheduler (APScheduler) | Heartbeat |
|------|------------------------|-----------|
| 创建方式 | 用户通过对话或 CLI 主动创建 | 系统自动运行，不暴露给用户管理 |
| 任务内容 | 任意用户业务任务（提醒、报告等） | 系统维护：画像压缩 + heartbeat.md + 决策抽取 + 需求挖掘 |
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
       ├── _consolidate_profiles()           # 画像分区压缩
       ├── _run_heartbeat_md()               # 执行 heartbeat.md 任务
       ├── _extract_decision_patterns()      # 抽取成功路径 → success_patterns
       ├── _mine_recurring_needs()           # 挖掘重复模式 → suggestions.json
       └── sleep(interval_minutes * 60)
```
-->

---

## 四个维护动作

> 注：原「Facts 去重（`_consolidate_facts`）」已随 flat-facts 系统退役删除——
> 长期事实由结构化记忆管道的准入 merge + 夜间复评负责（见 memory.md）。

### 1. 画像分区压缩（`_consolidate_profiles`）

每日一次（`profile_consolidate_hour` 后），按 identity / emotion / agreement 三组分别压缩 `user_profile.md`。跳过条件：未到钟点 / 今天已压 / 无改动 / bullet < 4。
→ 详见 [memory.md · Profile](./memory.md#第三层用户画像user-profile)

### 2. heartbeat.md 任务（`_run_heartbeat_md`）

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

### 3. 决策模式抽取（`_extract_decision_patterns`）

从近 20 个 session 的 tool_steps 抽取高频成功路径（≥2 次）→ `playbook.json` 的 `success_patterns`。
→ 详见 [memory.md · 过程记忆](./memory.md#过程记忆procedurestore)

### 4. FDE 需求挖掘（`_mine_recurring_needs`）

从近 30 个 episodes 识别 ≥3 次重复模式 → `suggestions.json` → 下次对话首轮注入 `<proactive_suggestion>`。用户拒绝后不再重复。
→ 详见 [memory.md · Episode](./memory.md#第四层情节记忆episodic-memory)

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

### 每日 0 点记忆沉淀（`_midnight_loop`）

`start_heartbeat()` 还会启动一条独立的 midnight loop。到达服务器本地 0 点后，它遍历所有用户，并在对应 `ETHAN_USER_ID` 上下文中执行统一的夜间沉淀 `run_nightly_consolidation()`（做梦与结构化每日沉淀已合并为单一编排）：

1. **结构化每日沉淀**：按用户本地自然日补提短 session、重跑 pending 候选准入、标记过期记录、生成 general/companion 分域 DailySummary；
2. **重建 memory 向量索引**（准入语义配对与混合召回的底层，自愈漂移）；
3. **做梦（insight 挖掘）**：先把最新 memories 同步为向量去重底库，再精炼 repetition/error/success_path 信号，embedding 去重后写 `vec_items`，repetition/error 反写为结构化候选走准入、success_path 反写 playbook。

顺序有意为之：结构化先跑，当日新准入的记忆进入做梦的去重底库，insight 不会与刚提取的记忆重复反写。两步各自保留独立的 `consolidation_jobs` 记录（`user_id + local_date + pipeline_version` 为 job_key）：已完成或正在运行时跳过；失败状态可重试，失败不推进处理边界。单用户上下文用 `ContextVar.set/reset` 包裹，确保不同 profile 的 `memory.db` 物理隔离。

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
