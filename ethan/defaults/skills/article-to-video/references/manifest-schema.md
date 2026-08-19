# Manifest 协议

`manifest.json` 是模型与确定性媒体流水线之间的唯一契约。必须写合法 UTF-8 JSON，不要写 Markdown 围栏或注释。

## 顶层字段

| 字段 | 必需 | 说明 |
|---|---:|---|
| `title` | 是 | 视频标题，1–100 字符 |
| `summary` | 否 | 一句话摘要，供封面和包装使用 |
| `width` / `height` | 否 | 默认 `1080` / `1920`；横屏用 `1920` / `1080` |
| `fps` | 否 | 24、25、30 或 60，默认 30 |
| `targetDurationSec` | 否 | 用户指定的目标秒数；填写后会用实际 TTS 时长强校验 |
| `durationToleranceSec` | 否 | 允许误差，默认目标时长的 10%，最少 2 秒 |
| `language` | 否 | 默认 `zh-CN` |
| `sourceUrl` | 否 | URL 输入的原始链接 |
| `voice` | 否 | Edge TTS 参数；配了 `presenter` 且省略时继承角色包音色 |
| `theme` | 否 | 颜色主题 |
| `domain` | 否 | `general`（默认）/ `finance` / `paper`，决定主题底色与可用视觉 |
| `presenter` | 否 | 虚拟人立绘配置（引用资产库角色包） |
| `scenes` | 是 | 1–50 个场景 |

`voice`：

```json
{
  "name": "zh-CN-XiaoxiaoNeural",
  "rate": "+5%",
  "volume": "+0%",
  "pitch": "+0Hz"
}
```

`theme` 支持 `background`、`surface`、`primary`、`secondary`、`text` 以及可选的 `accent`（强调色，callout 默认底色）、`positive` / `negative`（金融域约定红涨绿跌）六位十六进制颜色，未知字段会校验失败。只需填入要覆盖的字段。合并优先级：内置默认 ← `domain` 主题 ← 用户 `theme`。

`domain` 主题：`finance` = 深蓝底 + 金色主色（`positive` 红 / `negative` 绿，A 股约定）；`paper` = 紫色系；`general` = 内置默认。

`presenter`（虚拟人立绘，引用 `~/.ethan/assets/library/presenters/<id>/`，制作流程见 `presenter-guide.md`）：

```json
{
  "id": "xiaoyu",
  "position": "right",
  "scale": 1.0,
  "defaultPose": "standing"
}
```

- `id`：kebab-case，必须已在资产库中且 `status == "ready"`，否则 validate 报错并给出 `presenter_gen.py` 修复命令
- `position`：`right`（默认）/ `left`
- `scale`：0.6–1.4，默认 1.0
- `defaultPose`：必须是角色包里已有的姿势名（默认 `standing`）

## 场景字段

| 字段 | 必需 | 说明 |
|---|---:|---|
| `id` | 是 | 唯一 kebab-case ID，后续修改时保持稳定 |
| `narration` | 是 | 实际送入 TTS 的旁白，20–180 个汉字为宜 |
| `headline` | 是 | 屏幕主标题，建议不超过 24 个汉字 |
| `body` | 否 | 屏幕补充文本，建议不超过 60 个汉字 |
| `visual` | 是 | 视觉预设及其数据（6 种类型，见下） |
| `callouts` | 否 | 1–3 条黄色关键词标注（晓玉说同款），每条 `{"text": "≤12字", "tone": "accent\|positive\|negative"}` |
| `presenter` | 否 | 场景级立绘控制：`{"pose": "pointing"}` 切姿势，`{"visible": false}` 隐藏；要求顶层已配 `presenter` |

## visual 类型详细定义

### kinetic-text — 关键词展示

```json
{ "type": "kinetic-text", "keywords": ["关键词1", "关键词2", "关键词3"] }
```

最多 5 个关键词，每个 ≤80 字符。每词独立卡片，首词高亮。

### steps — 流程步骤

```json
{ "type": "steps", "items": ["步骤一", "步骤二", "步骤三"] }
```

最多 5 项，带编号展示。

### stat — 数字展示

