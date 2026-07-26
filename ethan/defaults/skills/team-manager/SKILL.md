---
name: team-manager
version: 3.0.0
description: >
  团队人员管理技能。覆盖三大核心场景：
  ① 绩效管理 — 记录到 people、分析文档/CR、绩效季汇总评估；
  ② 任务委派 — 拆分 checkpoint、创建飞书任务、节点提醒跟进；
  ③ 提醒与自动化 — 项目节点、交付截止、例行巡检、绩效季主动提醒。
  数据统一写入知识库（scene=work），后端可在 filesystem/Obsidian/external 间切换。
  时间线和定时任务管理由 schedule-manager 技能负责。
trigger: "工作记录|工作进展|业务进展|更新进展|进展整理|我的记录|表现不错|做得好|汇总绩效|绩效总结|绩效报告|团队总结|周报汇总|CR汇总|代码产出|分配任务|委派|布置任务|任务跟踪|checkpoint|团队管理|整理进people|记到people|归到people|整理成员|按人整理|整理观点|整理沉淀|工作沉淀|沉淀整理|分类写入|整理文档|收藏文档|收藏链接|存个文档|记个链接|项目节点|交付提醒|截止|巡检|延期"
author: Ethan Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  ethan:
    tags: [Team, Performance, Task, Delegate, Management, Reminder]
---

# 团队管理 (Team Manager)

团队人员管理效率工具，覆盖绩效管理、任务委派、提醒自动化三大场景。

> 数据统一写入**知识库**（`scene="work"`），后端可在 filesystem / Obsidian / external 间切换，数据自然跟随。
> 时间线和定时任务管理由 `schedule-manager` 技能负责，本技能专注于**人**的管理。

## 🚫 硬规则（必须遵守，不可绕过）

### R1：写知识库只用 knowledge_* 工具

**所有 team-manager 技能产生的数据写入，必须通过 `knowledge_add` / `knowledge_edit`（scene="work"）完成。**

禁止行为：
- ❌ 用 `file_write` 直接写 markdown 文件
- ❌ 用 `shell` 的 `mkdir` / `cat` / `echo` 创建目录或文件
- ❌ 自己拼接 vault 路径（如 `/root/Documents/obsidian/work/life/people`）——路径由后端管理，Agent 不需要关心

正确做法：
- ✅ 新建条目 → `knowledge_add(title=..., content=..., tags=..., scene="work", frontmatter=...)`
- ✅ 追加内容 → `knowledge_edit(source=..., content=..., mode="append", scene="work")`
- ✅ 整篇替换 → `knowledge_edit(source=..., content=..., mode="replace", scene="work", frontmatter=...)`

**判断标准**：只要写入的内容属于人员日志/项目进展/业务范围/文档收藏/CR 周报/绩效草稿/工作沉淀 等本技能管理的条目类型，就必须走 knowledge_* 工具。即使你已经用 lark-cli / web_fetch 拉取了原始文档内容，写回时也要走 knowledge_* 工具，不要 file_write。

### R2：内容来自外部文档/链接时，必须传 frontmatter={"source": ...}

**凡是条目内容派生自外部网页/飞书文档/链接（用户提供了 URL，或你用 lark-cli / web_fetch 拉取过原文），调用 `knowledge_add` / `knowledge_edit` 时必须传 `frontmatter` 参数：**

```python
knowledge_add(
    title="...",
    content="...",
    tags=[...],
    scene="work",
    frontmatter={"source": "{原始 URL}"},  # 必传
)
```

- `source` 字段是**必传**项，值为原始文档的 URL（飞书 docx 链接、网页链接等）
- 可按需追加其他字段：`author`、`published`、`url`（字段名小写、值用字符串）
- 固定字段（title/type/tags/created/updated）由后端自动管理，**不要**在 frontmatter 里重复传
- filesystem 后端会忽略 frontmatter，但参数仍要传（保持一致，后端切换时不丢字段）

### R3：scene 固定为 work

team-manager 的所有 knowledge_* 调用，`scene` 参数固定为 `"work"`，不要用 `"life"` 或空字符串。

## ⚡ 快速路径（优先匹配，命中即执行，勿绕路）

### 「整理进 people」

当用户说「把 xxx 整理进 people」「记到 people 里」时，**不要搜索、不要读参考文档**，直接执行：

