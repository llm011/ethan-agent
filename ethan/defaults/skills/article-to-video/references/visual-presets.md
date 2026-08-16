# 视觉预设

MVP 只使用 Open Motion/CSS 生成的可复现视觉，不依赖外部图片。

| `visual.type` | 数据字段 | 适用场景 |
|---|---|---|
| `kinetic-text` | `keywords: string[]` | 开场、核心概念、强节奏关键词 |
| `steps` | `items: string[]` | 流程、清单、阶段，最多 5 项 |
| `stat` | `value: string`, `label: string` | 关键数字或短结论 |
| `quote` | `quote: string`, `attribution?: string` | 短引用或作者观点 |
| `summary` | `items: string[]` | 结尾回顾，最多 4 项 |

选择规则：

- 相邻场景避免使用相同预设。
- 没有可靠数字时不要使用 `stat`。
- `quote` 必须短于 80 个汉字，并保留来源归属。
- 视觉字段缺失时脚本会回退到 `kinetic-text`，但应在写 manifest 时主动补齐。
