# Agent Loop 与上下文优化计划

> 建立：2026-11-25。基线：main `281f4ee5`（v1.0.0b36）。状态见文末「进度记录」。
>
> 本文是**执行计划 + 证据台账**。标「已验收」的条目必须有实测数据或测试支撑，
> 不写推测数字（教训见 `optimization-plan.md` 顶部警告：那份计划里的效果数字是目标推测，
> 不是实测）。行号以基线为准，改动后会漂移，定位时以符号名为准。
>
> `optimization-plan.md` 是历史规划文档，本计划接替它；其中「长程任务 / 断点续传 /
> 任务状态持久化」一直未落地，对应本计划的条目 6。

---

## 1. 来源

对照了三份外部材料，逐条回到代码和数据库里核实：

- **DeepSeek Super Agent 的 Agent Loop 材料**（七步循环、承接语两条路线、Harness 2.0 的
  三个动作、主子 Agent 架构）。
- **AgentMesh：跨平台多 Agent 通信协作最佳实践**（EventHub、AgentHub、Super Team、CLI）。
  这是跨平台协作基础设施，对单用户的 Ethan 只有「工作项持久化」和「事件触发」两点相关。
- **DeepSeek Thinking Mode 文档**：带 `tools` 的请求必须回传 `reasoning_content`，否则 400。

结论：循环骨架（并发执行、自然结束判断、特殊工具短路、有界收尾）我们是齐的。
真正的问题在**上下文的稳定性**、**协议回传**、**续跑状态**三处。

---

## 2. 实测基线（2026-11-25）

数据来自 `~/.ethan/db/sessions.db`（注意 `~/.ethan/sessions.db` 是废弃的旧库）。
`messages.usage` 是 JSON：`input` = prompt_tokens 总量，`cache` = 其中命中缓存的 token
（口径见 `ethan/providers/_responses.py::parse_usage`）。

| 指标 | 数值 |
|---|---|
| 近 7 天输入 token | 3.50 亿，缓存命中 3870 万（11.1%），未命中 3.11 亿 |
| 按来源 | schedule 3.447 亿（11 个会话 / 78 次运行）；api 470 万；web 60 万；dsh ≈ 0 |
| 模型 | 近 7 天全部 `deepseek-v4.1-flash` |
| 每次请求输入 | 约 10 万 token 量级 |
| 工具调用 | 4006 次，报错 27 次（0.7%）；`shell` 78%，文件读写 16% |
| 工具面 | 注册 67 个；`full` 档初始广播 39 个 / 3.82 万字符；`fast` 档 15 个 / 0.98 万字符 |

烧得最多的定时任务（7 天）：

| 任务 | token | 每次步数 | 命中率 |
|---|---|---|---|
| 论文深度解读（每日 17:47） | 7000 万 | 107 | 10.5% |
| 今天笔记汇总推送 | 5800 万 | 72 | 0.1% |
| 书籍深度听书生成 | 5300 万 | 75 | 15.6% |
| EigenFlux 每日简报订阅 | 4420 万 | 58 | 0.0% |
| EigenFlux 早间简报 | 4380 万 | 64 | 33.4% |
| EigenFlux 晚间简报 | 4040 万 | 65 | 0.0% |

命中率是**双峰**的：生效的运行 92%–96%；失效的运行 0%–0.8%，包括最大的几次
（141 步 / 1368 万 token，0%；88 步 / 1120 万 token，0.8%）。

### 复测方法

```sql
-- 总览（近 7 天）。在 shell 双引号里要把 $. 写成 \$. ，并用 sqlite3 -readonly 打开
SELECT count(*), sum(json_extract(usage,'$.input')), sum(json_extract(usage,'$.cache')),
       round(100.0*sum(json_extract(usage,'$.cache'))/sum(json_extract(usage,'$.input')),1)
FROM messages
WHERE role='assistant' AND usage IS NOT NULL AND json_valid(usage)
  AND json_extract(usage,'$.input') > 0
  AND created_at > strftime('%s','now') - 7*86400;

-- 按来源 / 按定时会话：把 GROUP BY 换成 s.source 或 s.id
SELECT s.source, count(DISTINCT s.id), count(m.id),
       round(sum(json_extract(m.usage,'$.input'))/1e6,1),
       round(100.0*sum(json_extract(m.usage,'$.cache'))/sum(json_extract(m.usage,'$.input')),1)
FROM sessions s JOIN messages m ON m.session_id = s.id
WHERE m.role='assistant' AND m.usage IS NOT NULL AND json_valid(m.usage)
  AND json_extract(m.usage,'$.input') > 0 AND m.created_at > strftime('%s','now') - 7*86400
GROUP BY 1 ORDER BY 4 DESC;

-- 工具报错率
SELECT json_extract(s.value,'$.tool'), count(*), sum(json_extract(s.value,'$.state')='error')
FROM messages m, json_each(m.tool_steps) s
WHERE m.role='assistant' AND m.created_at > strftime('%s','now') - 7*86400
GROUP BY 1 ORDER BY 2 DESC;
```

---

## 3. 问题台账（均已到代码里核实）

### P1 预算淘汰不断改写已发出的内容，缓存失效 【影响最大】

- `ethan/core/context_budget.py`：`MAX_TOOL_RESULT_CHARS = 20000`、`CONTEXT_BUDGET_CHARS = 100000`
  （注释写明是给 20 万窗口留余量）、`EVICTED_STUB_CHARS = 600`。
