---
name: work-notes
version: 1.1.0
description: >
  工作过程记录与沉淀助理（聚焦"事"）。把零散的工作信息按结构沉淀进知识库，五件事：
  ① 项目进展 — 按业务+项目记录进展，含时间节点；
  ② 业务范围 — 维护业务方向和关注仓库；
  ③ 文档收藏 — 解析链接自动收藏，保留原文 source；
  ④ 工作沉淀整理 — 把文档按分类整理进知识库；
  ⑤ 每日例行 — 每天固定要有产品体验/文档阅读/工作梳理三类日程（不固定时间），
     由 heartbeat 心跳在工作日白天范围内检查状态、决定是否提醒，支持飞书通知和跳过记录。
  进展中的时间节点转交 schedule-manager 识别并建提醒；涉及人时同步到 people-kb 档案。
  与 team-manager 分工：本技能记录"事"的工作过程，team-manager 记录"人"的工作结果。
trigger: "工作进展|项目进展|业务范围|工作沉淀|收藏文档|收藏链接|每日例行|配置每日例行|产品体验|文档阅读|工作梳理|每日回顾|今天不做"
author: Ethan Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  ethan:
    tags: [Work, Project, Document, Knowledge, Routine, Daily]
---

# Work Notes（工作过程记录与沉淀）

> 把项目进展、业务范围、文档收藏、工作沉淀、每日例行结构化写入知识库（`scene` 区分 work/life）。
> 时间节点交 `schedule-manager`；涉及人时同步 `people-kb`。
> **定位**：记录"事"的工作过程。团队成员的工作结果（绩效、CR、表现）归 `team-manager`。

## 🚫 硬规则

### R1：写知识库只用 knowledge_* 工具

所有写入通过 `knowledge_add` / `knowledge_edit`。禁止 `file_write` / `shell`，禁止自己拼 vault 路径。

- 新建 → `knowledge_add(title, content, tags, scene, frontmatter)`
- 追加 → `knowledge_edit(source, content, mode="append", scene)`
- 整篇替换 → `knowledge_edit(source, content, mode="replace", scene, frontmatter)`

### R2：外部来源必传 frontmatter={"source": ...}

内容派生自外部网页/飞书文档/链接时（用户给了 URL，或你用 lark-cli / web_fetch 拉过原文），必传 `frontmatter={"source": "{原始 URL}"}`。固定字段（title/type/tags/created/updated）由后端管理，不重复传；可按需追加 `author`/`published`。

### R3：scene 区分

工作向（项目、业务、工作沉淀）→ `work`；生活向（个人收藏、生活文档）→ `life`。拿不准默认 `work`。

### R4：title 命名规范

title 决定文件名。禁止 `/`、`\`、连续 `-`、连续空格、前后空格。外部长标题精简后再填（`文档收藏 - Coze插件协议PRD` 而非塞入原始多层标题）。版本号/日期紧凑：`W28`、`Q2`、`0715`。英文小写。

## 📇 条目类型

| 类型 | 标题格式 | tags | scene | 写入方式 |
|---|---|---|---|---|
| 项目进展 | `项目进展 - {业务名} - {项目名}` | `["project", "{业务名}", "{项目名}"]` | work | knowledge_edit(append) |
| 业务范围 | `业务范围 - {业务名}` | `["scope", "{业务名}"]` | work | knowledge_edit(replace) |
| 文档收藏 | `文档收藏 - {文档标题}` | `["doc", "{业务名}", "{分类}"]` | work/life | knowledge_add |
| 工作沉淀 | `{姓名}工作沉淀 - {分类名}` | `["doc", "people", "{姓名}", "{分类名}"]` | work | knowledge_add |
| 产品体验 | `产品体验 - {YYYY-MM}` | `["routine", "product", "{YYYY-MM}"]` | work | knowledge_edit(append) |
| 工作梳理 | `工作梳理 - {YYYY-MM}` | `["routine", "reflection", "{YYYY-MM}"]` | work | knowledge_edit(append) |
| 每日回顾 | `每日例行回顾 - {YYYY-MM}` | `["routine", "daily-review", "{YYYY-MM}"]` | work | knowledge_edit(append) |

## ⚡ 快速路径

### 业务进展 / 工作进展

**触发**：「更新业务进展」「更新工作进展」，或发文档/链接要求更新进展。只要意图是"把某些项目进展记下来"，即使没精确命中 trigger 也走此路径。

1. 读文档/上下文，提取每个项目的关键进展（精简）
2. `knowledge_edit`（append，scene="work"）追加到 `项目进展 - {业务名} - {项目名}`：
   ```markdown
   ## {YYYY-MM-DD}
   - {进展条目}（@{姓名}）
   ```
3. **涉及具体人的进展** → 同步一条到 people-kb 的 `人物 - {姓名}` 档案（格式见 people-kb 的 `references/profile-format.md`）
4. **含时间节点**（如"8.15 完成"）→ 转交 `schedule-manager` 走定时信号识别
5. 回复：更新了哪些项目、哪些人

### 项目进展格式

追加到 `项目进展 - {业务名} - {项目名}`：

```markdown
## 2026-07-21
- xxx 开发中（@小王）
- xxx 已提测（@小李）

