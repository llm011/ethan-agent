---
name: excalidraw
description: >
  TRIGGER WHEN: 用户要求"画流程图"、"画架构图"、"可视化业务逻辑"、"绘制示意图"、
  "Excalidraw"、".excalidraw"、"在 Obsidian 里画图"、"思维导图"、"diagram"、
  "标准 Excalidraw"、"Excalidraw 动画"或提到需要把逻辑/架构/流程转为可视化图形时。
  在 Obsidian vault 内通过 DSL 或 JSON 生成可编辑的 Excalidraw 图（.md / .excalidraw），
  默认输出 Obsidian Excalidraw 插件可直接打开的 .md 文件。
---

# Excalidraw 绘图助手 (Obsidian 优先)

本技能将自然语言描述转化为可编辑、可论证的 Excalidraw 图形，默认面向 Obsidian Excalidraw 插件
（zsviczian/obsidian-excalidraw-plugin）工作流。综合三条来源的精华：

- **DSL 快速模式**（来自 macmini `excalidraw-flowchart`）：用简洁 DSL 一行生成流程图。
- **Obsidian 三模式输出**（来自 axtonliu/axton-obsidian-visual-skills）：Obsidian `.md` / 标准 `.excalidraw` / 动画 `.excalidraw`。
- **视觉论证哲学**（来自 coleam00/excalidraw-diagram-skill）：图形应"argue, not display"，
  形状本身承载语义，技术图必须带"证据工件"。

## 🎯 触发词与输出模式

| 触发词 | 输出模式 | 文件格式 | 默认用途 |
|--------|----------|----------|----------|
| `画流程图`、`画架构图`、`Excalidraw`、`思维导图`、`可视化`、`diagram` | **Obsidian**（默认） | `.md` | Obsidian Excalidraw 插件直接打开 |
| `标准 Excalidraw`、`standard excalidraw`、`导出到 excalidraw.com` | **Standard** | `.excalidraw` | 在 excalidraw.com 打开/分享 |
| `Excalidraw 动画`、`动画图`、`animate` | **Animated** | `.excalidraw` | 拖到 excalidraw-animate 生成动画 |

未明确指定时，**默认使用 Obsidian 模式**（因为用户主要在 Obsidian 内工作）。

## 🛡️ 核心工作流 (Workflow)

### Step 0: 评估深度（决定简单还是完整）
- **简单/概念图**：抽象形状 + 标签即可（心智模型、哲学概念）。
- **完整/技术图**：必须先查实际规格（真实事件名、API、JSON 载荷），并嵌入"证据工件"。
  - 例：画 AG-UI 协议时，应展示 `RUN_STARTED` / `STATE_DELTA` 等真实事件名，而不是 "Event 1"。

### Step 1: 逻辑分析
识别用户描述中的：核心步骤、决策点、流向、循环分支、并行/汇聚、层级。

### Step 2: 选择视觉模式（让形状=语义）
- 一对多分发 → **Fan-out**（中心向外辐射）
- 多对一汇聚 → **Convergence**（漏斗）
- 层级嵌套 → **Tree**（线 + 自由文本，不一定要框）
- 顺序流程 → **Timeline**（线 + 点 + 标签）
- 循环改进 → **Spiral/Cycle**（箭头回到起点）
- 抽象状态 → **Cloud**（重叠椭圆）
- 输入→输出转换 → **Assembly line**
- 二选一对比 → **Side-by-side**
- 阶段分隔 → **Gap/Break**（视觉留白）

**同义测试 (Isomorphism Test)**：去掉所有文字，仅靠结构能否传达概念？不能就重设计。

### Step 3: 选择生成路径
- **DSL 快速模式**：逻辑简单（≤15 节点）、用户没要求精细排版 → 走 DSL（见下文「DSL 模式」）。
- **JSON 完整模式**：技术图、复杂布局、需要证据工件、需要动画 → 手写 JSON（见下文「JSON 模式」）。

### Step 4: 生成文件并写入 vault
- 解析 Obsidian vault 路径（环境变量 `OBSIDIAN_VAULT_PATH`，缺省 `~/Documents/Obsidian Vault`）。
- 文件名格式：`[主题].[类型].md`（Obsidian 模式）或 `[主题].[类型].excalidraw`（其他）。
  - 例：`商业模式.relationship.md`、`登录流程.flowchart.excalidraw`。
- **大图分节生成**：超过 ~30 节点时，按"入口→决策→主体→输出"分节写入，避免单次 token 超限。

### Step 5: 自检与反馈
- 检查：跨节箭头双向绑定、ID 唯一、`appState` 与 `files: {}` 完整、文本无 emoji、无未转义引号。
- 反馈给用户：保存路径、在 Obsidian 中如何查看、设计选择说明、是否需要调整。

## 📦 Obsidian 集成（重点）

