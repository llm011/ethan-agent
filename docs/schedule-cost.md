# 定时任务成本报表

Web / Desktop 的定时任务列表卡片和时间轴均展示近 7 天（滚动 604800 秒）的运行次数、真实输入 token、缓存 token、命中率和平均工具步数。`GET /schedule` 为每个认证用户自己的 job 返回 `cost`；不可读时为 `null`，UI 显示不可用而非虚假零值。

## 统计口径

- **一条最终落库 assistant 消息代表一次运行**，包括最终记录的失败；`running` / `pending` 进度占位行不计。无最终落库行的尝试不计，网络重试不额外计。轮转阈值使用 user 消息数，与这里的成本运行数不是同一指标。
- 时间按该最终行 `created_at`：`> now - 7*86400 AND <= now`，非自然日、无时区歧义。复用进度行时沿用原行创建时间。
- 输入 / 缓存取 `messages.usage` 的 `input` / `cache`。input 是含缓存的 prompt 总量；只有有效 JSON、数值 input > 0 的行参加 token 汇总，缺失/坏 JSON 不估算。cache 缺失按 0（与 SQL SUM 忽略 NULL 等效）。不根据模型价格推算金额。
- 命中率 = `100 * SUM(cache) / SUM(input)`，保留 1 位小数；无输入分母显示 `—`，不冒充 0%。
- 平均步数 = 所有最终运行的 `tool_steps` JSON 数组长度平均，保留 1 位小数。缺失、坏 JSON 或非数组记 0；一个数组项是一条工具步骤，不是 LLM 请求轮数。
- `usage_run_count` 单独标出有效 input 的运行数量，明确运行分母与 token 统计分母不同。

## 精确归因与历史限制

独立模块 `ethan/scheduler/cost.py` 在现有 profile `db/sessions.db` 内维护 `schedule_message_attribution`，以最终 **message_id** 为唯一主键，保存 `session_id / job_id / user_id`。每次回调通过 SessionStore 原子接口将最终消息和精确映射同事务提交；原进度行被 UPDATE，不会重复记录一次运行。错误终态也归因。任务改标题、轮转到新 session、服务重启不覆盖旧映射。同一 session 被多个 job 使用，各消息仍只归属一个 job，不将整个 session 重复算给每个任务。

上线前没有映射的历史消息不能可靠恢复 job，**不猜标题、不将当前 job.session_id 下全部消息算给 job**。UI 标出当前用户近 7 天全局的 `unattributed_runs`，这是未归因缺口，不是当前任务的运行数、也不可按任务相加。新执行最终消息与映射在独占短连接的 `BEGIN IMMEDIATE` 事务内提交：消息写入后、归因写入前进程退出，SQLite 恢复会同时回滚，不会留下有最终 usage 却没有 job 映射的行。归因失败明确抛出，不能静默漏账。既有进度占位重启后可能被标记为 interrupted，但没有尚未提交的最终 usage；正常恢复定稿后仍复用原行，只计一次。自动 Recorder 的 checkpoint 终态可能在 channel 最终定稿前持久化；若在这两阶段间退出，该检查点尚不在 job 成本样本中，可能被报告为未归因，不用 checkpoint 状态猜测金额或 token。

目前只读活跃 `sessions.db`，不扫描会话数据库整体归档文件。因此数据库整体归档后，归档中的报表数字不包含在当前查询内；会话自身轮转不受影响。已删除 / 已到期移除的 job 不在当前任务列表展示。

## 安全与只读 SQL

- scheduler 是全局共享的；列表先按认证返回的 `user_id` 精确过滤 job（旧任务缺 user_id 仅归 default profile），再请求该 profile 的成本，不回传其他用户的任务内容或聚合。
- 回调在打开 SessionStore 前设置 job 的 user context。归因查询额外校验映射的 user_id、session_id、`sessions.source='schedule'`。
- 报表从认证 profile 路径直接解析现有文件，不调用会迁移/创建库的路径函数；连接 URI `mode=ro`，同时 `PRAGMA query_only=ON`，在线程中执行避免阻塞 API event loop。
- job ID 列表经 JSON 绑定到 `json_each(?)`，user ID 和时间边界都是绑定参数，不拼接用户 SQL、路径或标题。查询只返回聚合数字，不读取消息内容。
- 最终消息、归因和 sessions.updated_at 写入使用独立短 SQLite 连接，同事务提交，不提交 SessionStore / 检查点共享连接中的其他事务。既有消息归因不可改到其他 job/user，同 tuple 重试幂等；冲突显式回滚。SQLite 以外的工具副作用不在此事务保护范围。