## 2026-07-15
- xxx 已完成上线（@小王）

> 路线：7.25 前基础功能，8.15 实现 xxx，8.24 完成 xxx
```

- 每次追加一个 `## {YYYY-MM-DD}` 日期标题
- `>` 引用块写路线/checkpoint（含时间节点，触发 schedule-manager 识别）
- 涉及人时注明 `（@{姓名}）`

### 文档 / 链接收藏

**触发**：用户发文档链接、说「收藏这个」「存一下」，或 Agent 处理中解析了任何文档/链接时**自动追加收藏**。

1. 解析：标题、链接、一句话摘要、作者（可选）、日期
2. 判断归属业务（不确定用"未分类"）
3. `knowledge_add`（scene 按内容判断）：
   - 标题：`文档收藏 - {文档标题}`
   - tags：`["doc", "{业务名}", "{分类}"]`
   - frontmatter：`{"source": "{url}"}`（R2）
   - 内容：
     ```markdown
     - 链接：{url}
     - 一句话介绍：{摘要}
     - 作者：{作者}
     - 日期：{YYYY-MM-DD}
     ```

> 注：如果用户消息里带 URL，先走 `url-process` 技能做平台识别与抓取，再回到这里做收藏落库。

### 工作沉淀整理 / 分类写入

**触发**：「整理下 XX 的工作沉淀」「按类别整理进来」。

1. 拉原文（飞书 docx 用 `lark-cli docs +fetch`；网页用 `url-process` / `web_fetch`）
2. 按内容结构分类（技术沉淀、项目复盘、方法论、踩坑总结、团队协作等，由内容决定）
3. **每类一个独立条目**，`knowledge_add`（scene="work"）：
   - 标题：`{姓名}工作沉淀 - {分类名}`
   - tags：`["doc", "people", "{姓名}", "{分类名}"]`
   - frontmatter：`{"source": "{原始 URL}"}`（R2）
   - 内容：
     ```markdown
     # {分类名}

     > 原文：{url}
     > 作者：{姓名}
     > 整理日期：{YYYY-MM-DD}

     {保留关键观点、数据、方法，去口水话}
     ```
4. **同步一条到 people-kb** 的 `人物 - {姓名}` 档案（mode=append，scene="work"）：
   ```
   ## {MM-DD}
   - [亮点] 整理了工作沉淀（{分类数} 个分类），原文：{url}（{HH:MM}）
   ```
5. 回复：创建了多少分类、各自标题、原文链接已写 front matter

### 每日例行（产品体验 / 文档阅读 / 工作梳理）

**触发**：「每日例行」「配置每日例行」「产品体验」「文档阅读」「工作梳理」「每日回顾」「今天不做 XX」。

**核心理念**：每天固定要有这三类日程，但不固定执行时间。由 heartbeat 心跳在时间范围内检查状态、决定是否提醒，而非 cron 定时触发。

#### 三类例行内容

| 例行 | 建议时段 | 时长 | 做什么 |
|---|---|---|---|
| 产品体验 | 上午 | 20-30 分钟 | 真实使用自家产品，发现可用性/功能/性能问题与灵感 |
| 文档阅读 | 午后/下午 | 20-30 分钟 | 读一篇技术/业务文档，提取观点+启发 |
| 工作梳理 | 下午尾声/傍晚 | 15-20 分钟 | 挑 1-2 个核心事项，梳理状态/思考/下一步 |

建议时段只是参考，用户可在时间范围内任意时间执行。可跳过、可合并、可调整。

#### 驱动机制：heartbeat + 状态文件

**不使用 cron 定时**。通过 heartbeat 心跳驱动，心跳每次触发时检查状态文件决定是否提醒。

**1. 配置（首次使用）**

用户说「配置每日例行」时，Agent 询问并写入配置文件 `{workspace}/system/routine-config.json`：

```json
{
  "enabled": true,
  "workdays": [1, 2, 3, 4, 5],
  "time_range": {"start": "09:00", "end": "19:00"},
  "suggest_windows": {
    "product": ["09:00", "12:00"],
    "reading": ["13:00", "16:00"],
    "reflection": ["16:00", "19:00"]
  },
  "max_reminds_per_day": 2,
  "notify_channel": null
}
```

