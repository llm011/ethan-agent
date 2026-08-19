# 视觉预设

使用 Open Motion/CSS 生成的可复现视觉，不依赖外部图片。

| `visual.type` | 数据字段 | 适用场景 |
|---|---|---|
| `kinetic-text` | `keywords: string[]` | 开场、核心概念、强节奏关键词 |
| `steps` | `items: string[]` | 流程、清单、阶段，最多 5 项 |
| `stat` | `value: string`, `label: string` | 关键数字或短结论 |
| `quote` | `quote: string`, `attribution?: string` | 短引用或作者观点 |
| `summary` | `items: string[]` | 结尾回顾，最多 4 项 |
| `candlestick` | `closes` 或 `candles`，可选 `bands`、`markers` | 金融行情：K 线 + 布林带 + 点位标注 |

选择规则：

- 相邻场景避免使用相同预设。
- 没有可靠数字时不要使用 `stat`。
- `quote` 必须短于 80 个汉字，并保留来源归属。
- 视觉字段缺失时脚本会回退到 `kinetic-text`，但应在写 manifest 时主动补齐。

## candlestick 用法（domain: finance）

- 只有收盘价给 `closes`（8–120 个），上下影线按场景 id 做种子的确定性伪随机合成，重渲染画面一致；有完整 OHLC 给 `candles`（2–60 根）。
- `bands` 画布林带等轨道线：`upper`/`lower` 金色虚线、`middle` 蓝色实线，长度必须与序列一致。
- `markers` 标注关键点位（≤4 个）：`index` 指向序列下标，`label` ≤12 字（如「假突破」「止盈点」），`tone` 决定 chip 颜色（`accent` 黄 / `positive` 红 / `negative` 绿），`position` 选 `above`/`below`。
- 动画为左到右揭示（场景前 40% 帧），marker 在其蜡烛出现后弹出；蜡烛颜色红涨绿跌。
- 金融场景建议同时配 `callouts`（黄色关键词）与 `presenter`（立绘），组成「晓玉说」式画面：左侧标题+K线、右侧立绘、底部字幕。
