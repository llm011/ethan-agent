# 事件触发与廉价心跳检查

## 默认行为

外部接入**默认关闭**，`POST /api/events/github`、`POST /api/events/alert` 返回 404。
仅设置 `ETHAN_EVENTS_ENABLED=1` 才开启；没有专用 secret 时仍拒绝（503）。
没有接入任何真实外部账号，也不改变飞书长连接或原有心跳任务。

事件只启动一次**无工具的原生 Agent 分析**，结果和 usage 保存到独立 `source=event`
会话，标题 `[事件] ...`，可通过现有会话接口查看。不会选外部 coding kernel、执行 shell、
自动授权、下载链接、写记忆/skills、发告警回复或自动修复。需要行动时由用户另行确认。

## 操作员环境配置

```sh
ETHAN_EVENTS_ENABLED=1
ETHAN_EVENTS_GITHUB_SECRET='<至少 32 字节随机专用 secret>'
ETHAN_EVENTS_GITHUB_REPOSITORIES='owner/repo,owner/another-repo'
ETHAN_EVENTS_ALERT_SECRET='<另一个至少 32 字节随机专用 secret>'
ETHAN_EVENTS_USER_ID='' # 固定 default profile；也可填已存在命名 profile
# 可选：单独事件去重库，默认 CONFIG_DIR/db/events.db
ETHAN_EVENTS_DB='/path/to/private/events.db'
```

不要复用 Web token/API key。没有仓库白名单时 GitHub 全部拒绝。profile 只由环境选择，
payload 不得决定 user/session/model/工作目录/权限；每次事件创建新 session，不附到既有对话。
生产需 TLS、反向代理请求速率限制和私有数据目录；不要把签名/secret 写入日志。

## GitHub / CI

将 webhook 的 Content type 配为 `application/json`，Secret 与专用 GitHub secret 相同。
仅接受 GitHub 原生 `push` 和 `workflow_run`；后者只支持 `action=completed`。
必须提供 `X-GitHub-Event`、`X-GitHub-Delivery`、`X-Hub-Signature-256`。
签名是 `sha256=` + `HMAC-SHA256(secret, 原始请求体)`。
未知类型（包括 ping）、非白名单仓库、无效 ref/commit/run/conclusion 均拒绝。
GitHub 配置 webhook 时的 ping 被明确拒绝，不会启动 Agent。

push 只传 type/repository/ref/after；workflow_run 只传 type/repository/run_id/conclusion。
提交说明、sender、workflow 名称、脚本等不会进入模型。这是最小 CI 结果摘要，不读取构建日志。

## 告警

```json
{"type":"alert","status":"firing","name":"CPU high","severity":"warning","summary":"CPU > 90%"}
```

status 仅 `firing` / `resolved`；name 必填（≤128 字符）、severity ≤32、summary ≤2000。
未知字段或事件拒绝。不能直接接 Prometheus Alertmanager 的批量原生格式，需发送方转成上述 schema。
请求头：

- `X-Event-Delivery`：稳定唯一 id，1–128 个字母/数字/`_.:-`；重试用原 id。
- `X-Event-Timestamp`：Unix 秒，允许与服务器时间偏差 300 秒。
- `X-Event-Signature-256`：`sha256=` + `HMAC-SHA256(alert_secret, delivery + '.' + timestamp + '.' + raw_body)`。

告警签名绑定 delivery、时间戳和 body，不支持普通 bearer token。summary 属不可信数据，
JSON 编码放到 user 数据消息，不能插入 system/runtime 指令；固定策略要求只作人工复核摘要。
Agent 无 tools/skills，`is_owner=False`，硬拒绝所有工具请求，防注入权限边界不依赖 prompt。

## 上限、去重和崩溃语义

