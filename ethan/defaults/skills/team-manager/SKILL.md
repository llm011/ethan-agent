---
name: team-manager
version: 1.0.0
description: >
  团队管理助理（面向带团队的 leader）。基于 people-kb 的人物档案，做四件管理向的事：
  ① CR 分析 — 按团队成员统计周度 MR、识别质量问题与正面信号，产出 CR 周报；
  ② 绩效汇总 — 从人物档案时间线 + CR 周报按维度汇总，生成绩效草稿（不做最终判定）；
  ③ 任务委派 — 拆 checkpoint、创建飞书任务、配节点提醒；
  ④ 群消息扫描 — 定时扫团队群，识别值得记录的人员事件。
  识别到的人员事件统一写进 people-kb 的 `人物 - {姓名}` 档案（带工作标签）。
  定时任务/提醒由 task-and-schedule-manager 负责，本技能只负责识别与汇总。
trigger: "汇总绩效|绩效总结|绩效报告|绩效草稿|团队总结|周报汇总|CR汇总|CR周报|代码产出|代码统计|本周CR|分配任务|委派|布置任务|安排.*出方案|任务跟踪|checkpoint|拆解任务|团队管理|监控.*群|扫.*群|群消息|群扫描"
author: Ethan Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  ethan:
    tags: [Team, Work, Performance, CodeReview, Task, Management]
---

# Team Manager（团队管理）

> 面向带团队的管理者。人员事件的**存储格式归 `people-kb` 管**（写进 `人物 - {姓名}` 档案）；
> 本技能负责**识别、统计、汇总、委派**这些管理动作。
> 定时任务和提醒由 `task-and-schedule-manager` 负责。

## 🚫 硬规则

### R1：写人物事件走 people-kb 格式，只用 knowledge_* 工具

所有人员事件写入 `人物 - {姓名}` 档案（scene="work"），格式见 people-kb 的 `references/profile-format.md`。禁止 `file_write` / `shell`，禁止自己拼 vault 路径。

- 追加事件 → `knowledge_edit(source, content, mode="append", scene="work")`
- 档案不存在 → 先 `knowledge_add` 建档（people-kb 新建模板），再写 memory 指针（people-kb R3）
- CR 周报 / 绩效草稿是独立条目，用 `knowledge_add`

### R2：外部文档来源必传 frontmatter

CR 周报、绩效草稿等内容派生自外部文档/链接时，传 `frontmatter={"source": "{原始 URL}"}`。固定字段（title/type/tags/created/updated）由后端管理，不重复传。

### R3：title 命名规范