1. 从用户消息或上下文中提取 `{姓名}: {事件}` 列表
2. 对每个人，用 `knowledge_edit`（mode=append，scene="work"）追加到对应人员条目：
   - **条目标题**：`人员日志 - {姓名}`（tags: `["people", "{姓名}"]`）
   - **追加内容**：
     ```
     ## {MM-DD}
     - {事件描述}（{HH:MM}）
     ```
   - 条目不存在时先 `knowledge_add` 创建初始文件（含当月标题），再追加
3. 回复确认：列出写入了哪些人、各写了什么

**总计最多 3 步**：提取 → knowledge_edit → 确认。

### 「业务进展 / 工作进展」

当用户说「更新业务进展」「更新工作进展」或发送文档/链接要求更新进展时，**不要 web_search、不要 knowledge_search**，直接执行：

**判断标准**：只要用户意图是"把某些人做的事/项目进展记录下来"，即使没有精确命中 trigger 关键词，也应走此路径。

1. 读取文档/上下文内容，提取**每个人做的最关键的事**（精简，不要太多太细）
2. **写 people**：对每个人，用 `knowledge_edit`（scene="work"）追加到 `人员日志 - {姓名}`
3. **写 project**：用 `knowledge_edit`（scene="work"）追加到 `项目进展 - {业务名} - {项目名}`（tags: `["project", "{业务名}", "{项目名}"]`），格式：
   ```markdown
   ## {YYYY-MM-DD}
   - {进展条目}
   ```
   - 业务名从上下文判断，不确定时询问用户
   - 项目名由模型根据内容判断
   - 进展涉及具体人时注明 `（@{姓名}）`
4. 回复确认：列出更新了哪些人、哪些项目

**总计最多 4 步**：读取 → 写 people → 写 project → 确认。

### 「工作沉淀整理 / 分类写入」

当用户说「整理下 XX 的工作沉淀」「整理这个同事的沉淀，分类写入」「把这份文档按类别整理进来」时，**不要 file_write、不要 shell mkdir**，直接执行：

1. 拉取原文（若用户给了飞书 docx 链接，用 `lark-cli docs +fetch` 拉 markdown；若是网页用 `web_fetch`）
2. 按内容结构分类（如：技术沉淀、项目复盘、方法论、踩坑总结、团队协作等，由内容决定）
3. **每一类创建一个独立的知识库条目**，用 `knowledge_add`（scene="work"）：
   - **标题**：`{姓名}工作沉淀 - {分类名}`（如 `范文杰工作沉淀 - 方法论`）
   - **tags**：`["doc", "people", "{姓名}", "{分类名}"]`
   - **frontmatter**：`{"source": "{原始文档 URL}"}` —— **必传**（见硬规则 R2）
   - **内容**：
     ```markdown
     # {分类名}

     > 原文：{url}
     > 作者：{姓名}
     > 整理日期：{YYYY-MM-DD}

     {按内容结构组织，保留关键观点、数据、方法，去掉口水话}
     ```
4. **同时追加一条事件到该成员的 `人员日志 - {姓名}`**（用 `knowledge_edit` mode=append，scene="work"）：
   ```
   ## {MM-DD}
   - [亮点] 整理了工作沉淀（{分类数} 个分类），原文：{url}（{HH:MM}）
   ```
5. 回复确认：列出创建了多少个分类条目、各自标题、原文链接已写入 front matter

**总计 4-5 步**：拉取原文 → 分类整理 → knowledge_add 写入（每类一条）→ knowledge_edit 追加 people 事件 → 确认。

**关键约束**：
- 不要用 `file_write`，只用 `knowledge_add` / `knowledge_edit`
- 不要自己拼路径，让后端管
- 原文 URL **必须**通过 `frontmatter={"source": ...}` 传入，不要只在正文里写「原文：xxx」
- 多个分类可以并行 `knowledge_add`，提高效率

### 「文档/链接收藏」

当用户发送文档链接、或说「收藏这个」「存一下」，或 Agent 在处理过程中**解析了任何文档/链接**时，**自动追加收藏记录**：

1. 解析文档：提取标题、链接、一句话摘要、作者（可选）、日期
2. 判断归属业务（从上下文判断，不确定时用"未分类"）
3. 用 `knowledge_add`（scene="work"）创建收藏条目：
   - **标题**：`文档收藏 - {文档标题}`
   - **tags**：`["doc", "{业务名}", "{分类}"]`
   - **frontmatter**：`{"source": "{url}"}` —— **必传**（见硬规则 R2）
   - **内容**：
     ```markdown
     - 链接：{url}
     - 一句话介绍：{摘要}
     - 作者：{作者}
     - 日期：{YYYY-MM-DD}
     ```