- `enforce_context_budget()` 在每批工具结果进上下文后执行（`agent.py` 的 `chat()` 与
  `stream_chat()` 各有循环内和入口两处调用）。合计超过 10 万字符时，把最近 3 条以外的旧结果
  改写成 600 字摘要，大块优先。
- `shell` 和 `file_read` 都是 `no_compress` 且出口不截断（`shell.py`、`file.py` 里均有
  「不截断，原样进 context」的注释），大结果原样进来。
- 机制模拟（用真实的 `enforce_context_budget`，40 轮，每轮追加一条工具结果）：

  | 每条结果 | 改动前缀的轮数 | 前缀稳定占比 |
  |---|---|---|
  | 约 1.5K 字 | 0 / 40 | 100% |
  | 约 6K 字 | 24 / 40 | 27.2% |
  | 约 12K 字 | 32 / 40 | 12.9% |

  12.9% 与实测 11.1% 吻合；任务类型固定 → 结果大小分布固定 → 同一定时任务命中率稳定，
  也和双峰现象一致。
- **没有直接证据的部分**：淘汰路径没有日志，无法逐次运行证明零命中的运行就是大结果运行。
  另外凌晨 0 点有几次 4 步的小运行也是零命中，此机制解释不了，未解。

### P2 提示词分层不干净

- `docs/caching.md`：`Current time:` 是 Anthropic provider 的缓存分割点
  （`ethan/providers/anthropic.py::_split_system_for_cache`），之前是稳定层。
- 但 `fast` 档（`system_prompt.py`）分割点之后还有 `_documents_protocol()`、
  `_INTENT_SYSTEM_INSTRUCTION`、`memory_recall_hint`、`<user_profile>`、
  `<behavioral_guidelines>` 这些稳定内容；`full` 档分割点之后有后三个。
- `config.py` 默认 `base_tools` 里有 4 个 `agenda_*`，对应工具没有注册，被静默过滤。
  **核实修正（2026-11-25）**：此描述只在 `tools.agenda.enabled` 默认 False 时成立。agenda 工具
  在 enabled=True 时**确实注册**（`agent_factory.py:208`），且 `base_tools` 是广播白名单
  （`agent.py:369-370`，`t.name in wanted`）——删掉后启用日程的用户将看不到这些工具，
  与 `config.py:214-215` 注释「日程页开关打开后工具注册即广播」的设计意图冲突。
  **结论：保留 `agenda_*`，不删除**；本条目不做，已向用户确认。

### P3 `reasoning_content` 没有回传

- `agent.py::_pump`（`stream_chat` 内的闭包）只把 reasoning 转成 `ThinkingEvent` 往外吐，
  从不累积；组装回填消息时是 `Message(role="assistant", content=..., tool_calls=...)`，没带 reasoning。
- 所以 `_transform.py` 里回传 `reasoning_content` 的分支在循环内是空转的。
- `_wants_reasoning()` 靠模型名匹配 `deepseek-r1` / `deepseek-reasoner`，新模型匹配不上。
- 库里真发生过一次：2026-09-02 22:27，`deepseek-v4-flash`，interrupted，
  `The reasoning_content in the thinking mode must be passed back to the API`。之后没再出现。

### P4 状态补偿只在「卡住」时触发；已输出内容不去重

- `ethan/core/loop_control.py::LoopMonitor.is_stuck()`：连续同签名报错或精确重复才触发反思。
  单次工具失败没有任何补偿，只把错误塞进 tool result。
- 决策提示是定时的（第 3 轮起每 3 轮），不是按状态。
- `ethan/core/stream_collector.py` 把各轮 content 全部拼接，没有去重；工具失败后模型重说一遍
  过渡语，用户会看到两次。

### P5 续跑只有摘要；后台任务不持久

- `system_prompt.py::build_previous_run_summary()`：续跑时只从上一条 assistant 消息的
  `tool_steps` 生成摘要（预览上限普通 100 字、失败步骤和最后两步 250 字）。
- 历史消息回到 API 时不还原 tool 调用和结果（全仓库只有实时循环和 `task_fanout` 构造 `role="tool"`）。
- `ethan/tools/builtin/background_task.py`：任务登记在模块级 `_REGISTRY`，进程重启即失效。

### P6 循环函数过长且重复

- `ethan/core/agent.py` 2200 行；`stream_chat()` 单函数约 1100 行；`chat()` 里有一份几乎相同的逻辑。
- 仓库规则是单文件 700 行以内（超 1000 行必须拆）。

### P7 信息供给

- `ethan/tools/builtin/recall_memory.py`：记忆从「首轮无条件召回」改成了按需工具，
  需要个人上下文时多一个来回，且依赖模型自己判断。
- 路由是关键词二分（`routing.py`、`agent.py::_select_route`），没有按信号强度分级。

---

## 4. 已核对、无需处理

- **后台任务的权限边界**：`BackgroundTaskTool.side_effect = True`；飞书渠道对非主人安装
  `ChannelGuardProvider(is_owner=False)`，所有副作用工具直接拒绝，非主人发起不了后台任务。
- **工具选择难度**：广播 39 个工具，报错率 0.7%，没有证据表明选择难在造成损耗。
  `find_tools` 已把 28 个长尾工具挡在初始集外。