### 1. Vault 路径解析
```
优先级: OBSIDIAN_VAULT_PATH 环境变量 → ~/Documents/Obsidian Vault
推荐存放子目录: vault 根下的 "Excalidraw/" 或 "Attachments/Excalidraw/"
```
文件工具不会展开 shell 变量，**必须先解析为绝对路径再写入**，路径含空格时尤其注意。

### 2. Obsidian 模式 `.md` 文件结构（严格按此模板，不得修改）

```markdown
---
excalidraw-plugin: parsed
tags: [excalidraw]
---
==⚠  Switch to EXCALIDRAW VIEW in the MORE OPTIONS menu of this document. ⚠== You can decompress Drawing data with the command palette: 'Decompress current Excalidraw file'. For more info check in plugin settings under 'Saving'

# Excalidraw Data

## Text Elements
%%
## Drawing
\`\`\`json
{完整 JSON 数据}
\`\`\`
%%
```

关键约束：
- Frontmatter **必须**包含 `excalidraw-plugin: parsed` 与 `tags: [excalidraw]`，不能改成其他值。
- 警告信息行必须完整保留。
- JSON 必须被 `%%` 标记包围（Obsidian 注释，插件会读取其中的 Drawing 数据）。
- `## Text Elements` 段留空，插件会自动从 JSON 填充。
- JSON `source` 字段使用 `https://github.com/zsviczian/obsidian-excalidraw-plugin`。

### 3. 在笔记中引用 Excalidraw 图
- 嵌入预览：`![[文件名.md]]` 或 `![[文件名]]`（Obsidian 会渲染为图形预览）。
- 链接跳转：`[[文件名]]`（点击进入 Excalidraw 视图编辑）。
- 建议把 `.md` 图文件放在固定子目录，配合 Obsidian 的"已附加文件默认位置"设置避免散落。

### 4. PNG / SVG 导出
- 在 Obsidian 中打开 `.md` 图文件 → 右上角 MORE OPTIONS → Export → PNG/SVG。
- 或在 Excalidraw 视图内 `Ctrl/Cmd + Shift + E` 调出导出菜单。
- 批量导出可调用 Obsidian Excalidraw 插件命令面板：`Excalidraw: Export active file as PNG`。
- **不在本技能内自动跑 Playwright 渲染**（coleam00 原方案依赖 Python+playwright，本技能保持纯文档型，
  如需自动渲染可后续单独引入 `references/render_excalidraw.py`）。

### 5. Standard / Animated 模式（非默认）
- **Standard `.excalidraw`**：纯 JSON，`source: "https://excalidraw.com"`，无 Markdown 包装。拖到 excalidraw.com 即可。
- **Animated `.excalidraw`**：每个元素加 `customData.animate: {order, duration}`，
  `order` 越小越先出现（建议顺序：标题 → 主框架 → 连接线 → 细节文字）。
  拖到 https://dai-shi.github.io/excalidraw-animate/ 预览并导出 SVG/WebM。

## 🚀 DSL 模式（快速流程图）

适合 ≤15 节点的简单流程图。通过 `npx @swiftlysingh/excalidraw-cli` 把 DSL 转成 `.excalidraw`，
再用 `cp` 放进 vault（或直接 `-o` 指定 vault 路径）。

```bash
# 内联 DSL（注意引号转义，多行建议用 heredoc）
npx @swiftlysingh/excalidraw-cli create --inline "(Start) -> [Step 1] -> {OK?} -> \"yes\" -> (End)" \
  -o "$OBSIDIAN_VAULT_PATH/Excalidraw/quick-flow.excalidraw"
```

完整 DSL 语法见 [references/dsl-syntax.md](references/dsl-syntax.md)。

> ⚠️ DSL 模式生成的是标准 `.excalidraw`（非 Obsidian `.md`）。若要 Obsidian 直接打开，
> 优先用下文 JSON 模式生成 `.md`；DSL 模式适合快速起草后导入 excalidraw.com 微调。

## 🧱 JSON 模式（完整可控）

### 顶层结构
```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "https://github.com/zsviczian/obsidian-excalidraw-plugin",
  "elements": [...],
  "appState": { "gridSize": null, "viewBackgroundColor": "#ffffff" },
  "files": {}
}
```
> Standard/Animated 模式下 `source` 改为 `https://excalidraw.com`。

### 元素通用必填字段
```json
{
  "id": "unique-id",
  "type": "rectangle|ellipse|diamond|text|arrow|line",
  "x": 100, "y": 100, "width": 200, "height": 50,
  "angle": 0,
  "strokeColor": "#1e1e1e",
  "backgroundColor": "transparent",
  "fillStyle": "solid",
  "strokeWidth": 2,
  "strokeStyle": "solid|dashed",
  "roughness": 1,
  "opacity": 100,
  "groupIds": [],
  "frameId": null,
  "index": "a1",
  "roundness": { "type": 3 },
  "seed": 123456789,
  "version": 1,
  "versionNonce": 987654321,
  "isDeleted": false,
  "boundElements": [],
  "updated": 1751928342106,
  "link": null,
  "locked": false
}
```

