# Gmail 工作流配方 (Recipes)

## 1. 保存附件到 Google Drive
**步骤**:
1. 搜索带附件邮件: `gws gmail users messages list --params '{"userId": "me", "q": "has:attachment"}'`
2. 获取消息详情及 AttachmentID: `gws gmail users messages get --params '{"userId": "me", "id": "MSG_ID"}'`
3. 提取附件: `gws gmail users messages attachments get --params '{"userId": "me", "messageId": "MSG_ID", "id": "ATT_ID"}'`
4. 上传至云盘: `gws drive +upload --file "./path" --parent "FOLDER_ID"`

## 2. 批量转发特定标签邮件
**步骤**:
1. 列表标签: `gws gmail users messages list --params '{"q": "label:important"}'`
2. 循环转发: `gws gmail +forward --message-id "ID" --to "recipient@example.com"`

> [!CAUTION]
> 批量转发属写操作，必须在执行前向用户展示预览（受影响数量、收件人），获得明确确认后才能继续。

## 3. 自动整理收件箱 (Label & Archive)
**步骤**:
1. 搜索匹配邮件。
2. 打标签: `gws gmail users messages batchModify --json '{"ids": ["ID1"], "addLabelIds": ["LABEL_ID"]}'`
3. 归档: `gws gmail users messages batchModify --json '{"ids": ["ID1"], "removeLabelIds": ["INBOX"]}'`

## 4. 增量检查新邮件（结合状态文件）

利用 `~/.ethan/.secrets/gmail_last_check_v2.json` 记录上次检查时间，避免重复处理：

```bash
# 1. 读取上次检查时间
LAST_TS=$(jq -r '.last_check // 0' ~/.ethan/.secrets/gmail_last_check_v2.json)

# 2. 用 Gmail 查询语法筛选此时间之后的新邮件（ Gmail q 支持 after: 时间戳）
gws gmail +triage --query "is:unread after:${LAST_TS}"

# 3. 处理完后更新时间戳
NOW=$(date +%s)
jq --arg now "$NOW" '.last_check = ($now | tonumber)' \
   ~/.ethan/.secrets/gmail_last_check_v2.json > tmp.json \
   && mv tmp.json ~/.ethan/.secrets/gmail_last_check_v2.json
```

> 该文件**仅记录时间戳和已处理的 message id**，不是凭证。凭证由 `gws auth` 自行管理。

## 5. 用 +watch 持续监听收件箱

```bash
# 一次性拉取当前未读
gws gmail +watch --project my-gcp-project --label-ids INBOX --once --output-dir ./emails

# 持续监听（注意 watch 每 7 天过期，需重新执行）
gws gmail +watch --project my-gcp-project --label-ids INBOX
```