- **承接语**：走的是结构化路线（工具调用的 `intent` 参数 + 前端工具时间线 / 飞书进度气泡），
  不需要让主模型写自由文本。
- **循环骨架**：工具并发（`ToolExecutor.execute` 用 `asyncio.gather`）、自然结束判断、
  `decide` 拦截 / `ask_user` / `wait_for_user` / consent 拒绝等短路、三类 finalize 收尾都在。

---

## 5. 计划

每条独立成 PR，走 `dev-pr` 流程。顺序即优先级。

### 阶段一：缓存与稳定前缀

#### 条目 1 入口定稿，停止改写已发内容（对应 P1）

目标：长运行里工具循环的前缀逐字节稳定；抓取类定时任务命中率从 0%–15% 到 80% 以上。

按风险从小到大依次做，每步都跑模拟测试，达标就停：

1. **淘汰可观测**：`enforce_context_budget` 淘汰分支加 warning 日志（当前没有）。
2. **低水位淘汰**：触发时一次降到预算的 50%。现在刚好降到线上，下一条结果进来又触发，
   改成偶发的成批改写。
3. **预算按模型窗口缩放**：用 `effective_input_budget()` 推导，不再写死 10 万字符。
4. **入口定稿**（前三步不达标才做）：`shell` / `file_read` 超过阈值的结果，全文落到会话
   临时目录（沿用 `web.py` 超过 8000 字落盘的做法），上下文里保留**逐字开头 + 文件路径 + 总字数**。
   不写摘要：两处注释都写明摘要会丢 `entity_id`、导致模型反复重读。

验收：
- 新增单测：模拟 40 轮、每条 12K 字，改动前缀 0 次。
- 现有 context budget 相关测试、`ruff` 通过。
- 上线 3 天后复测：抓取类定时任务命中率 ≥ 80%；工具报错率 ≤ 1%（基线 0.7%）；
  大结果运行的平均步数没有明显上涨（入口定稿后模型可能多一次读文件）。

涉及：`ethan/core/context_budget.py`、`ethan/core/agent.py`（两处循环内调用点）、
`ethan/tools/builtin/shell.py` 与 `file.py`（仅第 4 步）、`tests/`。

#### 条目 2 提示词按「稳定 / 每轮变化」重排（对应 P2）

约束：**`Current time:` 必须保住分割点的性质**，之前全部是对话内稳定的块，之后全部是每轮或每次变化的块。

改动：
- 把 `_documents_protocol()`、`_INTENT_SYSTEM_INSTRUCTION`、`memory_recall_hint` 移到分割点之前。
- `<user_profile>`、`<behavioral_guidelines>` **先核实变更频率再决定**：`caching.md` 把它们
  归为动态层并称「每轮都会变化」，但它们只在用户或模型更新时才变。确认是准静态后移入稳定层。
- `<relevant_skills>` / `<matched_skills_brief>` / `mode_hint` / `<memory_signal>` /
  `<runtime_context>` / `<previous_run_summary>` 留在分割点之后。
- 清掉 `config.py` 默认 `base_tools` 里 4 个未注册的 `agenda_*`。
- 同步更新 `docs/caching.md` 的分层图。

验收：`uv run pytest tests/test_prompt_budget.py -q`、
`.venv/bin/python -m tests.bench_prompt_size` 通过；新增单测断言分割点两侧的块。

涉及：`ethan/core/system_prompt.py`、`ethan/core/config.py`、`tests/`、`docs/caching.md`。
`ethan/providers/anthropic.py::_split_system_for_cache` 只读确认分割方式。

#### 条目 3 定时任务成本报表（可选）

在定时任务接口和页面展示每个任务的运行次数、输入 token、命中率、平均步数。
上面那张表现在是手查库得到的，做成页面才能自己判断哪些任务值得跑。
验收：页面数字与第 2 节的 SQL 复测一致。

### 阶段二：循环健壮性

#### 条目 4 `reasoning_content` 回传（对应 P3）

- `_pump` 累积 reasoning，组装回填消息时带上。
- 协议判定改成看响应里是否出现 `reasoning_content`（模型名匹配保留为补充），不再只靠名字。
- 历史消息的 reasoning 回传与 DeepSeek 规则对齐（带 `tools` 时所有历史轮都要回传）。
- 验收：加一个「缺 reasoning 就报 400」的假客户端回归测试；经网关对 `deepseek-v4.1-flash`
  跑一次两步工具调用不报 400。

#### 条目 5 按状态补偿，加已输出去重（对应 P4）

- 工具报错后给一次针对性提醒，不等连续失败。
- 记录本轮已输出的过渡语，重复的不再展示；`StreamCollector` 去重。
- 验收：单测覆盖「失败一次即提醒」「重复段落去重」。

#### 条目 6 运行检查点（对应 P5，同时落地 `optimization-plan.md` 里没做的断点续传）

- 每次迭代把目标、已完成步骤（工具 + 参数摘要 + 结果摘要）、待办、产物落库。
- 「继续」时读检查点，不再只靠 `tool_steps` 摘要。
- 后台任务持久化，重启后能重新挂上。
- 验收：运行中途杀掉服务，「继续」能带着结构化上下文接上；重启后后台任务列表还在。
- 同步 `docs/background-tasks.md`、`docs/agent-loop.md`。

#### 条目 7 循环拆分（对应 P6）

