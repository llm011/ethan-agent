---
name: channels
description: "消息渠道接入配置：飞书 WebSocket 长连接配置与使用说明。未来支持微信、Telegram 等渠道。"
trigger: "渠道|channel|飞书配置|lark配置|接入|webhook|websocket|消息渠道"
fast_path: true
---

# 消息渠道接入 (Channels)

Ethan 支持通过多种渠道收发消息，无需公网 IP。

## 飞书 (Feishu/Lark)

通过 WebSocket 长连接接收消息，使用 lark-cli event consume 建立持久连接。

### 配置步骤

1. 在飞书开发者后台创建企业自建应用
2. 获取 App ID 和 App Secret
3. 在 Ethan Web 设置 → 渠道 → 飞书 中填入凭据
4. 重启服务：`./manager.sh restart`

### 初始化 lark-cli

```bash
lark-cli config init  # 首次配置，会弹出授权链接
```

配置文件位于 `~/.lark/config.yaml`。

### 连接状态检查

```bash
lark-cli event consume im.message.receive_v1 --as bot --quiet
```

## 未来渠道

- 微信 (WeChat)
- Telegram
- Slack

新渠道接入后，在此文件中补充对应的配置说明。
