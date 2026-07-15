# Palantir AIP 启发的 Agent 改进项清单

> 本文档整合了 Palantir AIP Agent 的核心设计理念、第三方建议，以及与 Ethan Agent 现状对比后提炼的可落地改进项。按优先级排序，每项包含：价值、成本、具体做法、风险。

## 已实施（本 PR：feat/memory-recall-enhancement）

| # | 改进项 | 核心变化 | 详见 |
|---|--------|----------|------|
| A1 | 记忆自动召回 | FactStore 增加 `tags`，`build_context_with_recall(query)` 按关键词语义召回 | [memory.md · 信号检测与语义召回](./memory.md#信号检测与语义召回) |
| A2 | 记忆信号检测器 | `detect_memory_signal()` 确定性规则检测 → 注入 hint + 激活工具 | [memory.md · 信号检测](./memory.md#信号检测与语义召回) |
| A3 | 降低门槛 + 多渠道 | 触发从 `%10` → `%5`，warm_capacity 20→10，微信/飞书也触发抽取 | [memory.md · 后台抽取触发](./memory.md#后台抽取触发) |
| B1 | 决策记录结构化 | 心跳从 tool_steps 抽取成功路径 → `playbook.json` 正反馈 | [memory.md · 过程记忆](./memory.md#过程记忆procedurestore) |
| B2 | FDE 需求挖掘 | episodes ≥3 次重复 → `suggestions.json` → 首轮注入建议 | [memory.md · Episode](./memory.md#第四层情节记忆episodic-memory) |

> B1 与 B2 共享基础设施（心跳调度 + lite 模型 + 存储层），输入源不同（tool_steps vs episodes）但闭环结构一致。

---

## 待实施

### P1 — 近期做（中成本 + 高价值）

#### 3. Action 前置校验 + 操作草稿模式
- **价值**：让 side_effect 工具有安全边界，Agent 才敢更自主地执行高危操作
- **成本**：~200 行
- **做法**：
  1. `BaseTool` 增加 `pre_check(**kwargs) -> tuple[bool, str]` 方法，在 consent 之前做业务规则校验
  2. consent 流程从"问要不要执行"升级为"展示完整操作计划（参数预览 + 影响范围）"
  3. 对 `file_write`/`shell`/`lark_message_send` 等 side_effect 工具特别有价值
- **借鉴 Palantir**：Action Types 的原子性事务 + 前置规则校验
- **Ethan 现状**：[consent.py](file:///ethan/core/consent.py) 只做"问不问用户"，不做"操作是否合法"的校验

#### 4. 知识模型三层：事实层 → 事理层 → 行动层
- **价值**：规则从 prompt 文本变成可编程的结构化数据，推理链路有了确定性约束
- **成本**：~300 行 + 规则梳理
- **做法**：
  1. **事理层优先**：把 system/agent.md 和 system/soul.md 里的规则抽取成结构化 `rules.json`——每条规则有 `id`/`condition`/`action`/`priority`
  2. **行动层**：给高频 side_effect 工具定义"动作模板"——参数 schema + 前置校验 + 影响范围描述
  3. 事实层暂不做（见 P2）
- **借鉴 Palantir**：知识模型嵌入 AI 推理——事实层调用实体定义，事理层加载规则约束，行动层获取动作模板
- **Ethan 现状**：规则散落在 system/*.md 的 prompt 文本里，难以系统化管理

#### 5. Context Layer 语义增强
- **价值**：上下文从"信息罗列"升级为"行为指导"
- **成本**：~150 行
- **做法**：
  1. FactStore 增加 `implication` 字段——每条 fact 不仅记录内容，还记录"这对 Agent 行为意味着什么"
  2. 心跳任务里用 lite 模型给新 fact 生成 implication
  3. 注入 `<memory_context>` 时用 implication 替代原始 content
- **借鉴 Palantir**：Context Layer 能解释"这意味着什么"，不只是"发生了什么"
- **Ethan 现状**：`_build_system()` 注入的是 FactStore top-N facts 的扁平文本

---

### P2 — 远期考虑（高成本或场景依赖）

#### 6. Harness 校验层（Tool 调用前置校验）
- **价值**：所有 Tool 调用前统一校验权限、格式、业务规则
- **成本**：高（需定义校验规则集 + 改造 ToolExecutor）
- **做法**：
  1. 在 ToolExecutor.execute 中，consent 之前加一层 Harness 校验
  2. 校验规则可配置（YAML 或 JSON），支持权限、格式、业务规则
  3. 校验失败直接拒绝，不进入 consent 流程
- **借鉴 Palantir**：LLM 推理后，所有操作必须通过 Ontology 的校验层
- **与 P1.3 的关系**：P1.3 是 per-tool 的 pre_check，Harness 是全局校验层。可以先做 P1.3，再抽象为 Harness
- **Ethan 适用性**：个人 Agent 场景下，全局校验层可能过重，per-tool pre_check 足够

#### 7. 最小可行本体（MVO）
- **价值**：验证 Ontology 思路是否适合个人场景
- **成本**：中
- **做法**：选一个高价值痛点域（如"日程管理"或"笔记管理"），建 5-10 个 Object Type + 2-3 条 Link + 1-2 个 Action
- **借鉴 Palantir**：Ontology 不是静态知识图谱，是可执行的业务世界模型
- **Ethan 适用性**：验证性探索。个人场景下对象关系简单，除非扩展到专业领域（如法律案件管理）

#### 8. FactStore 实体关系层（轻量 OAG）
- **价值**：支持关系遍历查询（"张三和合同 A 是什么关系"）
- **成本**：中
- **做法**：给 FactStore 增加实体和关系三元组 `{entities: [...], relations: [...]}`
- **借鉴 Palantir**：OAG（Ontology Augmented Generation）替代 RAG
- **Ethan 适用性**：个人场景下"查关联信息"频率有限。等 P1 知识模型三层跑通后，如果发现关联查询是高频痛点再做

#### 9. MCP 标准化暴露
- **价值**：外部 Agent（Claude Code 等）可调用 Ethan 的工具/技能/记忆
- **成本**：高（需重构工具协议层）
- **做法**：把核心能力通过 MCP 协议暴露为标准 MCP 服务器
- **借鉴 Palantir**：通过 Ontology MCP 将语义层暴露为标准协议
- **Ethan 适用性**：个人使用集成需求不迫切。持续关注 MCP 生态，等标准稳定且有明确需求时再做

#### 10. 操作审计日志（独立于 session 记录）
- **价值**：能回溯"Agent 昨天做了什么操作"，不可篡改
- **成本**：低
- **做法**：side_effect 工具的执行记录写入 `~/.ethan/audit.log`（append-only），支持按时间/工具/会话检索
- **借鉴 Palantir**：不可篡改的审计日志
- **Ethan 适用性**：不照搬完整权限体系，但审计日志有独立价值，可单独提前做

#### 11. 分布式 Agent 共享状态基座
- **价值**：多 Agent 协同时，通过共享状态而非 Prompt 传递信息
- **成本**：高（需引入 Redis + PostgreSQL 或等价方案）
- **做法**：
  1. 状态层（Redis + PostgreSQL）作为统一的内存基座
  2. 所有 Agent 共享同一个 Ontology/状态，而不是各自维护上下文
  3. LLM 推理后，所有操作必须通过状态层的校验
- **借鉴 Palantir**：Ontology 提供统一的内存与上下文基座，实现多 Agent 无歧义协同
- **借鉴第三方建议**：结合 Vercel Open Agents 的持久化工作流 + Cloudflare Agent Memory 的上下文压缩
- **Ethan 适用性**：当前是单 Agent 架构，多 Agent 协同是远期需求。如果未来扩展到多 Agent（如专业法律 Agent + 通用助理 Agent 协同），再考虑

#### 12. Sandbox 沙箱隔离执行
- **价值**：Tool 执行的安全性提升
- **成本**：高
- **做法**：用 WASM/Docker 隔离容器作为执行宿主
- **借鉴第三方建议**：比 Palantir 的 Sandbox 更轻量
- **Ethan 适用性**：当前 shell 工具已有 consent 机制，沙箱隔离对个人 Agent 过重。如果未来开放给多用户或执行不可信代码，再考虑

---

## 设计原则

1. **确定性与概率性分离**（Palantir 核心）：记忆的写入触发和召回由系统规则确定性保证，LLM 只在"记什么内容"上做概率性判断
2. **不照搬企业级重资产**：Palantir 的完整 Ontology/ABAC/审计体系对企业级是刚需，对个人 Agent 过重
3. **越用越聪明**：任何改动都应该让 Ethan"越用越聪明"，而不是"越用越重"
4. **先验证再投入**：MVO/实体关系层等不确定 ROI 的特性，先小范围验证再决定是否扩展

## 实施路线图

```
已实施（本 PR：feat/memory-recall-enhancement）
  A1 自动召回 → A2 信号检测器 → A3 降低门槛 + 多渠道触发
  B1 决策记录结构化（成功路径正反馈）→ B2 FDE 需求挖掘（主动建议）

P1（近期）
  3. Action 前置校验 → 4. 知识模型三层 → 5. Context Layer 语义增强

P2（远期/按需）
  6. Harness 校验层    7. MVO 最小本体        8. FactStore 实体关系层
  9. MCP 标准化       10. 操作审计日志       11. 分布式共享状态
  12. Sandbox 沙箱隔离
```