- 按七步循环把 `stream_chat()` 拆成小函数，消除 `chat()` 的重复，单文件压到 700 行以内，
  对外接口不变。
- 先补关键路径测试（空响应 nudge、三类 finalize、决策拦截、运行中补充），再动代码。
- 单独 PR，不改行为。同步 `docs/agent-loop.md`。

### 阶段三：信息供给与事件

#### 条目 8 会话级记忆提醒（对应 P7）

新会话首轮注入一次，单独成条、放在 System Prompt 之后、带时间戳；`recall_memory` 保留给追问。
依赖条目 1（缓存能用，前置才划算）。验收：少掉一轮召回往返，需要个人上下文的问答不退步。

#### 条目 9 分级路由（对应 P7）

按信号强度决定档位；强信号（如命中 Skill 触发词）时提前装好 Skill 和记忆。
同步 `docs/routing.md`。

#### 条目 10 事件触发（候选，等用户确认场景后再排期）

- 入站 webhook：GitHub / CI / 告警事件直接发起一次运行。
- 条件触发：心跳现在每 15 分钟醒一次（`config.yaml` 的 `heartbeat.interval_minutes`），
  改成先用便宜检查判断有没有变化，有才唤醒模型。
  心跳在 token 消耗里占多少还没测（按来源分组里没有出现 heartbeat 来源，原因待查）。

---

## 6. 明确不做

| 不做 | 理由 |
|---|---|
| 主子 Agent 并行（快脑表达 + 慢脑执行） | 对方实验后也没全量上线；首包没有事实依据，回注难做干净，成本翻倍 |
| 承接语两条路线（常驻提示 / 旁路小模型） | 我们已有结构化进度反馈，不污染回复正文 |
| 工具收敛成三个入口 | 那是只有三种职责的产品；我们是通用编码助手，合并会糊掉参数和执行边界 |
| AgentHub 式注册委派、A2A、Super Team 多 Agent 编排 | 单用户没有场景；Ethan 已有 `delegate_coding`、`task_fanout` 和外部内核委派 |

---

## 7. 约束与工作流

**本机实际参数**（`dev-pr` 技能表格里的路径是旧机器的）：

- 主仓库 `/Volumes/SSDExt/code/life/ethan-agent`，远端 `llm011/ethan-agent`，始终停在 `main`。
- worktree 放同级目录 `ethan-ai-<kebab>`，分支 `feature/<kebab>`。
- 健康 `http://127.0.0.1:8989/api/health`；重启 `ethan server restart`。
- 合并：分支策略要求的状态检查名对不上，`gh pr merge` 需要 `--admin`；**不要加 `--delete-branch`**。

**环境**：macOS 没有 `timeout` 命令；Python 用 `.venv/bin/python` 或 `uv run`；
查库用 `sqlite3 -readonly`，只取聚合数字，不输出消息内容。

**验证**：改动后至少跑 `uv run pytest tests/test_prompt_budget.py -q` 和相关测试、
`uv run ruff check <改动的文件>`。纯后端改动重启即生效；Web 改动要 `pnpm build:web`
并替换 `ethan/web_dist`；桌面端改动要等下次打 tag 发版。

**文档**：`README.md` 与 `README_CN.md` 必须同时改；功能变化后检查 `docs/` 对应章节。

**AOCI**：`aoci_*` MCP 工具在建立本计划的会话里没有挂载，索引维护做不了，收尾时如实说明；
工具可用时按 `AGENTS.md` 在最终稳定状态调一次 `aoci_maintain`。

**提交**：小改动（≤2 个文件且 diff ≤50 行）可直接上 `main`，其余走 worktree + PR。

---

## 8. 条目 1 的待核实项（动手前先确认）

- [x] 现有的 context budget 测试文件名与覆盖范围（`tests/` 下搜 `context_budget`）。
  → `tests/test_context_budget_images.py`（images 透传）、`tests/test_context_limit.py`（全量输入预检）。
  无直接覆盖 `enforce_context_budget` 前缀稳定性的测试，本次新增 `test_context_budget_stability.py`。
- [x] `effective_input_budget()` 的口径（字符还是 token，按路由怎么取值）。
  → 字符，= `upstream_limit()`(默认 997952) × (1 - margin_pct()/100)（默认 5% → 948054）。
  可被 `ETHAN_MAX_INPUT_CHARS` / `ETHAN_INPUT_LIMIT_MARGIN_PCT` 覆盖；==0 关闭预检。
  工具预算 = 它 × 10%，夹在 [30000, 200000]；env `ETHAN_TOOL_BUDGET_CHARS` 可显式覆盖。
- [x] `compress_previous_round_tools()` 与淘汰的交互：它只压「最后一个 assistant 消息之前」的
  search / fetch 结果，实时循环里是否也会改写已发内容。
  → 确认：它也在每轮循环内调用（agent.py 循环内 + 入口两处），改写已发出的 web_search/web_fetch
  结果。web_fetch 结果它自己落盘成文件指针（已带 marker，幂等），不会反复改写；web_search 压成
  title+url 列表（带 marker，幂等）。**已落盘（入口定稿 marker）的消息也需被它跳过**——
  本次入口定稿 marker `_OFFLOADED_MARKER` 独立于它的 marker，不冲突；且它只处理
  web_search/web_fetch，入口定稿处理 shell/file_read，工具名不同，互不覆盖。