- `workdays`：工作日（1=周一 … 7=周日），默认周一到周五
- `time_range`：心跳处理例行的时间范围，范围外不提醒
- `suggest_windows`：各类例行的建议时段（提醒只在这些时段内触发）
- `max_reminds_per_day`：每类每日最多提醒次数（默认 2 次：开始时 1 次+临近结束 1 次）
- `notify_channel`：通知渠道，`null` 表示未配置

**通知渠道配置**：Agent 主动询问「要不要配置飞书通知？每天到点提醒你」。用户同意后：
- 询问飞书账号（open_id 或姓名），用 `lark-cli contact +search` 解析成 open_id
- 写入 `notify_channel: {"type": "lark", "open_id": "ou_xxx"}`
- **每次用户使用每日例行功能时，若 `notify_channel` 为 null，都提醒一次**「还没配置通知渠道，要配置吗？」

**2. heartbeat 指令**

配置完成后，Agent 在 `{workspace}/system/heartbeat.md` 中追加一行（按 heartbeat 规范，若已存在 `[agent:work-notes]` 条目则跳过）：

```
[agent:work-notes] 检查每日例行状态
```

> heartbeat 规范见 `{workspace}/system/heartbeat.md` 顶部注释。指令一行写完，具体流程在本 SKILL.md 的「心跳检查流程」中定义。

**3. 状态文件**：`{workspace}/system/routine-state.json`

```json
{
  "date": "2026-08-03",
  "routines": {
    "product":    {"done": false, "remind_count": 0, "skip_reason": null, "last_remind": null, "last_done_time": null},
    "reading":    {"done": false, "remind_count": 0, "skip_reason": null, "last_remind": null, "last_done_time": null},
    "reflection": {"done": false, "remind_count": 0, "skip_reason": null, "last_remind": null, "last_done_time": null}
  }
}
```

**4. 心跳检查流程**（heartbeat 触发时 Agent 执行）

```
1. 读 routine-config.json，若 enabled=false 或当前不在 workdays/time_range 内 → 跳过
2. 读 routine-state.json：
   a. 若 date != 今天 → 先归档昨天的状态（写入知识库「每日例行回顾」），再初始化今天的新状态
   b. 遍历三类例行，对每一类：
      - 若 done=true 或 skip_reason!=null → 跳过
      - 若当前时间不在 suggest_windows 内 → 跳过
      - 若 remind_count >= max_reminds_per_day → 跳过
      - 否则 → 发提醒，remind_count++，last_remind=当前时间
3. 提醒发送：
   - 若 notify_channel 已配置 → 通过 lark-cli im +send 发飞书消息给主人
   - 若未配置 → 不发通知，但下次用户交互时提醒配置
4. 更新 routine-state.json
```

**提醒消息格式**（飞书）：
```
【每日例行提醒】{YYYY-MM-DD}
还没做：产品体验
建议时段：上午 09:00-12:00
回复「产品体验」开始记录，或回复「今天不做产品体验，因为...」跳过
```

**5. 用户执行例行**

用户说「产品体验」/「文档阅读」/「工作梳理」时：
1. 走下文的执行路径
2. 执行完成后，更新 routine-state.json：`done=true`，`last_done_time=当前时间`
3. 若 notify_channel 未配置，提醒一次「要配置飞书通知吗？」

**6. 跳过处理**

用户说「今天不做 XX，因为 YY」：
- 更新 routine-state.json：`skip_reason="YY"`
- 之后当天不再提醒该类
- 跳过原因会记入每日回顾

**7. 每日回顾**

触发：「每日回顾」/「今天的例行总结」/ 心跳在 time_range 结束前最后一次触发

1. 读 routine-state.json，汇总今日三类完成情况（done / skip_reason / 未做无原因）
2. `knowledge_edit`（append，scene="work"）追加到 `每日例行回顾 - {YYYY-MM}`：
   ```markdown
   ## {MM-DD}
   - 产品体验：✅ {一句话} / ❌ 跳过（{原因}）/ ❌ 未做
   - 文档阅读：✅ {一句话} / ❌ 跳过（{原因}）/ ❌ 未做
   - 工作梳理：✅ {一句话} / ❌ 跳过（{原因}）/ ❌ 未做
   - 明日重点：{1-2 件要跟进的事}
   ```
   条目不存在时先 `knowledge_add`（tags: `["routine", "daily-review", "{YYYY-MM}"]`）

**8. 跨天重置**

心跳在新的一天首次触发时：
1. 归档昨天的状态到知识库（走「每日回顾」流程，若昨天没做回顾）
2. 重置 routine-state.json：`date=今天`，所有 routines 恢复初始状态

