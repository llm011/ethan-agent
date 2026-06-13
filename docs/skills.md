# Skill 系统设计文档

## 概述

Skill 是 Ethan 的知识模块，以 Markdown 文件形式存储在 `~/.ethan/skills/` 目录。当用户输入匹配到某个 Skill 的触发词时，该 Skill 的内容会被自动注入到 LLM 的 system prompt 中，引导 agent 按照特定流程处理问题。

---

## 设计参考

- **OpenClaw**: 人工编写的 Markdown skill 文件，按需加载进 context
- **Hermes**: 自我进化 — agent 完成复杂任务后自动生成新 skill

Ethan 兼顾两者：支持手写 Skill + 从经验自动生成。

---

## Skill 文件格式

存储位置：`~/.ethan/skills/<name>.md`

```markdown
---
name: weather-query
trigger: 天气|weather|气温|temperature
description: 查询天气的标准流程
---

# 查询天气

当用户询问天气时，使用 web_search 工具搜索实时天气信息。

步骤：
1. 确认用户想查询的城市
2. 使用 web_search 搜索 "[城市] 天气 today"
3. 从结果中提取温度、天气状况、建议
```

### Frontmatter 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | 唯一标识，kebab-case |
| `trigger` | 是 | 触发关键词，`|` 分隔 |
| `description` | 否 | 一句话描述 |

---

## 匹配机制

文件：`ethan/skills/registry.py`

```
用户输入 → 逐个检查每个 Skill 的 trigger 列表
         → 如果某个 trigger 关键词出现在用户输入中 → 命中
         → 最多注入 3 个 Skill 到 system prompt
```

这是简单的子串匹配。未来可以升级为 embedding 语义匹配。

---

## 注入方式

匹配到的 Skill 内容追加到 system prompt 尾部：

```
[原始 system prompt]

---
Relevant skills for this request:

[Skill: weather-query]
（skill 正文）
```

Agent Loop 本身不感知 Skill 的存在 — 它只看到一个更丰富的 system prompt。

---

## 自动生成（Hermes 风格）

文件：`ethan/skills/generator.py`

触发条件（未来集成到 REPL loop）：
- 当前 session 对话轮数 > 5
- 对话包含多步骤问题解决过程

流程：
1. 调用 LLM 分析对话："这是否包含一个值得提炼的可复用模式？"
2. 如果是 → 生成 Skill Markdown 文件 → 保存到 `~/.ethan/skills/`
3. 如果否 → 返回 NO_SKILL

---

## CLI 命令

```bash
ethan skill list                              # 列出所有 Skills
ethan skill show weather-query                # 查看 Skill 内容
ethan skill create my-skill -t "k1|k2" -d "desc"  # 创建空 Skill 文件
```

---

## 数据流

```
用户输入: "北京天气怎么样"
    │
    ▼
SkillRegistry.match("北京天气怎么样")
    │ 匹配到 trigger "天气"
    ▼
SkillRegistry.build_context() → Skill 正文
    │
    ▼
Agent._build_system() → 拼入 system prompt
    │
    ▼
LLM 收到增强后的 system prompt → 按照 Skill 描述的流程执行
    │ 调用 web_search 搜索天气
    ▼
返回结构化的天气信息
```

---

## 内置 Lark 技能

Ethan 内置了一套 Feishu（飞书）IM 操作技能，通过 `lark-cli` 工具链驱动。

### 默认内置：`lark-im.md`

`lark-im` 是默认内置的 Feishu IM 技能，存放在内置 skills 目录中。它是一个轻量级的引导文件（bootstrap），内容如下：

```markdown
---
name: lark-im
trigger: 飞书|lark|feishu|发消息|IM|群消息
description: 飞书 IM 操作（发消息、查群、管理会话等）
---

运行 `lark-cli skills read lark-im` 获取完整操作文档，然后按照文档指引执行飞书 IM 操作。
```

Agent 匹配到该技能后，会先执行 `lark-cli skills read lark-im` 获取完整文档，再根据文档内容执行具体的飞书操作。这种"按需拉取"的设计避免了把大量文档常驻 context。

### 其他可用 Lark 技能

通过 `lark-cli skills list` 可以查看全部可用技能，目前共有 **26 个**额外 Lark 技能，涵盖：

| 类别 | 代表技能 |
|------|---------|
| 日历 | `lark-calendar` |
| 文档 | `lark-doc` |
| 多维表格 | `lark-base` |
| 任务 | `lark-task` |
| 审批 | `lark-approval` |
| 云空间 | `lark-drive` |
| 视频会议 | `lark-meeting` |
| 通讯录 | `lark-contact` |

查看完整列表：

```bash
lark-cli skills list
```

### 安装/使用其他 Lark 技能

读取某个技能的完整文档：

```bash
lark-cli skills read lark-<name>
```

例如，读取日历技能：

```bash
lark-cli skills read lark-calendar
```

如需将某个技能安装到 Ethan 的本地 skills 目录（使其自动触发），可复制到 `~/.ethan/skills/`：

```bash
lark-cli skills read lark-calendar > ~/.ethan/skills/lark-calendar.md
```

之后当用户输入包含该技能 trigger 关键词时，Ethan 会自动加载并使用它。