- [x] `web.py` 落盘的目录约定和标记文案，入口定稿沿用同一套（`/tmp/ethan/<session_id>/`）。
  → web.py 自身落盘到 `/tmp/web_fetch_*.md`（非会话目录），但 `compress_previous_round_tools`
  的 `_offload_fetch_content` 用 `/tmp/ethan/<session_id>/<tool_call_id>.md`。入口定稿沿用后者
  （会话目录，便于按会话清理），文件名 `<tool_call_id>.md`，幂等（同名覆盖）。
- [x] 小窗口模型（lite / fast 档）下预算缩放后的安全上限。
  → 经 `ETHAN_MAX_INPUT_CHARS` 收窄上游后，工具预算同步缩小，但 `TOOL_BUDGET_MIN_CHARS=30000`
  兜底，不会小到一上来就把所有结果压成 stub。lite 档通常不跑长工具循环，影响有限。

---

## 9. 进度记录

每项写清日期和状态：`未开始` / `进行中` / `已实现` / `已验收（附数据）`。

### 阶段二总结（2026-11-26）

历史阶段曾记录条目 4/5/6 已实现并合并上线（服务 v1.0.0b41），条目 7 部分完成。
**本轮源码复核修正：#485 只有内存快照与中断异常时保存，不满足每轮/派发前持久化，
#483 也未覆盖真实 UI 持久化后下一请求的逐轮 reasoning 配对。不能视为两项完整验收。** 四个历史 PR：

| 条目 | PR | 核心改动 |
|---|---|---|
| 4 `reasoning_content` 回传 | #483 | 流式累积 reasoning、非流式读取、证据驱动回传判定 |
| 5 状态补偿 + 去重 | #484 | 单次工具失败即提醒、StreamCollector 短文本去重 |
| 6 运行检查点 | #485 | 后台任务落库跨重启可见、`run_checkpoint` 精确续跑 |
| 7 循环拆分（部分） | #486 | 拆出 `reply_quality`（agent.py 2239→2092）、补关键路径测试 |

顺手修掉的既有缺陷：
- 条目 1 遗漏：`stream_chat` 循环内 `enforce_context_budget` 漏传 `session_id`，流式主路径不落盘（#484 修）。
- 条目 4 自审：同轮重试未重置 `round_reasoning` 导致 reasoning 重复累积（#483 内修）。
- 条目 6 自审：`list_tasks` 对已结束任务用 `now - started_at` 算时长会持续增长（#485 内修）。

⏳ 待线上验证（部署后观察）：
- 条目 4：经网关对 `deepseek-v4.1-flash` 跑两步工具调用不报 400；
- 条目 1+2：定时抓取类任务缓存命中率是否达 ≥80%；
- 条目 6：后台任务跨重启列表与「继续」按钮的实际体验。

- [x] 条目 1 入口定稿与预算淘汰 — 已实现（2026-11-25，工作区 `ethan-ai-context-cache`，分支 `feature/context-cache`）。
  实测（`tests/bench_context_budget_stability.py`，40 轮模拟）：

  | 每条结果 | 基线（改写前缀轮数 / 稳定占比） | 实现后（改写前缀轮数 / 稳定占比） |
  |---|---|---|
  | 1.5K 字 | 0 / 100% | 0 / 100% |
  | 6K 字 | 24 / 40% | 3 / 92.5%（低水位兜底，<8K 不落盘） |
  | 12K 字 | 32 / 20% | **0 / 100%**（入口定稿落盘） |

  验收项：
  - ✅ 单测 `tests/test_context_budget_stability.py::test_40_rounds_12k_zero_prefix_mutation`：40 轮 × 12K 字，前缀改写 0 次。
  - ✅ 现有 `test_context_budget_images.py` / `test_context_limit.py` 通过；`ruff` 通过。
  - ⏳ 上线 3 天后复测命中率（条目 1 的线上验收，需部署后补数据）。
  - 说明：第 4 步（入口定稿）已做，因为前三步 12K 仍有 8 轮改写、达不到 0 次；落盘后归零。
- [x] 条目 2 提示词重排 — 已实现（2026-11-25，同一 PR）。
  - ✅ 准静态块（`documents_protocol` / `_INTENT_SYSTEM_INSTRUCTION` / `memory_recall_hint` /
    `<user_profile>` / `<behavioral_guidelines>`）移入 `Current time:` 分割点之前（稳定层），
    fast/full 两档均已重排。
  - ✅ `agenda_*` 保留不删（核实后发现计划描述有误，见 P2 核实修正，已向用户确认）。
  - ✅ 单测 `tests/test_prompt_cache_layering.py` 断言分割点两侧块归属 + 无块跨两侧重复。
  - ✅ `tests/bench_prompt_size` 体积未涨（TOTAL 40864 ≤ 55000），`ruff` 通过。
  - ✅ `docs/caching.md` 分层图同步更新。
  - ⏳ Anthropic provider 路径的线上命中率收益需部署后观察（当前生产模型是 deepseek-v4.1-flash，
    走 OpenAI 兼容协议不做 prompt cache 分割；本重排对 deepseek 的「自动缓存」同样利好——
    前缀更稳定，见条目 1）。
- [ ] 条目 3 定时任务成本报表 — 未开始（可选）。本次先做条目 1+2；报表涉及双端前端（Web + Desktop），
  工作量较大，待条目 1 线上复测数据出来后再排期。
