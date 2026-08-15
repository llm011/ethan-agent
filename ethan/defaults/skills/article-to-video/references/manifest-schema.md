# Manifest 协议

`manifest.json` 是模型与确定性媒体流水线之间的唯一契约。必须写合法 UTF-8 JSON，不要写 Markdown 围栏或注释。

## 顶层字段

| 字段 | 必需 | 说明 |
|---|---:|---|
| `title` | 是 | 视频标题，1–100 字符 |
| `summary` | 否 | 一句话摘要，供封面和包装使用 |
| `mode` | 否 | 内容模式：`general`（默认）、`news`、`paper`、`kids` |
| `width` / `height` | 否 | 默认 `1080` / `1920`；横屏用 `1920` / `1080` |
| `fps` | 否 | 24、25、30 或 60，默认 30 |
| `targetDurationSec` | 否 | 用户指定的目标秒数；填写后会用实际 TTS 时长强校验 |
| `durationToleranceSec` | 否 | 允许误差，默认目标时长的 10%，最少 2 秒 |
| `language` | 否 | 默认 `zh-CN` |
| `sourceUrl` | 否 | URL 输入的原始链接 |
| `voice` | 否 | Edge TTS 参数 |
| `theme` | 否 | 颜色主题（覆盖 mode 默认配色） |
| `scenes` | 是 | 1–50 个场景 |

`mode` 根据内容类型选择默认配色和节奏指导。省略时默认 `"general"`。

`voice`：

```json
{
  "name": "zh-CN-XiaoxiaoNeural",
  "rate": "+5%",
  "volume": "+0%",
  "pitch": "+0Hz"
}
```

## theme 颜色主题

theme 支持 10 个六位十六进制颜色字段。用户只需填入要覆盖的字段，其余使用 mode 默认值：

| 字段 | 说明 | general 默认值 |
|---|---|---|
| `background` | 主背景色 | `#081120` |
| `backgroundEnd` | 渐变终点色 | `#1a0a2e` |
| `surface` | 卡片/面板背景 | `#111D32` |
| `primary` | 标题/关键词主色 | `#6EE7F9` |
| `secondary` | 次要强调色 | `#A78BFA` |
| `accent` | 高亮/强调色 | `#F59E0B` |
| `positive` | 好的/方案/优势 | `#10B981` |
| `negative` | 问题/痛点/劣势 | `#EF4444` |
| `text` | 正文颜色 | `#F8FAFC` |
| `textMuted` | 次要文字颜色 | `#94A3B8` |

不同 `mode` 有不同的默认配色：`news`（冷峻蓝灰）、`paper`（深邃蓝紫）、`kids`（温暖明亮高饱和）。

## 场景字段

| 字段 | 必需 | 说明 |
|---|---:|---|
| `id` | 是 | 唯一 kebab-case ID，后续修改时保持稳定 |
| `narration` | 是 | 实际送入 TTS 的旁白，20–180 个汉字为宜 |
| `headline` | 是 | 屏幕主标题，建议不超过 24 个汉字 |
| `body` | 否 | 屏幕补充文本，建议不超过 60 个汉字 |
| `visual` | 是 | 视觉预设及其数据（11 种类型） |
| `theme` | 否 | 场景级颜色覆盖（partial theme，只填需覆盖的字段） |

## visual 类型详细定义

### kinetic-text — 关键词展示

```json
{ "type": "kinetic-text", "keywords": ["关键词1", "关键词2", "关键词3"] }
```

最多 5 个关键词，每个 ≤80 字符。每词独立卡片，交替使用 primary/secondary/accent 色。

### steps — 流程步骤

```json
{ "type": "steps", "items": ["步骤一", "步骤二", "步骤三"] }
```

最多 5 项。带编号圆点（primary→secondary 渐变）+ 左侧连接线。

### stat — 数字展示

```json
{ "type": "stat", "value": "92.7%", "label": "MMLU 基准测试得分" }
```