4. 回复中附带「已收藏到知识库（scene=work）」

**注意**：这是**附带动作**——即使用户的主要意图是"更新进展"或"文档分析"，只要解析了链接就顺带收藏。frontmatter 必传规则见硬规则 R2。

## 🎯 三大核心场景

### 场景 A：绩效管理

持续收集团队成员工作事件，绩效季自动汇总并生成评估建议。

**能力**：
1. **手动记录** — 你随时说，Agent 自动写入对应成员的 people 日志
2. **文档分析** — 转发下属文档时，提取亮点数据、架构思路、业务价值
3. **CR 统计** — 按人汇总代码产出、质量问题、需求归属
4. **绩效汇总** — 绩效季按人输出全景 + 初步评估建议

详见：
- `references/people-log.md` — 人员日志格式与写入规则
- `references/analysis.md` — 文档分析 & CR 分析模板
- `references/review-guide.md` — 绩效评估报告生成指南

### 场景 B：任务委派

将任务分配给团队成员，自动拆解阶段、创建飞书任务、设置 checkpoint 提醒。

**能力**：
1. **任务拆解** — 接收描述，拆分为可跟踪的阶段性子任务
2. **创建飞书任务** — 为每个阶段创建飞书任务，设置到期日和提醒
3. **Checkpoint 跟踪** — 关键节点前自动提醒，确保按计划推进
4. **绩效联动** — 任务完成/延期自动写入对应人员的 people 日志

详见：
- `references/workflow.md` — 委派流程 SOP 与 Checkpoint 拆分指南

### 场景 C：提醒与自动化

主动追踪项目节点、交付截止、例行巡检，到点自动提醒，不用人盯。

**能力**：
1. **项目节点提醒** — 项目进展中记录了时间节点（如"8.15 完成 xxx"），到点前主动提醒
2. **交付截止提醒** — 任务委派时设置 DDL，DDL 前 1 天/当天自动提醒
3. **例行巡检** — 每日晨间扫描项目进展，发现延期风险主动预警
4. **绩效季提醒** — 绩效季临近时主动提醒收集数据、整理 people 日志

提醒通过 `schedule_create`（schedule-manager 技能）实现，本技能负责定义"提醒什么"和"什么时候提醒"。

**自动建议提醒**：当 Agent 在写 project 进展或委派任务时，若内容中包含明确的时间节点（如"8.15 前完成"、"下周五交付"），**主动建议**用户创建提醒：
- 「检测到时间节点「8.15 完成 xxx」，要设个提前 2 天的提醒吗？」
- 用户确认后，调 `schedule_create` 创建一次性提醒（category="one_off"）

**例行巡检建议**：首次使用时，Agent 主动建议创建以下例行任务：
- 每日晨间（9:00）扫描 project 进展，发现临近节点/已逾期事项
- 每周五（16:00）CR 汇总（已有，见 CR 分析章节）
- 每季度首月 15 号提醒绩效数据收集

详见：
- `references/workflow.md` — 任务委派时的提醒设置流程
- `schedule-manager` 技能 — 定时任务创建与管理

## 📁 数据存储

### 统一走知识库（scene=work）

所有团队管理数据通过 `knowledge_add` / `knowledge_search` / `knowledge_read` / `knowledge_edit` 读写，`scene="work"` 隔离。后端切到 Obsidian 时数据自然出现在 vault 的 `work/` 子目录下。

**条目类型与 tags 约定**：

| 类型 | 标题格式 | tags | 写入方式 |
|---|---|---|---|
| 人员日志 | `人员日志 - {姓名}` | `["people", "{姓名}"]` | knowledge_edit(append) |
| 项目进展 | `项目进展 - {业务名} - {项目名}` | `["project", "{业务名}", "{项目名}"]` | knowledge_edit(append) |
| 业务范围 | `业务范围 - {业务名}` | `["scope", "{业务名}"]` | knowledge_edit(replace) |
| 文档收藏 | `文档收藏 - {文档标题}` | `["doc", "{业务名}", "{分类}"]` | knowledge_add |
| 工作沉淀 | `{姓名}工作沉淀 - {分类名}` | `["doc", "people", "{姓名}", "{分类名}"]` | knowledge_add |
| CR 周报 | `CR周报 - {业务名} - {YYYY}-W{NN}` | `["cr-report", "{业务名}"]` | knowledge_add |
| 绩效草稿 | `绩效草稿 - {YYYY}-Q{N}` | `["review", "{YYYY}-Q{N}"]` | knowledge_add / knowledge_edit |

