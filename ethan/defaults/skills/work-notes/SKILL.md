---
name: work-notes
version: 1.0.0
description: >
  项目与文档沉淀助理。把零散的工作信息按结构沉淀进知识库，四件事：
  ① 项目进展 — 按业务+项目记录进展，含时间节点；
  ② 业务范围 — 维护业务方向和关注仓库；
  ③ 文档收藏 — 解析链接自动收藏，保留原文 source；
  ④ 工作沉淀整理 — 把文档按分类整理进知识库。
  进展中的时间节点转交 schedule-manager 识别并建提醒；涉及具体人时同步到 people-kb 档案。
trigger: "工作进展|业务进展|更新进展|项目进展|进展整理|工作沉淀|沉淀整理|分类写入|整理文档|收藏文档|收藏链接|存个文档|记个链接|业务范围|业务方向|项目路线|项目节点"
author: Ethan Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  ethan:
    tags: [Work, Project, Document, Knowledge]
---

# Work Notes（项目与文档沉淀）

> 把项目进展、业务范围、文档收藏、工作沉淀结构化写入知识库（`scene` 区分 work/life）。
> 时间节点交 `schedule-manager`；涉及人时同步 `people-kb`。

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

### 业务范围维护

**触发**：「更新业务范围」「记一下我们业务方向」。

`knowledge_edit`（replace，scene="work"）整篇维护 `业务范围 - {业务名}`：业务方向、关注仓库、核心项目、关键指标。作为 team-manager CR 分析和绩效汇总的背景。

## 🔗 关联技能

| 技能 | 联动 |
|---|---|
| `url-process` | 消息含 URL 时先走它做平台识别与抓取 |
| `schedule-manager` | 进展中的时间节点转交它建提醒 |
| `people-kb` | 涉及人的进展/沉淀同步到人物档案 |
| `lark-doc` / `lark-minutes` | 读飞书文档/妙记原文 |

## ⚠️ 约束

- **隐私边界**：所有记录仅存本地知识库，不上传外部
- **来源可溯**：外部内容必带 source（R2）
- **不重复造时间逻辑**：提醒/定时一律交 schedule-manager