`value` ≤24 字符，`label` ≤80 字符。数字从 0 动态增长到目标值。

### quote — 引用

```json
{ "type": "quote", "quote": "引用文字", "attribution": "来源" }
```

引用 ≤160 字符，归属 ≤80 字符。左侧 accent 色竖条装饰。

### summary — 结尾回顾

```json
{ "type": "summary", "items": ["要点一", "要点二", "要点三"] }
```

最多 5 项。每项带 accent 色圆点标记。

### icon-card — 图标概念卡

```json
{ "type": "icon-card", "icon": "brain", "title": "自注意力机制", "subtitle": "每个词直接看全局" }
```

`icon` 为图标名（见 visual-presets.md 图标列表）或 emoji。`title` ≤80 字符，`subtitle` ≤120 字符。

### comparison — A vs B 对比

```json
{
  "type": "comparison",
  "left": { "label": "优势", "items": ["点A", "点B"], "tone": "positive" },
  "right": { "label": "劣势", "items": ["点C", "点D"], "tone": "negative" }
}
```

每侧 label ≤30 字符，items 每项 ≤80 字符（≤5 项），tone 为 `positive`/`negative`/`neutral`。

### timeline — 事件/流程时间线

```json
{
  "type": "timeline",
  "items": [
    { "label": "第一步", "description": "详细说明", "tone": "positive" },
    { "label": "第二步", "description": "", "tone": "neutral" }
  ]
}
```

最多 6 项。每项 label ≤80 字符，description ≤120 字符，tone 为 `positive`/`negative`/`neutral`。

### callout — 高亮观点

```json
{ "type": "callout", "text": "核心结论", "tone": "accent", "icon": "lightning" }
```

text ≤160 字符，tone 为 `positive`/`negative`/`neutral`/`accent`，icon 可选（≤32 字符）。

### question — 提问引导

```json
{ "type": "question", "question": "天空为什么是蓝色的？", "hint": "和阳光有关系哦~" }
```

question ≤120 字符，hint ≤120 字符。超大问号背景 + 问题文字 + 提示。

### definition — 术语定义

```json
{ "type": "definition", "term": "光的散射", "definition": "光遇到小颗粒时会向四面八方弹开", "example": "蓝光弹得最多" }
```

term ≤60 字符，definition ≤200 字符，example ≤160 字符。

## 完整示例 — 论文讲解模式

```json
{
  "title": "Transformer 注意力机制详解",
  "mode": "paper",
  "targetDurationSec": 75,
  "scenes": [
    {
      "id": "opening-question",
      "narration": "你知道 ChatGPT 背后的 Transformer 是怎么理解每个词的含义的吗？",
      "headline": "注意力的力量",
      "visual": { "type": "question", "question": "Transformer 如何理解语言？", "hint": "秘密藏在注意力机制里" }
    },
    {
      "id": "problem",
      "narration": "传统的 RNN 模型在处理长文本时，会逐渐遗忘前面的信息。序列越长，理解越差。",
      "headline": "RNN 的困境",
      "visual": { "type": "callout", "text": "序列越长，理解越差", "tone": "negative" }
    },
    {
      "id": "method",
      "narration": "Transformer 的核心创新是自注意力机制：让每个词都能直接关注序列中的所有其他词。",
      "headline": "自注意力机制",
      "visual": { "type": "icon-card", "icon": "brain", "title": "Self-Attention", "subtitle": "每个词直接看全局" }
    },
    {
      "id": "result",
      "narration": "在机器翻译任务上，Transformer 比 RNN 提升了 2 个 BLEU 分数，训练速度还快了 4 倍。",
      "headline": "实验结果",
      "visual": {
        "type": "comparison",
        "left": { "label": "Transformer", "items": ["BLEU +2.0", "训练快 4x"], "tone": "positive" },
        "right": { "label": "RNN", "items": ["BLEU 基线", "训练慢"], "tone": "negative" }
      }
    },
    {
      "id": "conclusion",
      "narration": "注意力机制让模型不再受序列长度限制，成为现代大语言模型的基石。",
      "headline": "奠基之作",
      "visual": { "type": "callout", "text": "注意力机制 = 现代 AI 的基石", "tone": "positive", "icon": "star" }
    }
  ]
}
```