`knowledge_add` 的 title 决定文件名。禁止 `/`、`\`、连续 `-`、连续空格、前后空格。版本号/日期紧凑：`W28`、`Q2`、`0715`。外部长标题精简后再填。

## 📇 条目类型

| 类型 | 标题格式 | tags | scene | 写入方式 |
|---|---|---|---|---|
| 人物事件 | `人物 - {姓名}`（people-kb 档案） | `["people", "{姓名}", ...]` | work | knowledge_edit(append) |
| CR 周报 | `CR周报 - {业务名} - {YYYY}-W{NN}` | `["cr-report", "{业务名}"]` | work | knowledge_add |
| 绩效草稿 | `绩效草稿 - {YYYY}-Q{N}` | `["review", "{YYYY}-Q{N}"]` | work | knowledge_add / knowledge_edit |

## ⚡ 快速路径

### CR 分析

**触发**：「CR 汇总」「代码产出统计」「本周 CR」，或定时任务触发周度汇总。

1. 读 `~/.ethan/work/team.yaml` 确定成员、业务方向、关注仓库
2. 调 Codebase API 拉最近一周 MR（按成员过滤）
3. 按人统计：MR 数、代码行数、涉及仓库、关联需求
4. 识别质量问题（P0/P1）与正面信号（见 `references/analysis.md`）
5. `knowledge_add`（scene="work"）创建 `CR周报 - {业务名} - {YYYY}-W{NN}`
6. 值得记录的事件 `knowledge_edit` 追加到对应 `人物 - {姓名}`（带 `[亮点]`/`[问题]`，格式见 people-kb）
7. 回复摘要（关键产出 + 质量趋势）

### 绩效汇总

**触发**：「汇总绩效」「绩效报告」「绩效总结」，或绩效季前主动提醒。

1. 读 `team.yaml` 成员列表
2. 每人 `knowledge_search(query="人物 {姓名}", scene="work")` → `knowledge_read` 读本季度时间线
3. `knowledge_search(query="cr-report", scene="work")` 读当季 CR 周报
4. 按标签分组（`[亮点]`/`[问题]`/`[进展]`/普通），按四维度汇总
5. `knowledge_add`（scene="work"）生成 `绩效草稿 - {YYYY}-Q{N}`
6. 详见 `references/review-guide.md`

**不做最终判定**：只给汇总和建议区间，打分由管理者决定。

### 任务委派

**触发**：「安排一下 X，做 Y，下周五前出方案」「委派」「布置任务」。

1. 解析任务（assignee/title/描述/产出/DDL）
2. 确认 DDL（用户没给就按复杂度建议后确认）
3. 拆 checkpoint（模板见 `references/workflow.md`）
4. 调 `lark-task` 创建主任务 + 子任务
5. **节点提醒转交 `task-and-schedule-manager`**：对每个 checkpoint 调 `schedule_create`（category="one_off"）
6. 任务状态变化时，`knowledge_edit` 追加到 `人物 - {assignee}` 档案（完成/延期，带标签）
7. 详见 `references/workflow.md`

### 群消息扫描

**触发**：「帮我监控这个群」。

1. 取群 chat_id（已在群内 @bot 则取当前群）
2. 确认扫描频率（默认每天 22:00）和窗口（默认 24h）
3. 调 `task-and-schedule-manager` 的 `schedule_create` 建定时任务，prompt 用 `references/group-scan-prompt.md` 模板
4. 触发时拉消息、识别候选、输出去重清单
5. 用户回复「入库 1,3,5」后 `knowledge_edit` 追加到对应 `人物 - {姓名}`
6. 详见 `references/group-scan-prompt.md`

### 文档分析（下属产出）

用户转发下属的技术方案/周报/设计文档：

1. 读文档内容
2. 按 `references/analysis.md` 框架提取亮点（数据/架构/业务价值/风险）
3. 确认归属人
4. `knowledge_edit` 追加到 `人物 - {姓名}`，带 `[亮点]`/`[问题]`
5. 文档中的时间节点转交 `task-and-schedule-manager` 识别

## ⚙️ 配置

`~/.ethan/work/team.yaml` — 团队信息（成员、业务方向、关注仓库、绩效配置），用文件读写（不走知识库）。模板见 `templates/team.yaml.example`。

## 🔗 关联技能

| 技能 | 联动 |
|---|---|
| `people-kb` | 人员事件的档案格式与存储归它管；本技能往 `人物 - {姓名}` 写工作事件 |
| `task-and-schedule-manager` | 节点提醒、群扫描定时任务、绩效季提醒、CR 周度汇总定时任务 |
| `code-review` / `bytedance-code-review` | CR 数据拉取与分析 |
| `lark-task` | 创建飞书任务和子任务 |
| `lark-im` | 发提醒、扫群消息 |
| `lark-doc` / `lark-minutes` | 读文档/妙记内容分析 |
| `lark-contact` | 解析成员 open_id |

## ⚠️ 约束

- **确认后再创建**：任务拆分、飞书任务、定时提醒经用户确认
- **不做最终绩效判定**：Agent 只汇总建议，打分归管理者
- **隐私边界**：所有记录仅存本地知识库，不上传外部
- **客观记录**：人物事件以事实为主，避免主观评价词
- **敏感信息**：薪资、绩效评级不写进 people-kb 时间线（绩效草稿是独立条目）

## 📎 详细规范

- `references/analysis.md` — 文档分析 & CR 分析模板
- `references/review-guide.md` — 绩效评估报告生成
- `references/workflow.md` — 委派流程 SOP 与 checkpoint 拆分
- `references/group-scan-prompt.md` — 群扫描 prompt 模板