### 与计划第 2 节复测 SQL 对照

在 `sqlite3 -readonly <当前profile的db/sessions.db>` 中执行下面 SQL；参数由调用方绑定。前四项与计划 SQL 一致，只是加上精确 job 归因和终态过滤。运行总数另按所有终态 assistant 行计算，不能用有效 usage 数冒充。

```sql
SELECT count(*), sum(json_extract(m.usage,'$.input')),
       sum(json_extract(m.usage,'$.cache')),
       round(100.0*sum(json_extract(m.usage,'$.cache')) /
             sum(json_extract(m.usage,'$.input')),1)
FROM messages m
JOIN sessions s ON s.id=m.session_id
JOIN schedule_message_attribution a
  ON a.message_id=m.id AND a.session_id=m.session_id
WHERE a.job_id=? AND a.user_id=? AND s.source='schedule'
  AND m.role='assistant' AND m.status NOT IN ('running','pending')
  AND m.usage IS NOT NULL AND json_valid(m.usage)
  AND json_extract(m.usage,'$.input') > 0
  AND m.created_at > ? AND m.created_at <= ?;
```

完整生产 SQL 见 `COST_SQL`。合成 fixtures `tests/fixtures/schedule_cost.sql` 的固定 now=1000000、job a 结果：5 次运行，input 3100，cache 1010，命中率 32.6%，平均步骤 1.2，有效 usage 3 次；跨 old/new session 保留归因，shared session 的 job b 另计 900 input，不重复计入 a。

## 验证

后端：`PYTHONPATH=$PWD /Volumes/SSDExt/code/life/ethan-agent/.venv/bin/python -m pytest tests/test_schedule_cost.py -q`。

双端组件展示契约：`NODE_ENV=test pnpm --dir desktop exec vitest run src/__tests__/schedule-cost.test.tsx`，同一测试渲染 Web / Desktop 组件并核对 SQL fixture 数字、空分母和未归因提示。双端分别运行 `tsc --noEmit`。

独立验收基线：`19fd224d`（PR494 检查点已合并），工作区 `ethan-ai-schedule-cost`。成本测试覆盖消息 INSERT/UPDATE 后归因前强制子进程退出、SQLite 重启回滚后重试精确一次、归因异常回滚、归因冲突不可变 / 同 tuple 幂等、自动 Recorder pending 归因失败后仍认领同一行。本 worktree 实际验收：成本及 schedule/checkpoint/wire/resume 回归 57 项通过；Desktop 全量 26 个测试文件、256 项通过，其中双端成本展示契约 4 项。Web `pnpm --dir web exec next build --webpack` 通过（含 TypeScript 与 64 个静态页面生成），Desktop `NODE_ENV=test pnpm --dir desktop build` 通过。首次在两端生产构建并行时 Desktop 性能墙钟用例测得 111.39ms > 100ms，隔离复测及完整全量复测均通过，未放宽阈值。使用主仓解释器与 `PYTHONPATH` 指向本 worktree，无真实用户数据 fixture。

默认提示模板已由 PR495 精简到 5948 字符，旧 7052 超预算问题不再出现。带其他测试联跑时运行时技能热点用例出现 `hot=[]`，与成本无关；单独提示预算在主仓与本 worktree 均通过 11 项；两端 `tsc --noEmit` 独立检查通过，scoped ruff 与 diff whitespace 检查通过。已有测试仍可产生 React act 和 aiosqlite 线程关闭告警，不作为新成本报表成功指标。

未读取真实用户消息或敏感配置；未连接/操作账号；未部署服务。AOCI 未挂载，未做索引维护。