**frontmatter 必传场景**（见硬规则 R2）：文档收藏、工作沉淀、CR 周报等任何内容派生自外部文档/链接的条目，`knowledge_add` / `knowledge_edit` 调用时必须传 `frontmatter={"source": "{原始 URL}"}`。人员日志、项目进展等内部记录无需传。

**查询方式**：
- `knowledge_search(query="{姓名}", scene="work")` → 搜该人员的所有记录
- `knowledge_search(query="{业务名} 项目", scene="work")` → 搜该业务的项目进展
- `knowledge_search(query="cr-report {业务名}", scene="work")` → 搜该业务的 CR 报告

### team.yaml（配置文件，不走知识库）

团队配置仍用文件读写，位于 `~/.ethan/work/team.yaml`。模板见 `templates/team.yaml.example`。

```yaml
# team.yaml 示例
self:
  name: {你的名字}
members:
  - name: {成员名}
    code_username: {git用户名}    # 用于 CR 统计
    open_id: {飞书open_id}        # 用于创建任务/发消息
projects:
  - name: {项目名}
    repo: {仓库路径}
review:
  cycle: quarterly                 # quarterly | monthly
  dimensions: [产出与交付, 技术质量, 主动性与影响力, 成长趋势]
```

### people 日志格式

按人按月按日记录，用 `knowledge_edit`（append）追加到 `人员日志 - {姓名}` 条目。最新月份在上，月份间用 `---` 分隔：

```markdown
# 2026-07

## 07-21
- [亮点] 完成了支付模块联调，性能提升 30%（14:30）
- [问题] 线上 P1 告警，Redis 连接池耗尽（03:15）
- 参加了周会（10:00）

## 07-20
- 提出重构库存查询方案，被采纳（10:00）

---

# 2026-06

## 06-28
- 修复线上 P1 告警，根因是 Redis 连接池耗尽（03:15）
```

**标签约定**：`[亮点]` / `[问题]` / `[进展]` 可选，普通事件不加标签。

详见 `references/people-log.md`。

### project 进展格式

用 `knowledge_edit`（append）追加到 `项目进展 - {业务名} - {项目名}` 条目。格式：

```markdown
## 2026-07-21
- xxx 开发中（@小王）
- xxx 已提测（@小李）

## 2026-07-15
- xxx 已完成上线（@小王）

> 路线：7.25 前实现基础功能，8.15 实现 xxx，8.24 完成 xxx
```

**规则**：
- 每次追加一个 `## {YYYY-MM-DD}` 日期标题，下列进展条目
- `>` 引用块写路线或 checkpoint 描述（含时间节点，可让 schedule-manager 创建提醒）
- 进展条目涉及具体人时注明 `（@{姓名}）`

## 🔑 触发识别规则

### 绩效记录

| 用户输入模式 | Agent 行为 |
|---|---|
| `记一下，{姓名}...` | 识别人名 → knowledge_edit 追加到 `人员日志 - {姓名}`（按月去重） |
| `我的记录：...` | knowledge_edit 追加到 `人员日志 - {我的名字}` |
| `{姓名}做了/完成/修复了...` | 识别人名和事件 → knowledge_edit 追加到 `人员日志 - {姓名}` |
| `整理进 people` / `记到 people` | **快速路径**（见上方） |
| `更新业务进展` / `更新工作进展` | **快速路径：业务进展**（见上方） |
| `{姓名}最近怎么样` | knowledge_search 搜该人员 → 读取最近 1-2 个月记录，综合回顾 |
| `{姓名}的事` / `{姓名}做了什么` | knowledge_search 搜该人员 → 按时间顺序总结 |

**写入规则**：
- 单一数据源：所有事件只追加到对应人员的 `人员日志 - {姓名}` 条目
- 标签可选：`[亮点]` `[问题]` `[进展]` 用于标记事件类型，普通事件不加标签
- 按月去重：写入前先 `knowledge_read` 看当月已有记录，完全相同文本静默跳过，核心动词+对象重叠则询问合并/替换/另记
- `[进展]` 标签明确表示是事件更新而非重复，写入时不触发去重询问

### 文档分析

