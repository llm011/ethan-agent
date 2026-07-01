# 获取群成员列表 (chat.members.get)

用于获取指定群聊的成员列表信息。调用方必须位于目标群内，且属于同一租户。

## 基本命令
```bash
lark-cli im chat.members get --params '{"chat_id": "<chat_id>"}' --page-all
```

## 参数说明
* `chat_id` (string): 群 ID (以 `oc_` 开头)
* `member_id_type` (string): 成员 ID 类型，可选 `user_id`、`union_id`、`open_id`（默认 `open_id`）
* `--page-all`: 自动翻页遍历获取全部群成员。

## 返回示例
```json
{
  "items": [
    {
      "member_id": "ou_...",
      "member_id_type": "open_id",
      "name": "张三",
      "tenant_key": "..."
    }
  ],
  "member_total": 10
}
```
