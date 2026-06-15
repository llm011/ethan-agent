# Skill 系统设计文档

## 概述

Skill 是 Ethan 的知识模块，以 Markdown 文件形式存储，当用户输入匹配到某个 Skill 的触发词时，该 Skill 的内容会被自动注入到 LLM 的 system prompt 中，引导 agent 按照特定流程处理问题。

---

## 设计参考

- **OpenClaw**: 人工编写的 Markdown skill 文件，按需加载进 context
- **Hermes**: 自我进化 — agent 完成复杂任务后自动生成新 skill

Ethan 兼顾两者：支持手写 Skill + 从经验自动生成 + 用户纠正后自动更新。

---

## 双来源加载

Skill 从两个位置加载，优先级从低到高：

| 来源 | 路径 | 说明 |
|------|------|------|
| 内置 skills | `ethan/skills/<name>/` | 随项目发布，提供开箱即用的能力 |
| 用户 skills | `~/.ethan/skills/<name>/` | 用户自定义，优先级更高，可覆盖同名内置 skill |

两种来源都支持两种存储格式：

- **目录格式**（推荐）：`<name>/SKILL.md` 主文件 + `<name>/references/` 子目录（存放参考文档）
- **单文件格式**（兼容旧版）：`<name>.md`

---

## Skill 文件格式

```markdown
---
name: weather-query
trigger: 天气|weather|气温|temperature
description: 查询天气的标准流程
fast_path: false
channels:
  - web
  - lark
version: "1.0"
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
| `trigger` | 是 | 触发关键词，`\|` 分隔；也支持 YAML list 格式 |
| `description` | 否 | 一句话描述 |
| `fast_path` | 否 | `true` 表示命中 trigger 时直接走 fast 轨（默认 false） |
| `channels` | 否 | 限定渠道白名单（如 `[lark, web]`）。空列表 = 所有渠道可用 |
| `version` | 否 | skill 版本号，用于追踪更新 |
| `metadata` | 否 | 任意 key-value 扩展字段 |

config.yaml 中可通过 `fast_skill_triggers` 手动指定额外的 fast 轨关键词（不需要对应 Skill 文件）。

---

## 匹配机制

文件：`ethan/skills/registry.py`

![Skill 匹配机制](./images/skills-matching.jpg)
<!-- diagram-source
```
用户输入 → 逐个检查每个 Skill 的 trigger 列表
         → 渠道过滤：skill.channels 非空 且 当前渠道不在其中 → 跳过
         → 如果某个 trigger 关键词出现在用户输入中（子串匹配）→ 命中
         → 最多注入 3 个 Skill 到 system prompt
```
-->

**渠道过滤**：`SkillRegistry.match(query, channel="")` 接收当前渠道标识（如 `"lark"`、`"web"` 或 `""`）。如果 Skill 的 `channels` 列表非空且当前渠道不在其中，该 Skill 不会被注入。这样可以为飞书、Web、CLI 分别准备专属 Skill，互不干扰。

---

## 注入方式

匹配到的 Skill 内容追加到 system prompt 尾部：

```
<relevant_skills>
[Skill: weather-query]
（skill 正文，超过 3000 字符时自动截断）

[Skill: another-skill]
…
</relevant_skills>
```

Agent Loop 本身不感知 Skill 的存在 — 它只看到一个更丰富的 system prompt。

---

## 内置 Skills

| Skill | 触发词 | 说明 |
|-------|--------|------|
| `lark-im` | 飞书\|lark\|feishu\|发消息\|IM\|群消息 | 飞书 IM 操作（发消息、查群、管理会话等）。加载后先执行 `lark-cli skills read lark-im` 按需拉取完整文档，避免大量文档常驻 context |
| `channels` | channel\|渠道\|频道\|通知 | 多渠道消息推送（与 `/channels` Web UI 页面联动） |
| `home-assistant` | 家居\|智能家居\|HA\|home assistant\|灯\|空调 | Home Assistant 集成，控制智能家居设备（`fast_path: true`） |

### 安装/使用其他 Lark 技能

内置 `lark-im` 是引导文件（bootstrap），完整的飞书操作通过 `lark-cli` 技能体系提供。
通过 `lark-cli skills list` 可查看 26 个额外 Lark 技能（日历、文档、多维表格、任务等）。

将某个技能安装到本地：

```bash
lark-cli skills read lark-calendar > ~/.ethan/skills/lark-calendar.md
```

---

## 命中追踪（SkillStats）

文件：`ethan/skills/stats.py`  
数据文件：`~/.ethan/skills/.stats.json`

每次 Skill 被匹配注入时，`SkillRegistry.record_hit(skill_name)` 记录一次命中，并更新 `last_hit` 时间戳。当用户对某次 Skill 驱动的回复给出纠正时，`record_correction(skill_name, correction)` 将纠正内容追加到该 Skill 的 `corrections` 列表。

数据结构：

```json
{
  "home-assistant": {
    "hit_count": 42,
    "last_hit": 1749744812.3,
    "corrections": ["设备名称应使用中文", "亮度范围是 0-255"]
  }
}
```

---

## 自动更新（Skill Updater）

文件：`ethan/skills/updater.py`

当某个 Skill 累积的 `corrections` 数量达到阈值（默认 **2 条**）时，`update_skills_from_corrections()` 自动触发更新：

```
1. 读取 Skill 当前内容
2. 调用廉价模型将纠正合并进 Skill 正文
3. 更新前先备份：<name>.md.bak
4. 写入更新后的 SKILL.md（保留原 frontmatter）
5. 清空已处理的 corrections，等待下一轮积累
```

只有存储在用户目录（`~/.ethan/skills/`）的 Skill 才会被自动更新；内置 Skill 不会被修改。

---

## 自动生成（Hermes 风格）

文件：`ethan/skills/generator.py`

触发条件：
- 当前 session 对话轮数 > 5
- 对话包含多步骤问题解决过程

流程：
1. 调用 LLM 分析对话："这是否包含一个值得提炼的可复用模式？"
2. 如果是 → 生成 Skill Markdown 文件 → 保存到 `~/.ethan/skills/`
3. 如果否 → 返回 NO_SKILL

---

## CLI 命令

```bash
ethan skill list                              # 列出所有 Skills（内置 + 用户）
ethan skill show weather-query                # 查看 Skill 内容
ethan skill create my-skill -t "k1|k2" -d "desc"  # 创建空 Skill 文件
```

---

## 数据流

![Skills 系统数据流](./images/skills-dataflow.jpg)
<!-- diagram-source
```
用户输入: "北京天气怎么样"（渠道: web）
    │
    ▼
SkillRegistry.match("北京天气怎么样", channel="web")
    │ 渠道过滤 + 触发词匹配 → 命中 "weather-query"
    ▼
SkillRegistry.build_context() → Skill 正文（超长截断到 3000 字符）
    │
    ▼
Agent._build_system() → 拼入 system prompt
    │
    ▼
LLM 收到增强后的 system prompt → 按照 Skill 描述的流程执行
    │ 调用 web_search 搜索天气
    ▼
返回结构化的天气信息
    │
    ▼
SkillRegistry.record_hit("weather-query")  ← 记录命中
```
-->