## 完整示例 — 行业新闻模式

```json
{
  "title": "OpenAI 发布 GPT-5",
  "mode": "news",
  "targetDurationSec": 60,
  "scenes": [
    {
      "id": "event-overview",
      "narration": "OpenAI 正式发布 GPT-5，号称在推理能力上实现了质的飞跃。",
      "headline": "GPT-5 来了",
      "visual": { "type": "kinetic-text", "keywords": ["推理飞跃", "多模态原生", "Agent 能力"] }
    },
    {
      "id": "key-metric",
      "narration": "在 MMLU 基准测试中，GPT-5 拿到了 92.7 的分数，比 GPT-4 提升了 11 个百分点。",
      "headline": "核心指标",
      "visual": { "type": "stat", "value": "92.7%", "label": "MMLU 基准测试得分" }
    },
    {
      "id": "impact",
      "narration": "对行业来说，这意味着更强的 AI Agent 能力，但也带来更大的安全挑战。",
      "headline": "影响几何",
      "visual": {
        "type": "comparison",
        "left": { "label": "机遇", "items": ["Agent 自主性提升", "复杂任务自动拆解"], "tone": "positive" },
        "right": { "label": "挑战", "items": ["对齐风险增加", "监管压力加大"], "tone": "negative" }
      }
    }
  ]
}
```

## 完整示例 — 儿童教育模式

```json
{
  "title": "为什么天空是蓝色的？",
  "mode": "kids",
  "targetDurationSec": 70,
  "scenes": [
    {
      "id": "opening",
      "narration": "小朋友们，你们有没有抬头看过天空？天空为什么是蓝色的呢？",
      "headline": "天空的秘密",
      "visual": { "type": "question", "question": "天空为什么是蓝色的？", "hint": "和阳光有关系哦~" }
    },
    {
      "id": "fact",
      "narration": "太阳光其实是由红橙黄绿蓝靛紫七种颜色组成的！",
      "headline": "阳光的七色衣",
      "visual": { "type": "icon-card", "icon": "sparkle", "title": "太阳光 = 七种颜色", "subtitle": "赤橙黄绿青蓝紫" }
    },
    {
      "id": "explanation",
      "narration": "蓝光波长最短，散射得最厉害，所以整个天空都被蓝光染蓝了！",
      "headline": "蓝光散射",
      "visual": { "type": "definition", "term": "光的散射", "definition": "光遇到小颗粒时会向四面八方弹开", "example": "蓝光弹得最多，所以天空是蓝色" }
    },
    {
      "id": "encourage",
      "narration": "你已经知道天空的秘密了！记得告诉爸爸妈妈哦！",
      "headline": "你真棒！",
      "visual": { "type": "callout", "text": "你已经知道了天空的秘密！", "tone": "positive", "icon": "star" }
    }
  ]
}
```

## 校验规则

- 禁止重复 `id`、空旁白、未知视觉类型和非法颜色。
- 用户明确要求视频时长时必须填写 `targetDurationSec`；TTS 后超出容差则先改旁白，不带病渲染。
- `rate`、`volume` 必须是带符号百分比；`pitch` 必须是带符号 Hz。
- 不把 Markdown、HTML 或 URL 原文整段塞进屏幕文字。
- 引用原文时在 `visual.type=quote` 中使用短摘录，并在 `sourceUrl` 保留来源。
- `mode` 必须是 `general`/`news`/`paper`/`kids` 之一。
- `comparison` 两侧必须是对象且各有 label、items。
- `timeline` items 每项必须有 label，tone 只接受 `positive`/`negative`/`neutral`。
- `callout` tone 只接受 `positive`/`negative`/`neutral`/`accent`。