#### 三类例行的执行路径

**1. 产品体验**

1. 选择一个功能点或使用路径（建议轮换覆盖，不要每天都走同一条路径）
2. 实际走一遍核心流程——是真实使用，不是测试用例执行
3. 记录发现：问题、痛点、灵感、对比竞品的差异
4. `knowledge_edit`（append，scene="work"）追加到 `产品体验 - {YYYY-MM}`：
   ```markdown
   ## {MM-DD}
   - 体验路径：{功能/路径名}
   - 发现：{问题描述或灵感}
   - 感受：{一句话感受}
   ```
   条目不存在时先 `knowledge_add`（tags: `["routine", "product", "{YYYY-MM}"]`）
5. 严重问题（影响主流程/数据安全）同步到任务跟踪系统（如已配置 `lark-task`）
6. 更新 routine-state.json：`product.done=true`

**2. 文档阅读**

文档来源（任选）：技术 spec / 设计文档 / 架构说明 / 业务 PRD / 需求文档 / 行业报告 / 技术博客 / 论文 / 开源项目 README。

1. 读取原文（网页用 `web_fetch`；飞书文档用 `lark-cli docs +fetch`；本地文件用 `file_read`）
2. 提取三层信息：核心观点 / 关键数据 / 对自己工作的启发
3. 走「文档/链接收藏」快速路径创建收藏条目（tags 加 `daily-reading`），内容追加：
   ```markdown
   - 关键观点：
     - {观点1}
     - {观点2}
   - 启发：{对自己工作的启发}
   ```
4. 若文档中含时间节点或待办，触发 `schedule-manager` 的定时信号识别
5. 更新 routine-state.json：`reading.done=true`

**3. 工作梳理**

事项来源：近期项目进展中未关闭的事项 / 待办清单中优先级最高的 1-2 项 / 用户口述的"最近在忙的" / 阻塞超过 2 天的事项（优先梳理）。

1. 识别 1-2 个核心事项（多了反而散，聚焦才有深度）
2. 对每个事项梳理三件事：
   - **当前状态**：进度到哪了 / 是否阻塞 / 是否已完成
   - **关键思考**：做了什么决策、为什么、有没有更好的选择
   - **下一步**：具体动作 + 时间节点（不是"继续推进"这种废话）
3. `knowledge_edit`（append，scene="work"）追加到 `工作梳理 - {YYYY-MM}`：
   ```markdown
   ## {MM-DD}
   ### {事项标题}
   - 状态：{进度/阻塞/已完成}
   - 思考：{关键决策或反思}
   - 下一步：{具体动作}（@{时间节点}）
   ```
   条目不存在时先 `knowledge_add`（tags: `["routine", "reflection", "{YYYY-MM}"]`）
4. 时间节点触发 `schedule-manager` 识别流程
5. 更新 routine-state.json：`reflection.done=true`

### 业务范围维护

**触发**：「更新业务范围」「记一下我们业务方向」。

`knowledge_edit`（replace，scene="work"）整篇维护 `业务范围 - {业务名}`：业务方向、关注仓库、核心项目、关键指标。作为 team-manager CR 分析和绩效汇总的背景。

## 🔗 关联技能

| 技能 | 联动 |
|---|---|
| `url-process` | 消息含 URL 时先走它做平台识别与抓取 |
| `schedule-manager` | 进展中的时间节点转交它建提醒 |
| `people-kb` | 涉及人的进展/沉淀同步到人物档案 |
| `lark-doc` / `lark-minutes` | 读飞书文档/妙记原文（文档阅读例行） |
| `team-manager` | 分工：本技能记"事"，team-manager 记"人" |
| `lark-im`（CLI） | 每日例行提醒发送飞书通知给主人 |
| `lark-contact`（CLI） | 解析飞书姓名为 open_id（配置通知渠道） |
| 系统心跳（heartbeat.md） | 每日例行的驱动源，心跳触发时检查状态并决定是否提醒 |

## ⚠️ 约束

- **隐私边界**：所有记录仅存本地知识库，不上传外部
- **来源可溯**：外部内容必带 source（R2）
- **不重复造时间逻辑**：定时提醒交 schedule-manager；每日例行的时间范围检查交 heartbeat
- **每日例行不强催**：每类每日最多提醒 `max_reminds_per_day` 次，用户跳过后当天不再提醒
- **通知渠道不擅自创建**：必须用户明确同意后才配置飞书通知；未配置时不发通知，下次交互时提醒一次
- **聚焦"事"**：涉及人的工作结果（绩效/CR/表现）转交 team-manager
- **状态文件不进知识库**：`routine-state.json` 和 `routine-config.json` 是运行时状态，放在 `{workspace}/system/`，不写入知识库