当用户发送文档链接或说「帮我看看这个文档」时：
1. 读取文档内容
2. 提取亮点（数据/架构/业务价值/风险）
3. 询问归属人
4. 用 `knowledge_edit` 追加到 `人员日志 - {姓名}`，带 `[亮点]` 或 `[问题]` 标签

### CR 分析

用户说「CR 汇总」「代码产出统计」「本周 CR」时，或定时任务触发周度 CR 汇总时：
1. 读取 `team.yaml` 确定当前业务方向和关注的仓库/项目
2. 调用 Codebase API 拉取对应仓库最近一周的 MR 数据（按团队成员过滤）
3. 按人统计：MR 数量、代码行数、涉及仓库、关联需求
4. 识别质量问题（P0/P1）和正面信号（见 `references/analysis.md`）
5. 用 `knowledge_add`（scene="work"）创建 CR 周报条目：`CR周报 - {业务名} - {YYYY}-W{NN}`
6. 提取值得记录的事件用 `knowledge_edit` 追加到对应 `人员日志 - {姓名}`（带 `[亮点]` 或 `[问题]` 标签）
7. 回复摘要（关键产出 + 质量趋势）

**定时任务建议**（用户可配置到 `schedule-manager`）：

> 每周五下午对本周团队 MR 做一次 CR 汇总。读取 team.yaml 获取成员和关注仓库列表，调用 Codebase API 拉取本周 MR，按 team-manager 技能的 CR 分析流程生成周报，写入知识库（scene=work），并将关键事件同步到对应人员日志。完成后发送摘要给我。

### 任务委派

用户说「安排一下」「交给 XX」时：
1. 解析任务内容、被委派人
2. 确认 DDL
3. 拆分 checkpoint
4. 创建飞书任务 + 设置提醒（提醒创建交给 `schedule-manager`）
5. **检测时间节点**：若 checkpoint 含明确日期，主动建议创建 `schedule_create` 提醒（category="one_off"）

详见 `references/workflow.md`。

### 群消息提取

用户说「帮我监控这个群」时：
1. 获取群 chat_id（若已在群内 @bot 则自动取当前群）
2. 询问扫描频率（默认每天 22:00）和时间窗口（默认最近 24 小时）
3. 创建一个定时任务（通过 `schedule-manager` 的 `schedule_create`），prompt 使用群扫描模板
4. 定时任务触发时，Agent 按模板步骤拉取消息、识别候选事件、输出去重清单
5. 用户在原渠道回复「入库 1,3,5」确认后用 `knowledge_edit` 追加到对应 `人员日志 - {姓名}`

详见 `references/group-scan-prompt.md`。

## ⚙️ 首次配置

1. 复制 `templates/team.yaml.example` → `~/.ethan/work/team.yaml`，填入团队信息
2. 开始使用——群监控、文档分析、CR 统计均为用户主动触发，无需预配置
3. Agent 首次使用时会主动建议创建例行巡检任务（每日晨间扫描、每周五 CR 汇总等）

## 🔗 关联技能

| 技能 | 联动方式 |
|---|---|
| `schedule-manager` | 定时任务和时间线管理（任务提醒、周期编排、节点提醒） |
| `code-review` / `bytedance-code-review` | CR 结果记录到 people 日志 |
| `lark-task` | 创建飞书任务和子任务 |
| `lark-im` | 发送提醒消息、识别群聊事件（写入 people 日志） |
| `lark-doc` | 读取文档内容 |
| `lark-minutes` | 从飞书妙记提取信息 |
| `lark-calendar` | 为评审/对齐创建日历事件 |
| `lark-contact` | 解析成员 open_id |

## ⚠️ 约束

- **确认后再创建**：任务拆分方案、飞书任务创建、定时提醒创建，必须经用户确认
- **不做最终绩效判定**：Agent 只提供汇总和建议，打分由管理者决定
- **隐私边界**：所有记录仅存本地知识库，不上传外部服务
- **客观记录**：people 日志以事实描述为主，避免主观判断词
- **不越权**：Agent 不自行修改 DDL 或取消任务
- **scene 固定为 work**：team-manager 的所有知识库操作 scene="work"，不要混用其他 scene
- **写入工具**：禁止用 `file_write` / `shell` 写知识库内容，只用 `knowledge_add` / `knowledge_edit`（见硬规则 R1）
- **链接保留**：内容来自外部文档/链接时，`frontmatter={"source": ...}` 必传，不要只在正文里写「原文：xxx」（见硬规则 R2）
