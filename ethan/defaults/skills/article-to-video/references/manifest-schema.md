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
| `voice` | 否 | Edge TTS 参数 |
| `theme` | 否 | 颜色主题 |
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

`theme` 支持 `background`、`surface`、`primary`、`secondary`、`text` 六位十六进制颜色。

## 场景字段

| 字段 | 必需 | 说明 |
|---|---:|---|
| `id` | 是 | 唯一 kebab-case ID，后续修改时保持稳定 |
| `narration` | 是 | 实际送入 TTS 的旁白，20–180 个汉字为宜 |
| `headline` | 是 | 屏幕主标题，建议不超过 24 个汉字 |
| `body` | 否 | 屏幕补充文本，建议不超过 60 个汉字 |
| `visual` | 是 | 视觉预设及其数据 |

## 完整示例

```json
{
  "title": "AI Agent 为什么正在改变软件",
  "summary": "从工具到行动者，软件交互正在发生变化。",
  "width": 1080,
  "height": 1920,
  "fps": 30,
  "targetDurationSec": 60,
  "durationToleranceSec": 6,
  "language": "zh-CN",
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
      "narration": "为什么 AI Agent 可能比聊天机器人更深刻地改变软件？",
      "headline": "软件，开始自己行动",
      "body": "AI Agent 不只回答问题，也能拆解目标并调用工具。",
      "visual": {
        "type": "kinetic-text",
        "keywords": ["理解目标", "调用工具", "完成任务"]
      }
    },
    {
      "id": "three-changes",
      "narration": "它带来三个变化：操作步骤变少，软件之间开始协作，人的角色转向设定目标和审核结果。",
      "headline": "三个变化",
      "visual": {
        "type": "steps",
        "items": ["步骤更少", "软件协作", "人负责目标与审核"]
      }
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