### 文本元素额外字段
```json
{
  "text": "显示文本",
  "rawText": "显示文本",
  "fontSize": 20,
  "fontFamily": 5,
  "textAlign": "center",
  "verticalAlign": "middle",
  "containerId": null,
  "originalText": "显示文本",
  "autoResize": true,
  "lineHeight": 1.25
}
```

### 动画元素额外字段（仅 Animated 模式）
```json
{
  "customData": { "animate": { "order": 1, "duration": 500 } }
}
```

## 🎨 设计规范

### 文本
- **fontFamily**: 统一用 `5`（Excalifont 手写字体）。
- **字号**：标题 24-28px / 副标题 18-20px / 正文 14-16px。
- **行高**：统一 `1.25`。
- **转义**：文本内 `"` → `『』`；`()` → `「」`（避免与 JSON / DSL 语法冲突）。
- **禁止 Emoji**：用形状/颜色区分，不用 emoji。

### 配色（默认，可在 references/color-palette.md 自定义品牌色）
- 标题：`#1e40af`（深蓝）
- 副标题/连接线：`#3b82f6`（亮蓝）
- 正文：`#374151`（灰）
- 强调：`#f59e0b`（金）
- 证据工件背景：深色矩形 + 高亮文字

### 布局
- 画布范围：0-1200 × 0-800（更大图按 1200×800 网格延展）。
- 坐标原点在左上角。
- ID 命名建议用语义字符串（`trigger_rect`、`arrow_fan_left`），便于跨节引用。
- 大图按 section 命名 seed 段（section1 用 100xxx，section2 用 200xxx）避免碰撞。

### 容器 vs 自由文本
- 默认用**自由文本**（typography 自带层级，28px 标题不需要框）。
- 仅当满足以下条件时才加容器：是 section 焦点 / 需要箭头连接 / 形状本身有语义（决策菱形等）。
- **容器测试**：每个带框元素问一句"去掉框是否仍成立？" 是 → 去掉。

## 🧭 与 Mermaid / Obsidian Bases 的取舍

| 工具 | 适合场景 | 不适合场景 |
|------|----------|-----------|
| **Excalidraw** | 手绘风、自由布局、需要精细拖拽调整、需要嵌入真实代码/JSON 证据、需要在 Obsidian 内双向链接与嵌入预览 | 高度结构化、需要严格自动重排、需要版本化 diff |
| **Mermaid** | 文本驱动、Git 友好 diff、序列图/甘特图/类图等标准 UML、追求"代码即图" | 自由布局、复杂嵌套、需要证据工件、需要美观手绘风 |
| **Obsidian Bases** | 结构化数据视图（表格/卡片/看板）、过滤/分组/公式、类似 Notion 数据库 | 表达流程、关系、空间布局 |

决策建议：
- **流程/架构/关系图 → Excalidraw**（默认，本技能范围）。
- **标准 UML / 序列 / 甘特 / 类图 → Mermaid**（文本即图，diff 友好）。
- **结构化数据管理 → Obsidian Bases**（不是图，是数据视图）。
- **不确定时**：先问用户"是要表达流程/关系（Excalidraw），还是要版本化文本图（Mermaid），还是要数据视图（Bases）？"

## ⚠️ 避坑指南 (Gotchas)

- **环境依赖**：DSL 模式用 `npx` 运行 CLI 以避免版本冲突；JSON 模式零依赖。
- **Shell 转义**：多行 DSL 用 `cat <<'EOF'` 包裹；JSON 写文件用 Write 工具而非 `echo`。
- **命名规范**：决策节点以 `?` 结尾（`{成功?}`），起止用 `(Start)` / `(End)`。
- **vault 路径**：含空格时必须用引号；先解析 `$OBSIDIAN_VAULT_PATH` 再传给文件工具。
- **大图分节**：单次响应 token 上限 ~32k，>30 节点必须分节生成，每节独立可读。
- **跨节箭头**：新增 section 的箭头连接旧元素时，必须同时更新旧元素的 `boundElements` 数组。
- **Obsidian 模式 frontmatter**：`excalidraw-plugin: parsed` 与 `tags: [excalidraw]` 缺一不可，
  否则插件不识别。
- **JSON `source` 字段**：Obsidian 模式必须用 `zsviczian/obsidian-excalidraw-plugin`，
  Standard/Animated 用 `excalidraw.com`，混用会导致打开异常。

## 📚 渐进式参考 (References)

- **DSL 语法完整表**：`references/dsl-syntax.md`（节点 / 连线 / 布局指令 / 完整示例）。
- **品牌配色自定义**：（可选）后续可加 `references/color-palette.md` 集中管理颜色。
- **Excalidraw JSON Schema**：https://github.com/excalidraw/excalidraw/blob/master/packages/excalidraw/schema.ts
- **Obsidian Excalidraw 插件**：https://github.com/zsviczian/obsidian-excalidraw-plugin
- **DSL CLI**：`npx @swiftlysingh/excalidraw-cli --help`