```json
{ "type": "stat", "value": "92.7%", "label": "MMLU 基准测试得分" }
```

`value` ≤24 字符，`label` ≤80 字符。字号随 value 长度自适应（越短字号越大）。

### quote — 引用

```json
{ "type": "quote", "quote": "引用文字", "attribution": "来源" }
```

引用 ≤160 字符，归属 ≤80 字符，归属可省略。

### summary — 结尾回顾

```json
{ "type": "summary", "items": ["要点一", "要点二", "要点三"] }
```

最多 5 项，带编号展示。

### candlestick — K线图（金融域）

```json
{
  "type": "candlestick",
  "closes": [3120.5, 3128.0, 3115.2, 3140.8, 3152.3, 3144.0, 3161.5, 3158.9],
  "bands": {"upper": [...], "middle": [...], "lower": [...]},
  "markers": [{"index": 5, "label": "假突破", "tone": "accent", "position": "above"}]
}
```

- `closes`（收盘价序列，8–120 个数）与 `candles`（显式 OHLC，2–60 根，`{"o","h","l","c"}` 且 `h >= max(o,c)`、`l <= min(o,c)`）**二选一**；只给 `closes` 时上下影线由确定性伪随机合成（同 manifest 重渲染画面一致）
- `bands` 可选（如布林带），每条与序列等长；`upper`/`lower` 虚线用 accent 色，`middle` 用 secondary 色
- `markers` 可选，≤4 个：`index` 必须落在 `[0, 序列长度)`，`label` ≤12 字，`tone` 同 callouts，`position` 为 `above` / `below`
- 动画：左到右揭示（场景前 40% 帧），marker 在其蜡烛揭示后弹簧弹出；蜡烛红涨绿跌取 theme 的 `positive`/`negative`

## 轻量公式渲染

`kinetic-text` 的关键词与场景 `body` 支持轻量 LaTeX 子集，用于科普/论文类内容的公式展示：

- 上标 `^{...}` 或 `^X`；下标 `_{...}` 或 `_X`
- 命令：`\sqrt{...}`、`\times`、`\cdot`、`\text{...}`、`\frac`（渲染为 `/`）
- 希腊字母与常用符号：`\alpha`、`\beta`、`\sigma`、`\pi`、`\infty`、`\sum`、`\leq`、`\geq`、`\approx`、`\pm`、`\rightarrow` 等
- 不支持的命令原样显示

注意在 JSON 中反斜杠需转义（写成 `\\times`）。

## 完整示例

```json
{
  "title": "Transformer 注意力机制详解",
  "summary": "每个词直接看全局：注意力如何解决长序列遗忘。",
  "width": 1080,
  "height": 1920,
  "fps": 30,
  "targetDurationSec": 75,
  "language": "zh-CN",
  "sourceUrl": "https://example.com/attention",
  "voice": {
    "name": "zh-CN-XiaoxiaoNeural",
    "rate": "+5%",
    "volume": "+0%",
    "pitch": "+0Hz"
  },
  "theme": {
    "background": "#081120",
    "surface": "#111D32",
    "primary": "#6EE7F9",
    "secondary": "#A78BFA",
    "text": "#F8FAFC"
  },
  "scenes": [
    {
      "id": "opening-question",
      "narration": "你知道 ChatGPT 背后的 Transformer 是怎么理解每个词的含义的吗？",
      "headline": "注意力的力量",
      "body": "序列越长，RNN 遗忘越严重：P(x_t | x_{t-n})。",
      "visual": { "type": "kinetic-text", "keywords": ["全局视野", "并行计算", "长序列记忆"] }
    },
    {
      "id": "key-metric",
      "narration": "在机器翻译任务上，Transformer 比 RNN 提升了 2 个 BLEU 分数，训练速度还快了 4 倍。",
      "headline": "实验结果",
      "visual": { "type": "stat", "value": "4x", "label": "训练速度提升" }
    },
    {
      "id": "conclusion",
      "narration": "注意力机制让模型不再受序列长度限制，成为现代大语言模型的基石。",
      "headline": "奠基之作",
      "visual": { "type": "summary", "items": ["解决长序列遗忘", "训练可并行", "现代 LLM 的基石"] }
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