- [x] 条目 4 `reasoning_content` 回传 — 已实现（2026-11-25，工作区 `ethan-ai-reasoning`，分支 `feature/reasoning-backprop`）。
  修复三处：
  - 流式 `_pump`（agent.py）累积 reasoning 到 `round_reasoning`，回填 assistant Message 时带上（此前只转 ThinkingEvent 往外吐、不累积，回填消息丢 reasoning）。
  - 非流式 `parse_choice`（`_responses.py`）读取 `message.reasoning_content` 挂到 Message（此前根本没读，Message.reasoning 总为 None）。
  - 协议判定新增证据驱动 `_history_carries_reasoning()`：最近一条 assistant 带 reasoning 即回传历史，不再只靠模型名匹配 `_wants_reasoning()`——覆盖 `deepseek-v4.1-flash` 等模型名表之外的 reasoning 模型。切到普通模型后最近一条无 reasoning → 不回传，避免污染新端点。
  验收：`tests/test_reasoning_backprop.py` 覆盖 parse_choice 挂 reasoning、证据驱动判定、序列化回传、以及「缺回传即抛 DeepSeek 400」的假客户端回归（禁用修复后该测试红，证明能抓 bug）。`ruff` 通过。
  - ⏳ 经网关对 `deepseek-v4.1-flash` 跑一次两步工具调用不报 400 的线上验证待部署后补。
- [x] 条目 5 状态补偿 + 去重 — 已实现（2026-11-25，工作区 `ethan-ai-loop-robust`，分支 `feature/loop-robust`）。
  - **按状态补偿（单次失败即提醒）**：新增 `loop_control.tool_error_hint()`；agent 主循环
    （`chat` / `stream_chat` 两处）在 `had_error` 且未触发 `is_stuck` 时，把轻量针对性提醒
    附到下一轮 system 的 `pending_suffix`，引导模型先判失败原因、换路而非原样重试。
    连续失败由 `is_stuck` 的 `reflection_message` 接管（覆盖 pending_suffix），两者不冲突。
  - **已输出去重**：`StreamCollector` 维护最近 5 个短文本块（≤200 字）窗口，与窗口内某块
    完全相同（strip 后相等）的过渡语不再累积到 `full`、也不返回展示——修掉工具失败后模型
    重说一遍过渡语、用户看到两次的问题。长文本 / 不同短文本不受影响；窗口外旧块重现放行。
  - 顺手修了条目 1 的遗漏：`stream_chat` 循环内 `enforce_context_budget(working)` 漏传
    `self.session_id`，导致流式主路径不落盘（已补传）。
  验收：`tests/test_loop_robust.py` 覆盖 tool_error_hint 文案、collector 去重（5 种情况）、
  以及 agent 级端到端「单次失败→下一轮 system 带提醒」。`ruff` 通过，69 项相关测试无回归。
- [x] 条目 6 运行检查点 — 已实现（2026-11-26，工作区 `ethan-ai-checkpoint`，分支 `feature/run-checkpoint`）。
  两部分：
  - **后台任务跨重启可见**：新增 `background_tasks` 表（sessions.db）+ SessionStore CRUD；
    `background_task` 创建即落库、终态（done/error/stopped）更新结果。daemon 线程不能复用
    aiosqlite 连接（跨线程），用短生命周期 sqlite3 同步连接写（`_persist`，失败只记日志不中断任务）。
    启动扫描把残留 `running` 标 `interrupted`（daemon 线程已死），session 里已生成的部分结果保留。
    `list_tasks()` 合并内存 `_REGISTRY` 与持久化历史（内存状态覆盖同 id）。
  - **运行检查点/断点续跑**：新增 `messages.run_checkpoint` 列 + `save/load_run_checkpoint`。
    agent 每轮工具执行后更新 `_run_checkpoint`（当前轮次、最后工具、是否失败、最近签名）；
    中断落库时（producers.py）写入该行；`/chat/resume` 读回并注入 `runtime_context`，
    告诉模型「中断于第 N 轮 / 最后调了什么 / 是否失败」，避免从零重新推理。
  验收：`tests/test_background_task_persistence.py`（5 项：建表、upsert 往返、重启标 interrupted、
  同步落库、列表合并）+ `tests/test_run_checkpoint.py`（5 项：列存在、往返、缺失返回空、跨重启、
  agent 字段）。60 项相关测试无回归，`ruff` 通过。
- [x] 条目 7 循环拆分 — **部分完成**（2026-11-26，工作区 `ethan-ai-loop-split`，分支 `feature/loop-split`）。
  已完成：
  - 先补关键路径测试 `tests/test_agent_loop_paths.py`（空响应 nudge / max_iters 收尾 / 决策触发 /
    运行中补充），作为重构安全网——计划要求的「先补测试再动代码」。
  - 把与 `Agent` 实例状态无关的纯函数拆到 `ethan/core/reply_quality.py`（171 行）：错误归类
    （图片 400 / 可重试连接）、空回复兜底文案、退化回复判定、合成 user 消息前缀、图片剥离重试。
    `agent.py` 保留 re-export，旧引用路径（`agent_mod._is_degenerate_reply` 等）继续可用。
  - `agent.py` 2239 → 2092 行；62 项相关测试通过，`ruff` 通过。`docs/agent-loop.md` 补「模块拆分」节。
  - ⚠️ **未完成**：计划目标是「单文件 ≤700 行」。剩余大头是 `stream_chat()`（约 1140 行）与
    `chat()`（约 440 行）——后者是前者的非流式重复实现。消除这份重复需要把循环体抽成带
    20+ 局部状态的独立函数，或让 `chat()` 委托 `stream_chat()` 并聚合文本/usage/tool_steps，
    属于高风险重构，需独立排期与更细的等价性测试（尤其 tool_steps 与 usage 语义对齐）。
    本次只做了零风险的部分，未强行改写核心循环。
