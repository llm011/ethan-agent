# 深度 code review 方法论

> 本文档是 `code-review` 技能的**深度模式**流程。快速模式（默认）见主 SKILL。
> 深度模式只在用户明确要求「深度 / deep / thorough / 严格 / 彻底 / 仔细 审查」时启用。

## 核心思路：同时打两个敌人

任何 review 都在对抗：
- **漏报（false negative）**：真 bug 没看出来。
- **误报（false positive）**：报了一堆不是问题的东西，淹没真问题、浪费时间。

深度模式把 review 拆成一条**结构化流水线**，每一步专门打其中一个敌人：

| 阶段 | 打谁 | 怎么打 | 代价 |
|------|------|--------|------|
| 1. 圈定范围 + 读封闭上下文 | 漏报 | 不只看 diff，拉 callers / callees / 读写对 | 读的量大 |
| 2. 多维度独立扇出 | 漏报 | 每个维度一个独立 agent 扫一遍 | 看 N 遍 |
| 3. 强制写失败场景 | 误报 | 每条 finding 必须有具体 repro 路径 | 每条都要具象化 |
| 4. 对抗式验证 | 误报 | 独立验证 agent 默认「这是错的」去反驳 | 每条再跑几轮 |
| 5. 去重 + 严重度排序 | 信噪比 | 合并同类项，按 影响×概率 排序 | 汇总开销 |

细 = 多镜头 + 读全上下文；准 = 强制 repro + 独立证伪；慢 = 这两组动作本质是「一份代码被反复看很多遍、每条结论被反复挑战很多次」。**不要试图把它变快**——慢是它准的来源。

## 与快速模式的关系

**继承自主 SKILL（不变）**：
- 只读不写（不编译 / 不运行 / 不跑测试）
- 跳过噪音文件（同清单）
- GitHub 访问策略（`gh` 优先）
- 评论书写风格（简洁、口语化、协作式）
- P0 / P1 / P2 分级与发布方式（单条 `pulls/{N}/comments` + 总结 review）

**深度模式覆盖的约束**：
- 快速模式「只看 diff / 禁止读 diff 外文件」→ 深度模式**允许按需读 diff 外的单个文件**，用于补封闭上下文。
- 仍然**禁止 `git clone` / `git checkout`**。拉 diff 外文件用：
  - GitHub 拉单个文件：`gh api repos/<owner/repo>/contents/<path>?ref=<head_sha>`（按 PR head sha）
  - GitHub 找调用方：`gh api search/code -f q='<symbol> repo:<owner/repo>'`
  - 本地 diff：直接 `Read` / `Grep` / `Glob` 工作区文件
- 禁止写脚本解析 diff（同快速模式）。

## 阶段 0：准备（与快速模式共享）

先完成快速模式的「GitHub 访问策略 第 0 步」+「流程第 1-3 步」：
1. 解析 owner/repo + PR 号，确认 `gh` 可用。
2. `gh api .../pulls/<N>/files` 拿文件列表 + head sha。
3. 筛选值得 review 的文件（同噪音清单）。
4. `gh pr diff <N> > /tmp/pr_<N>.diff`，`rg_search` 定位每个文件 diff 起始行。

把结果写到 /tmp，作为后续 agent 的共享输入：
- `/tmp/pr_<N>.diff`（diff 全文）
- `/tmp/pr_<N>_sha.txt`（head sha）
- `/tmp/pr_<N>_intent.txt`（PR 标题 + 描述 + 关联 issue，用于「改动意图」）

> 本地 diff：把 diff 写到 `/tmp/local_diff.diff`，意图从 commit message / 用户说明取。

## 阶段 1：圈定范围 + 读封闭上下文（打漏报的基础）

diff 的 bug 往往不在改的那几行，而在：
- **谁调用了被改的函数（caller）**：改了签名 / 行为，调用方有没有对应改？
- **被改函数调了谁（callee）**：假设的下游行为成立吗？去读下游实现。
- **读写对**：改了写入端，读取端有没有对应改？反之亦然。

做法：
1. 从 diff 里提取被改动的**函数 / 符号清单**（函数名、类名、导出 API）。
2. 对每个关键符号找 caller（`gh api search/code` 或本地 Grep）。**只取最相关的 top 15 个上下文文件**，避免失控。
3. 必要时按 head sha 拉单个 callee 文件确认下游行为。
4. 把上下文文件收集到 `/tmp/pr_<N>_ctx/`（或记录工作区路径清单），供阶段 2 的 agent 读取。

> 预算：上下文文件上限 15 个。超过就按「直接 caller > 直接 callee > 读写对」优先级裁剪。
> 拿不到上下文（私有仓库 / 无权限）→ 跳过该符号的上下文，**不要 clone**，在阶段 2 注明「上下文缺失，finding 置信度降级」。

## 阶段 2：多维度独立扇出（打漏报的主力）

**不是通读一遍找问题，而是分维度各扫一遍。** 同一次 pass 带着「找逻辑 bug」的心态会自动忽略性能问题——注意力有指向性。给每个维度一次独立 pass，用不同镜头各照一遍。

