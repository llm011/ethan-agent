# 视觉预设

使用 Remotion/CSS/SVG 生成的可复现视觉，不依赖外部图片。共 11 种视觉类型。

## 类型速查

| `visual.type` | 数据字段 | 适用场景 |
|---|---|---|
| `kinetic-text` | `keywords: string[]`（≤5） | 开场、核心概念、强节奏关键词 |
| `steps` | `items: string[]`（≤5） | 流程、清单、阶段 |
| `stat` | `value: string`, `label: string` | 关键数字或短结论 |
| `quote` | `quote: string`, `attribution?: string` | 短引用或作者观点 |
| `summary` | `items: string[]`（≤5） | 结尾回顾 |
| `icon-card` | `icon: string`, `title: string`, `subtitle?: string` | 带语义图标的概念/知识点 |
| `comparison` | `left/right: {label, items[], tone}` | A vs B 对比（利弊、优劣） |
| `timeline` | `items: {label, description?, tone?}[]`（≤6） | 事件链、流程步骤、时间线 |
| `callout` | `text: string`, `tone?: string`, `icon?: string` | 高亮关键观点、结论 |
| `question` | `question: string`, `hint?: string` | 提问式引导、互动开场 |
| `definition` | `term: string`, `definition: string`, `example?: string` | 术语定义、概念解释 |

## tone 颜色映射

`comparison`、`timeline`、`callout` 中的 `tone` 字段决定颜色：

| tone | 颜色 | 含义 |
|---|---|---|
| `"positive"` | `theme.positive`（绿） | 好的、优势、方案 |
| `"negative"` | `theme.negative`（红） | 问题、痛点、劣势 |
| `"accent"` | `theme.accent`（橙黄） | 高亮、重点（仅 `callout`） |
| `"neutral"` / 省略 | `theme.primary`（主色） | 中性描述 |

## 图标列表（icon 字段可选值）

`icon-card` 和 `callout` 的 `icon` 字段支持以下预定义图标名（SVG 渲染，自动着色）：

`lightning` `lock` `chart-up` `check` `star` `arrow` `question` `bulb` `fire` `shield` `target` `clock` `heart` `rocket` `brain` `book` `sparkle`

未识别的名称会以 emoji 文本形式渲染（Chromium 原生彩色），可直接使用 emoji 字符如 `🔥` `💡` `🎯`。

## 选择规则

1. **相邻场景避免使用相同预设**（交替使用不同类型保持视觉节奏）。
2. **没有可靠数字时不要使用 `stat`**（不要编造数据）。
3. **`quote` 必须短于 80 个汉字**，并保留来源归属。
4. **视觉字段缺失时脚本会回退到 `kinetic-text`**，但应在写 manifest 时主动补齐。
5. **`comparison` 的左右两侧 tone 应形成对比**（如 positive vs negative），不要两侧同色。
6. **`question` 适合开场或转折**，不要连续使用两个 question 场景。
7. **`definition` 适合解释专业术语**，每个术语单独一个场景。

## Per-mode 视觉偏好

不同 `mode` 下的视觉类型使用偏好：

### general（通用）
无特殊偏好，按内容自然选择。

### news（行业新闻）
- 偏好：`kinetic-text`（关键词）→ `stat`（数据）→ `timeline`（因果链）→ `comparison`（利弊）→ `quote`（观点）→ `callout`（结论）
- 数字精确，信息密度高

### paper（论文讲解）
- 偏好：`question`（引入）→ `callout`（痛点）→ `icon-card`（方法）→ `timeline`（流程）→ `stat`+`comparison`（结果）→ `callout`（结论）
- 可用英文术语，每页一个概念

### kids（儿童教育）
- 偏好：`question`（引导）→ `icon-card`（知识点）→ `question`（互动）→ `definition`（解释）→ `steps`（分步）→ `callout`（鼓励）
- 节奏慢，每页只说一件事，用拟人化/比喻
- 旁白每场景不超过 80 汉字