- [ ] 条目 8 会话级记忆提醒 — 未开始
- [ ] 条目 9 分级路由 — 未开始
- [ ] 条目 10 事件触发 — 候选，待确认场景

**遗留问题**：凌晨 0 点几次 4 步运行零命中，未解释；心跳的 token 占比未测。

### 本轮源码复核与补完（2026-11-26）

上面的阶段记录与复选框保留历史口径（不再作为当前待办）；下表是当前复核后的真实状态，**实现不等于线上验收**。

| 条目 | 当前状态与证据 | 尚需验收 |
|---|---|---|
| 1 | 已实现；40轮12K结果零前缀改写 regression | 上线三天真实≥80%命中率；夜间零命中原因 |
| 2 | 已实现；fast/full稳定层与分割回归；默认协议预算 PR #495 squash `bb08f4f8`，7051→5948正文字符，独立151项通过，安全/secrets逐字保留 | 三天实测收益；发布模板不覆盖用户运行时定制，不能将模板预算冒充全量prompt预算 |
| 3 | PR #497 squash `c6da069b`；双端7天input/cache/次数/平均步骤，消息+wire+精确归因同事务；独立后端57项、Desktop256项及双构建通过；review修复小数token舍零，双端6契约通过，唯一线程resolve、CI绿 | 旧历史不猜归因，未扫描整体归档；checkpoint结束到channel定稿的退出可显示未归因；安装的Desktop仍需新Tauri包 |
| 4 | PR #490 squash `4a5f7fff`；真实Agent→producer→SQLite→下一请求严格reasoning/call-id配对；独立118项绿，两条review修复并resolve，含chat/stream兜底与异常/停止6终止组合 | 真实网关两步无400但reasoning为0，非空thinking回传仍未实证 |
| 5 | 已实现；原状态补偿与短输出去重回归保持 | 真实用户体验持续观察 |
| 6 | PR #494 squash `19fd224d`；每轮/授权前/派发前/单工具完成持久化，原生自动Recorder；真实子进程SIGKILL与未知工具禁止重放；独立89项绿；review修复检查点失败时兄弟工具cancel/drain，唯一线程resolve、最新CI绿 | 外部内核内部工具不可见；临时无sid CLI不强制DB；跨进程任务不可reattach |
| 7 | 完成纯结构拆分，独立PR #488 squash `d1d088b7`；Agent530行、七步共享编排，Chat/Stream政策分别保留；同24 characterization旧新皆绿；修复review顺序回归后25项绿，唯一线程resolve、CI绿 | 已合并；服务最终部署时再核验 |
| 8 | PR #489 squash `d70edd00`；独立固定时间戳、profile/mode隔离快照，9项单测；独立72项通过，review无阻塞、CI绿；真实Agent假provider一轮早餐无recall往返；见session-memory.md | 真实个人问答质量A/B，不捏造提升比例 |
| 9 | PR #491 squash `45db2b1d`；RouteDecision strong/medium/weak，显式技能完整加载及channel/mode隔离；独立98项通过；新装触发词括号崩溃后继 PR #493 `b31fd5c8` 修为仅星号glob，其余字面转义，真实新装先2红后绿、新20项通过 | 生产延迟/质量对照；medium是强度不是旧字数轨 |
| 10 | PR #496 squash `ed48fdc6`；默认关闭、专用HMAC/白名单/限流/持久去重、本地心跳变化检查；review修复换delivery重放与极简兜底策略丢失，保留真实reasoning前缀；独立严格18项/扩展60项，双线程resolve、最新CI绿 | 外部账号未连接；只读人工复核摘要；心跳真实token占比未测；旧ledger无原始body不能补造历史摘要 |

条目3独立 worktree 验证：Desktop全量256项通过，双端小数展示契约6项通过，Web（webpack）与Desktop生产构建、构建后串行双端tsc通过。构建不等于已安装Desktop新包；Web仍需部署静态产物。
早期 completion 整合 Python 全量 **2156 passed / 3 skipped**，不是最终合并主线证据。基础 main `19fd224d` 全量2160通过、3跳过，末尾1失败/13错误均为复制未跟踪技能node_modules导致内置盘满（errno28），不是协议断言失败；已清理本次独占79GB临时目录，最终统一代码在干净worktree与外置盘临时根重新全量验证。最终统一主线 `ed48fdc6` 干净worktree全量 **2204 passed / 3 skipped / 11 warnings，100.14s，exit0**；旧 aiosqlite 关线程与依赖废弃 warning 如实保留。
第一轮8失败已核实修复：3项worktree缺.venv、2项拆分后旧源码定位改真实迁移/producer执行、
1项默认协议精简后恢复判断标准，2项serve测试隔离开关/进程锁并阻止真实启动。
真实已配置网关 `deepseek-v4.1-flash` 两组各3请求：均 step1→step2→OK，无400，
但普通/显式thinking探针 reasoning_chars 都为0，**不能证明非空思考字段线上回传验收**。
独立review实证修复：事件override缺fast参数；共享连接提前commit半成品message/wire。
AOCI MCP未挂载，本轮只按源码证据实施，未伪造认知收据或索引维护。