### 维度清单（每个维度一个独立 agent，并行跑）

| 维度 | 关注点 |
|------|--------|
| 正确性 | off-by-one、空指针 / nil、类型错误、边界条件、分支逻辑错误、状态机错误、返回值未检查、默认值错误 |
| 并发 / 竞态 | 数据竞态、死锁、原子性破坏、goroutine / thread 泄漏、时序依赖、锁 / channel 误用、TOCTOU |
| 安全 | 注入（SQL / 命令 / 模板）、硬编码密钥、路径穿越、XSS / CSRF、鉴权绕过、敏感信息泄漏、不安全反序列化、SSRF |
| 性能 | N+1 查询、热路径重复 IO、O(n²) 嵌套、不必要分配 / 拷贝、缺索引、大对象未释放、阻塞调用在热路径 |
| 错误处理 | 异常被吞、错误未传播、panic 未恢复、部分失败缺回滚、错误信息泄漏内部细节、忽略 error 返回值 |
| 测试覆盖 | 新逻辑无测试、边界 case 未覆盖、断言错误、mock 失真、测试间状态依赖 |
| API / 契约一致性 | 签名变更调用方未同步、契约变更、向后兼容性破坏、序列化格式变更、错误码变更 |

> 改动很小（<50 行、单文件）时可缩减到 3-4 个最相关维度；大改动用全 7 个。

### 执行方式：并行独立 subagent

用 **Task 工具**为每个维度启动一个独立 subagent（`subagent_type=general_purpose_task`），**在一条消息里并行发起多个 Task 调用**。每个 subagent：
- 互相看不到对方结论（Task 子代理天然 stateless 隔离）。
- 只拿一个维度 + diff / 上下文路径 + finding schema。
- 返回结构化 findings。

**扇出 subagent prompt 模板**（每个维度填入 `<DIMENSION>` 和该维度关注点）：

```
你是 code review 流水线的一个「单维度扫描 agent」。你只负责一个维度：<DIMENSION>，
看不到其他维度的结论，也不要评论其他维度。

输入材料（只读这些，不要 clone 仓库）：
- diff：/tmp/pr_<N>.diff
- 上下文文件目录 / 清单：<CTX_LIST>
- 改动意图：<INTENT（从 /tmp/pr_<N>_intent.txt 读）>

任务：只从 <DIMENSION> 角度扫这个 diff，必要时读上下文文件确认，找出可疑点。

<DIMENSION> 关注点：<该维度关注点，见上表>

每条 finding 必须用以下 schema 输出（写不出的字段就别报这条）：
- id: <D1>
- dimension: <DIMENSION>
- location: <file:line>（新文件行号）
- title: <一句话问题>
- failure_scenario:
    input: <具体什么输入 / 条件触发>
    path: <file:line → file:line，走到哪一步出错>
    outcome: <产生什么错误结果>
- evidence: <diff 里哪几行 + 上下文哪几行支撑这个判断>
- suggested_fix: <一句话>
- severity_hint: <P0 / P1 / P2>

硬规则：
1. 只报你能写出具体 failure_scenario 的。构造不出「输入→路径→错误结果」→ 直接丢弃，别报。
2. 不 clone 仓库，不 git checkout。只读给你的 diff 和上下文文件。
3. 不写脚本解析 diff。
4. 不要凑数。没发现就回「无发现」。

输出：findings 列表（清晰结构化）。没发现就明确说「无发现」。
```

收集所有维度的 findings，进入阶段 3。

## 阶段 3：强制失败场景（打误报的初筛）

这是阶段 2 内置的纪律，但 orchestrator 再做一遍硬过滤：

对每条候选 finding，逼问：
- `input` 够具体吗？（不是「某些情况」「可能」这种模糊词）
- `path` 真能走通吗？（每一跳都有 file:line 支撑）
- `outcome` 是真实的错误结果吗？

**构造不出具体 repro 路径 → 直接丢弃。** 这一步毙掉一批「看起来像 bug」其实是脑补的 finding。

> 这一步在 orchestrator（主 agent）脑内完成，0 个额外 subagent。

## 阶段 4：对抗式验证（打误报的主力，最慢）

阶段 3 存活下来的每条 finding，派**独立的验证 subagent** 去反驳。验证者的默认立场：**「这条是错的，除非证据能说服我。」**

### 为什么独立

人肉 review 里你很难对自己的结论保持怀疑——一旦写下来就倾向于相信。拆成「提出」和「证伪」两个独立角色，打破确认偏误。验证 subagent 不知道原始 reviewer 有多自信。

### 执行方式

对每条存活 finding，用 Task 工具并行启动 2-3 个验证 subagent（`subagent_type=search`，适合探索调用方 / 上游来反驳），**每个给不同反驳角度**：

| 验证 agent | 反驳角度 |
|-----------|---------|
| V-正确性 | 声称的 bug 在逻辑上真的成立吗？是不是误读了代码？ |
| V-可达性 | failure_scenario 的 input 真的能走到出错 path 吗？上游有没有 guard / 校验 / 提前 return 挡住？去查 caller。 |
| V-上游 | 被调用的函数 / provider 真的会按 finding 假设的方式处理吗？去读 callee 实现。 |

