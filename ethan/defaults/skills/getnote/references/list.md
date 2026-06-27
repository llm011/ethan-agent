# 笔记列表 - references/list.md

## GET /open/api/v1/resource/note/list

获取笔记列表（分页）。

### 请求头
```
Authorization: $GETNOTE_API_KEY
X-Client-ID: $GETNOTE_CLIENT_ID
```

### 查询参数
- `cursor`: 分页游标（可选）
- `limit`: 每页数量，默认 20
- `type`: 过滤类型（可选）：text, link, image

### 响应
```json
{
  "success": true,
  "result": {
    "notes": [
      {
        "id": "1234567890123456789",
        "title": "笔记标题",
        "content": "笔记内容",
        "type": "text",
        "created_at": 1700000000,
        "updated_at": 1700000000
      }
    ],
    "next_cursor": "xxx"
  }
}
```

---

## GET /open/api/v1/resource/note/detail

获取笔记详情。

### 请求头
```
Authorization: $GETNOTE_API_KEY
X-Client-ID: $GETNOTE_CLIENT_ID
```

### 查询参数
- `note_id`: 笔记 ID（必填）

### 响应
```json
{
  "success": true,
  "result": {
    "id": "1234567890123456789",
    "title": "笔记标题",
    "content": "笔记内容",
    "type": "text",
    "created_at": 1700000000,
    "updated_at": 1700000000
  }
}
```

---

## POST /open/api/v1/resource/note/update

更新笔记。

### 请求头
```
Authorization: $GETNOTE_API_KEY
X-Client-ID: $GETNOTE_CLIENT_ID
```

### 请求体
```json
{
  "note_id": "1234567890123456789",
  "title": "新标题",
  "content": "新内容"
}
```

---

## POST /open/api/v1/resource/note/delete

删除笔记。

### 请求头
```
Authorization: $GETNOTE_API_KEY
X-Client-ID: $GETNOTE_CLIENT_ID
```

### 请求体
```json
{
  "note_id": "1234567890123456789"
}
```

---

## POST /open/api/v1/resource/note/sharing

创建笔记分享链接。

### 请求头
```
Authorization: $GETNOTE_API_KEY
X-Client-ID: $GETNOTE_CLIENT_ID
```

### 请求体
```json
{
  "note_id": "1234567890123456789"
}
```

### 响应
```json
{
  "success": true,
  "result": {
    "share_url": "https://biji.com/note/share_note/xxx"
  }
}
```