---
name: skill-creator
description: "创建和管理 Ethan Agent 技能：起草 SKILL.md、设计触发词、组织 references/scripts 目录结构。当用户要求「创建技能」「写个 skill」「沉淀成技能」「做成技能」「新建能力」时触发。"
trigger: "创建技能|写个 skill|新建技能|做成技能|沉淀成技能|新建能力|create skill|new skill|写技能|加个技能|skill 模板|技能模板|skill template"
---

# skill-creator

帮助用户创建新的 Ethan 技能。技能是 Ethan 的可扩展能力单元，通过 `SKILL.md` 定义触发条件和执行指令。

## 技能目录结构

```
~/.ethan/skills/<skill-name>/
├── SKILL.md              # 必需：技能定义文件
├── references/           # 可选：大段参考文档、API 规范等
│   └── api-details.md
└── scripts/              # 可选：辅助脚本（Python/Shell/Node）
    └── helper.py
```

- 用户技能放在 `~/.ethan/skills/` 下（自动加载，无需重启）
- 内置技能在代码仓库 `ethan/defaults/skills/` 下

## SKILL.md 格式

```markdown
---
name: my-skill-name
description: "一句话说明技能做什么 + 什么时候应该被触发。这是语义匹配的主要依据。"
trigger: "关键词1|关键词2|英文词|中文短语"
version: 0.1.0
fast_path: false
---

# 技能标题

正文：告诉 Ethan 拿到这个技能后该如何执行任务。
```

### frontmatter 字段说明

| 字段 | 必需 | 说明 |
|------|------|------|
| `name` | ✅ | 技能 ID，与目录名一致，kebab-case |
| `description` | ✅ | **最重要的字段**——语义匹配的主要依据 |
| `trigger` | 推荐 | 管道分隔的关键词/短语，用于快速精确匹配 |
| `version` | 可选 | 语义化版本号 |
| `fast_path` | 可选 | `true` 表示高优先级匹配，适用于通用策略类技能 |

## 写好 description 的要点

description 决定技能能否被正确匹配，必须同时包含：

1. **做什么**：技能的核心能力（如「查询航班」「生成周报」）
2. **何时用**：典型使用场景或用户表述（如「当用户问机票价格时」）

好的例子：
```yaml
description: "通过 API 查询实时航班信息和票价。当用户问「查机票」「航班价格」「飞北京多少钱」时使用。"
```

差的例子：
```yaml
description: "航班查询工具"  # 太短，缺少场景描述
```

## 写好 trigger 的要点

trigger 用于关键词快速匹配（优先于语义搜索）：

- 包含中英文常见表述
- 用 `|` 分隔
- 包含缩写、口语化表达
- 不超过 15-20 个词组

```yaml
trigger: "查机票|航班查询|flight|机票价格|飞哪里|订机票|航班|票价"
```

## 正文编写原则

SKILL.md 正文是 Ethan 执行任务时的**指令手册**：

1. **明确步骤**：告诉 Ethan 收到请求后应该做什么（调用什么工具、按什么顺序）
2. **给出示例**：关键操作给出 code block 示例（命令、API 调用格式等）
3. **标注约束**：哪些事不能做、常见陷阱、超时处理
4. **保持精简**：SKILL.md 正文控制在 **500 行以内**；超出的放 `references/`

## 何时用 references/ 目录

当以下内容太长（>100 行）不适合内联在 SKILL.md 时，拆到 `references/`：

- API 接口文档、请求/响应示例
- 详细的工作流说明
- 大段的 prompt 模板
- 配置参考、参数表

在 SKILL.md 中用简短描述 + 指引引用：
```markdown
详细 API 参数见 `references/api-details.md`。
```

Ethan 会按需用 `skill_read` 工具加载 references 文件。

## 何时用 scripts/ 目录

当技能需要执行复杂逻辑、数据处理或 API 调用时：

- Python/Node/Shell 脚本
- 适合：多步 API 编排、数据转换、文件处理
- 脚本通过 `shell` 工具执行

在 SKILL.md 中说明调用方式：
```markdown
执行分析脚本：
\`\`\`bash
python3 ~/.ethan/skills/my-skill/scripts/analyze.py --input "$FILE"
\`\`\`
```

## 创建技能的完整流程

### 1. 确定技能边界

问用户：
- 这个技能要解决什么问题？
- 典型的触发场景是什么？
- 需要调用哪些工具或外部服务？

### 2. 创建目录和文件

```python
# 用 file_write 创建 SKILL.md
# 路径：~/.ethan/skills/<skill-name>/SKILL.md
```

技能名规则：
- kebab-case（如 `flight-query`、`weekly-report`）
- 简短有意义
- 避免与已有技能重名（先用 `skill_list` 检查）

### 3. 编写 SKILL.md

按上述格式填写 frontmatter + 正文。正文重点写：
- Ethan 收到请求后的执行步骤
- 用到的工具和命令
- 输出格式要求

### 4. 验证技能已加载

```
调用 skill_list 确认新技能出现在列表中
```

### 5. 测试匹配

用一个真实的用户查询测试，看技能是否被正确匹配到。如果匹配不上：
- 检查 description 是否覆盖了该查询的语义
- 检查 trigger 是否包含关键词
- 调整后重新保存即可（无需重启）

## 模板：最小可用技能

```markdown
---
name: example-skill
description: "简短说明做什么。当用户说「某某」「某某」时触发。"
trigger: "关键词1|关键词2|关键词3"
---

# 技能标题

## 使用场景

描述何时触发此技能。

## 执行步骤

1. 第一步做什么
2. 第二步做什么
3. 输出什么格式的结果

## 注意事项

- 约束条件
- 常见陷阱
```

## 注意事项

- 一个技能只做一件事，保持职责单一
- 用户技能同名会覆盖内置技能（可用于定制）
- 避免在 SKILL.md 中硬编码用户个人信息（如 token），用环境变量或让用户运行时提供
- 技能之间可以互相引用，但不要形成循环依赖