本轮实际独立依赖顺序：纯结构7（#488）→ 记忆8（#489）→ 路由9（#491）→ 协议4（#490）→ 新装glob修复（#493）与默认协议预算（#495）→ 检查点6（#494）→ 成本3（#497）与事件10（#496）。另 #492 隔离测试启动环境，阻止测试误启真实服务。
已有条目1/2/5不重复开发；线上三天观察属于部署后时间窗，不可能在本轮立即宣称完成。
本轮部署前只读聚合近3天：schedule 31个有usage的assistant样本，input 125885002、cache
50810880，命中率 **40.36%**（不是未来部署收益，不达≥80%）。api 4样本11.67%，web 1样本0%。
该历史聚合还不能按具体job定位，需要新成本归因开始积累后再核验；不输出用户消息内容。

### 继续真实验收（2026-11-26，未把实现冒充达标）

- 只读观察工具 PR #499 squash `d47aa57c`，16 项测试、独立复核及 CI 通过；review 修复百分比舍入假通过，门槛比较原始计数。默认单次 `python scripts/observe_agent_loop_acceptance.py --since 2026-11-26T05:23:00+08:00`，只读一致事务、匿名聚合，无模型请求或生产配置修改。`full_acceptance` 保守为 false：全部 schedule 汇总不能冒充具体抓取任务质量验收。
- 10:35:04 上海时间，部署后仅 5.201 小时：schedule 最终 assistant 4 行，只有 1 行有正 input；input 5,840,324、cache 0，61 工具步骤 / 1 error（1.64%）。唯一精确归因运行的 wire 有 62 assistant / 61 tool，32 条非空 reasoning、合计 25,166 字符（仅长度）。实际成本 SQL 与独立聚合同窗一致。**未达 ≥80% / ≤1% 门槛，未满三天**；完整初始部署窗口最早 11月29日约05:23，后继修复部署须单列时间边界。
- 现有 usage 只有数值，不保留缓存字段是否缺失，故历史 cache=0 不能区分上游真实零命中与缺字段被默认零。Trae 流式/非流式 token_usage 投影确实丢弃扩展字段；网关转换修复及 Ethan 字段覆盖观测在独立 PR 中处理，未在上线前宣称已生效。夜间零缓存原因仍不能仅凭历史 DB 定论。
- 只读现有配置确认 `defaults.heartbeat.enabled=false`、interval 15；近30天没有 heartbeat 计费行与关闭条件一致，不是 source 误归 schedule。**不自动启用心跳**，零记录不代表全系统维护真实成本为零。
- 真实已配置 `buddy-proxy/deepseek-v4.1-flash` 流式三请求 step1→step2→OK，无400；首轮真实 reasoning 236 字符被加入下一请求历史，后两轮 reasoning 为0。初始探针要求两工具轮都非空而 exit1，保留该失败；只能证明当前网关入口接受带非空思考的历史。Trae `_native_messages` 会剥除 reasoning_content，**不证明上游原文回传或 DeepSeek 官方严格协议通过**，不切换付费路由伪装验收。
- 新增合成个人问答 A/B 工具，临时 SQLite、三组合成偏好、唯一只读召回工具，两臂同题同系统；A 关闭快照，B 执行真实快照准备。离线假 provider 只验证线路，不算真实质量；首次 live 因现有 provider 类型拼法 `openai_compact` 被脚本错误拒绝，未发模型请求，已修兼容回归。第二次真实六臂测量**未通过**：存在非 JSON、评分失败及 B 额外召回；不能宣称个人问答无退步。网关非流式推理混入正文是真实转换缺陷，但未保存答案的既有报告不能据此断言每次格式失败原因；补匿名格式诊断并等待网关修复后受控复测。
- Desktop 已完成实际 Tauri release arm64 app/DMG，版本 `1.0.0-beta.54`；内嵌 Brotli JS 与生产 dist 逐字节一致，含成本报表特征。原始 DMG SHA256 `0d20ba64eb7350bd62ec5dc4924343a34ace2e93b9b2ad1fe2c67d49a9e08bed`，hdiutil 校验通过，稳定保留于 `ethan-desktop-b54-deliverables`。旧 b26 已完整备份并校验，新 b54 已复制到 `/Applications/Ethan Agent.app`；原始无签包与旧包同样缺资源 seal，新安装包已本地 ad-hoc 重签，`codesign --verify --deep --strict` 通过，签后可执行 SHA256 `b3193f31dd9044df10ad852d7dbc8607c1da303b30c4c9eecdb931099a1d0d00`。**未打断当前进程，新版下次启动生效**；没有 Developer ID、公证、自动更新签名或公开发版。原无签 DMG 仅通过 CRC/内容校验，应用签名未通过；另名本地签名安装包 `Ethan Agent_1.0.0-beta.54_aarch64_local-adhoc.dmg` SHA256 `563a37dba995c9635bb137f51954e5519996154b001b9f47d89549a67a3f40e7` 已只读挂载并验证内置应用严格签名、版本与签后可执行哈希一致，随后卸载。