> finding 数量多时，只验证 top 10（按 severity_hint 排序），避免爆炸。

**验证 subagent prompt 模板**：

```
你是独立的「对抗式验证 agent」。你的默认立场：下面这条 finding 是错的，除非证据能说服你。
你的任务是反驳它，不是确认它。

Finding 全文：
<粘贴 finding，含 failure_scenario>

可供核查的材料（不要 clone 仓库）：
- diff：/tmp/pr_<N>.diff
- 上下文文件：<CTX_LIST>
- 找调用方 / 上游：GitHub 用 `gh api search/code -f q='<symbol> repo:<owner/repo>'`；本地用 Grep / Glob
- 按需拉单个文件：`gh api repos/<owner/repo>/contents/<path>?ref=<head_sha>`

从以下角度尝试反驳（任一成立就 KILL）：
1. <分配给你的角度，见上表>

输出裁决（只回裁决，不要复述 finding）：
- verdict: HOLD（站得住）/ KILL（站不住）
- killed_by: <哪个角度毙的，若 KILL>
- reasoning: <具体证据，引用 file:line>
- confidence: high / medium / low
```

### 投票规则

- 收集所有验证 agent 的 verdict。
- **多数 KILL → 丢弃该 finding。**
- 平票（如 1 HOLD / 1 KILL）→ **保守丢弃**（优先信噪比，宁可漏一个也别塞误报）。
- 多数 HOLD → 保留，进入阶段 5。
- 验证 agent 提供了新信息导致 finding 需要修正 → orchestrator 修正后保留。

## 阶段 5：去重 + 严重度排序（信噪比）

1. **去重**：多个维度会撞同一个 bug（如「并发」和「正确性」都报了同一处竞态）。合并同类项，保留描述最准的那条，`dimension` 字段可列多个。
2. **严重度评分**：按 `真实影响 × 触发概率` 排序，最严重的放最前。

评分表：

| | 触发概率 high（默认路径 / 常见输入） | medium（边界输入） | low（罕见输入） |
|---|---|---|---|
| 影响 high（数据损坏 / 安全 / 崩溃 / 资金） | P0 | P0 | P1 |
| 影响 medium（性能 / 可靠性） | P1 | P1 | P2 |
| 影响 low（可读性 / 可维护性） | P2 | P2 | P2 |

> 与主 SKILL 的 P0 / P1 / P2 定义对齐：P0 必须修复写行内评论，P1 建议性评论，P2 只在总结一句带过。

## 输出（继承主 SKILL）

1. **发评论**：完全按主 SKILL「第 6 步」——单条 `pulls/{N}/comments` POST 行内评论 + 一条总结 review。评论风格同主 SKILL（简洁、口语化、协作式）。
2. **聊天总结**（深度模式额外加一层透明度）：

```
深度 review 完成（模式：deep）。

覆盖维度：正确性、并发、安全、性能、错误处理、测试覆盖、API 契约。
候选 finding <X> 条 → 失败场景过滤后 <Y> 条 → 对抗式验证存活 <Z> 条。

P0（已评论到行）：① … ② …
P1（已评论）：① …

被验证毙掉的（供参考）：① <title> — <killed_by>
```

没有存活 finding：「深度 review 完成，7 个维度扫完，候选 0 条 / 验证存活 0 条。没发现阻塞性问题，可以合并。」

> 本地 diff（无代码平台）：不发布评论，按 `📍 文件:行号` 格式在对话里输出，同样附透明度总结。

## 预算与失败信号

- **慢是设计内的**：深度模式比快速模式慢 5-10 倍，不要试图压缩阶段 2 / 4 的独立 agent。
- 阶段 1 上下文文件上限 15 个；阶段 2 维度上限 7 个；阶段 4 每条 finding 验证 agent 上限 3 个、验证 finding 上限 10 条。
- **失败信号**（提前停止）：
  - 阶段 2 所有维度返回「无发现」→ 跳过 3-5，直接报「深度扫完，无候选」。
  - 阶段 3 把所有候选都过滤掉 → 报「深度扫完，候选均无法构造失败场景」。
  - 阶段 4 全部被毙 → 报「深度扫完，候选 <X> 条经对抗式验证全部不成立」。

## 反模式（别这么做）

| ❌ 别做 | ✅ 应该 |
|--------|--------|
| 为了快，把 7 个维度合并成一次通读 | 保持独立 pass，每个 agent 一个镜头 |
| finding 不写 failure_scenario 就报 | 构造不出具体 repro → 丢弃 |
| 验证 agent 和提出 agent 是同一个 / 能看到结论 | 验证必须独立 subagent，默认反驳 |
| 为了多报几条放宽验证 | 平票保守丢弃，优先信噪比 |
| clone 整个仓库补上下文 | 按需拉单个文件 + search / code |
| 因为「看得仔细」就堆一长串评论 | 改动大 ≠ 评论多，只发存活的 P0 / P1 |
