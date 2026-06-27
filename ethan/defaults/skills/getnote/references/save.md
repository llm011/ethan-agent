# 笔记保存 - references/save.md

## POST /open/api/v1/resource/note/save

保存文本、链接或图片笔记。

### 请求头
```
Authorization: $GETNOTE_API_KEY
X-Client-ID: $GETNOTE_CLIENT_ID
```

### 请求体 (JSON)

**文本模式**：
```json
{
  "type": "text",
  "content": "笔记内容",
  "title": "可选标题"
}
```

**链接模式**：
```json
{
  "type": "link",
  "url": "https://example.com",
  "title": "链接标题（可选）"
}
```

**图片模式**：
```json
{
  "type": "image",
  "image_key": "上传返回的image_key",
  "title": "图片标题（可选）"
}
```

### 响应

文本/链接模式（同步）：
```json
{
  "success": true,
  "result": {
    "note_id": "1234567890123456789"
  }
}
```

链接模式（异步）：
```json
{
  "success": true,
  "result": {
    "task_id": "xxx"
  }
}
```

### 查询异步任务进度

**POST /open/api/v1/resource/note/task/progress**

```json
{
  "task_id": "xxx"
}
```

---

## GET /open/api/v1/resource/image/upload_token

获取图片上传凭证。

### 请求头
```
Authorization: $GETNOTE_API_KEY
X-Client-ID: $GETNOTE_CLIENT_ID
```

### 响应
```json
{
  "success": true,
  "result": {
    "image_key": "xxx",
    "upload_url": "https://xxx",
    "form": {}
  }
}
```

### 上传图片流程
1. 调用 upload_token 获取 image_key 和上传地址
2. 使用 POST 上传到 upload_url + form 字段
3. 保存笔记时使用该 image_key