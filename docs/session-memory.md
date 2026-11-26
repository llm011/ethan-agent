# 会话首轮记忆

原生 Ethan 的新 owner 会话在首次非 minimal/instant 请求前，用现有规则与本地记忆库
召回个人上下文。不会新增模型分类或重排请求。restricted 与 companion 域隔离仍由现有
召回模块执行，Agent user_id 必须与当前 profile ContextVar 一致。

快照以独立 user **数据**消息置于模型的 System Prompt 之后、对话历史之前，带固定时间戳、
规范模式与“非指令”标签；JSON 内容不取得 system 权限。System Prompt 本身不改写。
最多 6000 字符；空召回也记一次。取消照常传播，读取失败回退按需 `recall_memory`。

`sessions.db.session_memory_snapshots` 按 session/mode 保存不可变快照；重启或下一次请求
重用相同字节，不重新召回、更新时间戳或改写已经发出的前缀。短事务只提交自己的连接，
并发首请求以已提交的胜者为准。正常删除 session 时外键级联清理。

已有完成 assistant 的会话不补插快照；新请求的空 running 占位不视为旧会话。
模式改变不得重用 companion 快照。快照属于合成上下文，极简回复兜底不会把它当作
用户的原始任务。追问仍可使用 `recall_memory` 获取更新或更精准的信息。

验证：`tests/test_session_memory.py` 覆盖首次/重用/空召回/权限/模式/占位及真实
Agent chat/stream 集成；个人早餐 fixture 中假模型第一轮即读到偏好回答，无 recall 工具往返。
`tests/test_session_memory_followup.py` 另覆盖 chat/stream 同 session 的真实 owner 路由注入、
自动 checkpoint 与临时 SQLite 完成消息/历史重载：早餐首轮 local recall 一次、工具零次；
换到快照不含的出行偏好后，显式只读 recall 成功一次，首轮快照字节/时间戳不变、local 不重召回。
该确定性 provider stub 证明后续工具没有被禁用，不证明真实模型会正确选择工具。
这证明机制与固定案例，不代表已完成生产个人问答质量 A/B 或线上成本测量。

## 有限合成 A/B probe

`scripts/probe_session_memory_ab.py` 默认离线，使用真实 Agent chat/stream、临时 SessionStore
与假 provider，只覆盖早餐、出行、学习三个合成 fixture；不读取生产记忆或写生产 DB/config。
报告保留 `mode=dry_fake/live`，另在顶层、每个 row 和 pair 标注 `baseline_mode`：

- `controlled`（默认）：A 关闭快照并强制首次只读 `recall_memory`；B 正常准备快照。
  已记录的三题合计9次真实调用（A6/B3、均score2）仅证明该受控对照，不证明自然工具选择质量。
- `natural`（显式选择）：A 只关闭快照，不强制首次召回；B 正常准备快照。
  A/B 使用相同可见只读工具、合成 System 策略及 provider 默认采样，不隐藏 B 工具。
  该共同策略仍要求缺偏好时召回，因此只是此合成策略下的非强制工具选择，不等于生产自然对话。
  A 不召回且不知道偏好时，按原样输出接受严格 rubric 的失败，不注入偏好、不补答或隐式重跑。

离线命令（不产生真实模型请求）：

```bash
uv run python scripts/probe_session_memory_ab.py
uv run python scripts/probe_session_memory_ab.py --baseline-mode natural
# 可选 --transport chat 或 --transport stream；离线默认两种均验证。
```

假 provider 在缺少偏好时确定性选择召回，dry/stub 通过仅证明接线、模式与门禁；natural
真实测量的失败见下方，不宣称质量验收通过。只有另行授权显式 `--live --baseline-mode natural` 才请求当前
实际配置的默认 OpenAI-compatible gateway/model（仅 chat），不切 route/账号、不改配置、
不使用 fallback 或 SDK/应用层隐藏重试。每 case/arm 最多3次模型调用，每次最多768输出 token，
`--timeout` 每 case/arm 必须在 `(0, 180]` 秒内；三个 fixture 两个 arm 总计最多18次请求。
流式 live 被拒绝，因为当前 provider API 无法保证同一输出 token 上限。

严格有限候选 rubric 不使用 LLM judge，不剥离 think/code fence 来伪造通过；自然 A 的失败必须
保留。总体 `passed` 仍要求 A/B 均通过、B score 不退步、B 无额外 recall 且模型调用数不增加；
即便 B 完美、费用相等，也不会掩盖 A 的失败。B 零额外 recall 门禁只针对这三题的首轮完整偏好
快照，不限制后续换话题按需召回。只报告匿名格式/计数/usage/耗时，不保存输出或推理。
这些门禁只衡量本 probe 的调用计数与固定题输出，不证明真实账单降低、生产安全性或持续质量。

### 自然模式真实测量（2026-11-26 13:10，未通过）

PR #504 squash `d67fc2e7`；root 在固定代码 `d2675903651ca999b89dbbb6c31fa4a4912ca054`
上用当前配置 `buddy-proxy/deepseek-v4.1-flash` 执行唯一一轮 live/chat 六臂，120秒/臂、最多3 calls/臂、
768 tokens/call，共10次真实请求，exit1。匿名报告 `session-memory-ab-natural-live-20261126.json`
SHA256 `366b2a3baf39f154879b49c8b676a6408e8d5ecf05a14f6678f546f4f0a45dd9`。
按早餐/出行/学习顺序，A score=[2,2,0]、7 calls/4 tool recall/0 local recall，
B score=[2,2,2]、3 calls/0 tool recall/3 local recall，每题快照持久一次；整体 `passed=false`。
学习A为3 calls/2 recall、facts_exact=false/plan_safe=false；其余五臂通过。
六臂均JSON可解析、无think/code fence、无调用错误；未保存答案，学习失败具体原因未知，不推测因果。
A input/output=3,570/819，B=1,667/930；输入下降53.3%但输出增加13.6%，不证明所有token节省、
真实账单降低、生产自然质量或三天收益；原controlled输入3,119/1,667与本次分开记录。
不重跑、不放宽rubric或隐藏自然A失败；工具功能通过不等于自然质量通过。
新增功能focused 74项通过（3.29s），含两项chat/stream非空首轮快照的后续换题回归：真实owner路由、
自动checkpoint、公共SessionStore final-save/历史重载（非完整渠道producer），local1/tool0→local仍1/tool1，
旧快照内容/时间戳不变，新偏好仅来自显式工具结果；确定性stub只证明可用性，不证明模型会正确选择。