- 原始 body ≤64 KiB，支持流式累计检查；读取超时 10 秒；入站每 worker 最多 8 个请求。
- 单独 SQLite 事务原子去重与全 worker admission：最多 2 个运行中事件、每分钟最多 10 次新事件。
- HMAC/类型/schema 检查通过后才 claim；拒绝不会占用 delivery。重复返回 `status=duplicate`，不再启动模型。
- admission/执行失败记录 `failed`/`interrupted`；相同 id 仍不自动重跑，避免不确定结果重复执行。
- Agent 执行上限 120 秒。graceful shutdown 取消事件 task 并记录 interrupted；进程硬崩溃后的
  `running` reservation **不自动过期**（避免长运行 lease 到期重复执行）。操作员先确认原进程已停止，
  再在独立事件库把残留 state 改为 `interrupted`，可释放并发名额；需要重试使用新的 delivery id。
- 去重库不自动清理，保留跨重启去重；长期部署需要操作员按保留策略管理磁盘。
- GitHub 标准签名不绑定 delivery header，无发送时间戳；不能承诺对已捕获签名 body 换 id 的防重放。
  TLS、网关限流、保护 secret 必需。告警协议通过签名绑定 id/时间戳规避此问题。

## 本地便宜心跳检查

现有 `heartbeat.md` 可以包含远程轮询/周期目标，不能仅看它是否改动就抑制执行。
**没有检查 manifest 时保持原来的周期执行**，画像压缩、午夜沉淀、watchdog、skill 更新等不变。
对确实以本地文件变化为条件的任务，可由操作员创建 `<workspace>/system/heartbeat-checks.json`：

```json
{"paths":["inbox/state.json","/absolute/path/to/local/signal.json"]}
```

该 manifest 覆盖整个 heartbeat.md 任务集合；仅在这些文件变化足以代表所有任务的唤醒条件时使用。
纯时间目标/远程邮件/飞书/日历任务不能仅使用此 gate，否则会错过外部变化。

每轮先比较 manifest、heartbeat.md 内容、1–32 个常规本地文件的
inode/size/mtime_ns/ctime_ns。不调 LLM、不执行脚本、不访问网络、不递归扫描。
首次执行兼容，成功运行后提交指纹；无变化直接跳过 Agent，失败不会提交，下一轮重试。
manifest ≤16 KiB；缺文件、非法 JSON、目录等检查失败时 warning 并回退原周期执行，不静默吞任务。
状态只存在进程内，重启后再次首次执行；stat 检查不是内容 hash，不适合刻意保留全部元数据的修改。

`ethan.scheduler.heartbeat.Heartbeat.register(callback, change_check=...)` 同样支持可选廉价本地 predicate；
旧 callback 行为不变，False 跳过、检查异常记录并 fallback。调用方应确保 predicate 不调用模型。
系统心跳依然落库 `source=heartbeat` 和 usage，新增 owner/session ContextVar 设置并恢复，方便按来源统计。

## 验证

独立测试使用临时库、测试自有 HMAC 和假 provider；隔离单测使用假 Agent，集成回归运行真实
Agent 构造、路由与 stream loop，不调用真实模型，不接生产账号，不启动或 kill 服务：

```sh
ETHAN_NO_WATCHDOG=1 PYTHONPATH="$PWD" /path/to/main/.venv/bin/python -m pytest \
  tests/test_event_triggers.py tests/test_heartbeat_changes.py tests/test_heartbeat_session_naming.py -q
```

覆盖默认关闭、专用 secret、HMAC tamper、schema/仓库白名单、body 超限（含无 Content-Length）、
跨实例持久去重、并发 claim、rate/concurrency 限流、事件 owner/session 隔离、无工具与数据/策略隔离，
以及心跳首次/无变化/变化/检查失败 fallback/旧任务兼容。
真实 Agent 集成还验证空工具广播、payload 不进入 system、usage/正文落库、delivery 完成状态与
单条 assistant 进度行复用（绑定当前运行检查点接口，避免重复空消息）。

在独立 `feature/event-triggers` worktree、main 基线 `19fd224d` 上运行上述命令：**21 passed**；
对应修改文件 ruff 与 `git diff --check` 通过。仅使用本 worktree 的 `PYTHONPATH` 和主仓库现有解释器，
不叠加其他 worktree 代码。线上 token 节省未测，不能视为收益验收。
