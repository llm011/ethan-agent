---
name: didi-ride
version: 1.0.0
channels: [lark]
description: >
  滴滴打车助手。在飞书群或私聊中说"帮我叫车从A到B"，
  龙虾自动查询车型价格，发送交互式卡片，点击按钮即可下单。
triggers:
  - 叫车
  - 打车
  - 帮我叫个车
  - 去.*怎么打车
  - 打车多少钱
  - 叫个车
  - 网约车
metadata:
  requires:
    tools: ["didi_ride"]
    secrets: ["~/.ethan/.secrets/didi.json"]
  secretKeys: ["didi_mcp_key"]
  coordinatesWith: ["lark-im"]
---

# 滴滴打车助手

通过 `didi_ride` 工具实现飞书内全流程打车体验。

## ⚠️ 工具可用性检查（首要，必须先做）

本技能**强依赖 `didi_ride` 工具**，这是唯一的打车操作入口。开始任何操作前，先确认工具可用：

1. 检查当前会话是否注册了 `didi_ride` 工具。
2. 若工具**未配置 / 未注册**，**不要尝试任何替代方案**（不要 exec JS、不要 `node -e`、不要自己调 MCP），直接向用户返回明确提示：
   > ❌ `didi_ride` 工具未配置，本技能无法工作。
   > 请在 ethan 配置中启用 `didi_ride` MCP 工具，并确保密钥文件 `~/.ethan/.secrets/didi.json` 存在且包含 `didi_mcp_key` 字段。
3. 若工具可用，继续后续流程。

## 🔑 密钥配置

- 密钥文件路径：`~/.ethan/.secrets/didi.json`
- 必需字段：`didi_mcp_key`
- 文件结构（仅示意，非真实值）：
  ```json
  { "didi_mcp_key": "<REDACTED>" }
  ```
- 若文件缺失或字段缺失，按上方"工具可用性检查"中的提示告知用户，不要自行创建或写入密钥。

## 🤝 与 lark-im 的分工

- **didi-ride**：飞书群 / 私聊内的**打车专用**技能。仅处理"叫车 / 打车"意图，通过 `didi_ride` 工具发送交互式打车卡片。
- **lark-im**：通用飞书消息技能（收发消息、群管理、卡片回调等）。
- 打车卡片按钮的回调（叫车、刷新状态、取消订单）由 `didi_ride` 工具内部自动处理，**不需要走 lark-im**。
- 仅当需要额外的飞书消息能力（如主动通知用户、查询群成员）时，才协同使用 lark-im。

## ⚠️ 强制规则（必须遵守）

1. **只能使用 `didi_ride` 工具**。这是唯一的打车操作方式。
2. **绝对禁止使用 exec 调用任何 JS 文件**。不要 `node -e`，不要 `import { callTool }`，不要 `import { searchPlace }`。
3. **不要自己调用 MCP 工具**（如 maps_textsearch、taxi_estimate 等）。`didi_ride` 工具内部会自动完成所有 MCP 调用。
4. **不要用 markdown 表格展示价格**。`didi_ride` 工具会自动发送交互式飞书卡片，用户可以直接点按钮叫车。

违反以上任何一条，用户将无法通过卡片按钮叫车，功能会完全失效。

## 使用方式

### 查询价格并发送交互卡片

一步到位，只需调用一次 `didi_ride` 工具：

```
工具: didi_ride
参数: {
  "action": "query_pricing",
  "from": "太原西客站",
  "to": "武宿机场",
  "city": "太原"
}
```

参数说明：
- `from`（必填）：起点地址，自然语言
- `to`（必填）：终点地址，自然语言
- `city`（可选）：城市名，帮助 POI 搜索更准确

工具会自动完成全部流程：
1. POI 坐标搜索（maps_textsearch）
2. 车型价格查询（taxi_estimate）
3. 路线距离时长（maps_direction_driving）
4. 构建并发送飞书交互卡片（含叫车按钮）

卡片已经包含了全部信息，**调用工具后不要发任何文字回复**。不要总结价格，不要说"卡片已发送"，直接结束。

### 后续交互（自动处理）

用户点击卡片按钮后，由系统自动处理，你不需要做任何事：
- 「叫车 ¥XX」→ 自动创建订单 → 卡片更新为"等待接单"
- 「刷新状态」→ 自动查询 → 卡片更新为最新状态（含司机信息）
- 「取消订单」→ 自动取消 → 卡片更新为"已取消"

## 流程要求

1. 从用户消息中提取起点和终点
2. 如果起点或终点不明确，先询问用户
3. 如果能确定城市，传入 `city` 参数
4. 调用 `didi_ride` 工具（action: query_pricing）
5. **不要发任何文字回复**，卡片就是回复
