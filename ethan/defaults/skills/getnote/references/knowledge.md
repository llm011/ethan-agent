# 知识库 - references/knowledge.md

## GET /open/api/v1/resource/knowledge/list

获取我的知识库列表。

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
    "knowledge_list": [
      {
        "id": "1234567890123456789",
        "name": "知识库名称",
        "note_count": 100,
        "created_at": 1700000000
      }
    ]
  }
}
```

---

## POST /open/api/v1/resource/knowledge/create

创建知识库。

### 请求头
```
Authorization: $GETNOTE_API_KEY
X-Client-ID: $GETNOTE_CLIENT_ID
```

### 请求体
```json
{
  "name": "新知识库名称"
}
```

---

## GET /open/api/v1/resource/knowledge/notes

获取知识库笔记列表。

### 请求头
```
Authorization: $GETNOTE_API_KEY
X-Client-ID: $GETNOTE_CLIENT_ID
```

### 查询参数
- `knowledge_id`: 知识库 ID（必填）
- `cursor`: 分页游标
- `limit`: 每页数量

---

## POST /open/api/v1/resource/knowledge/note/batch-add

添加笔记到知识库。

### 请求头
```
Authorization: $GETNOTE_API_KEY
X-Client-ID: $GETNOTE_CLIENT_ID
```

### 请求体
```json
{
  "knowledge_id": "知识库ID",
  "note_ids": ["笔记ID1", "笔记ID2"]
}
```

---

## GET /open/api/v1/resource/knowledge/subscribe/list

获取订阅的知识库列表。

---

## GET /open/api/v1/resource/knowledge/bloggers

获取知识库博主列表。

---

## GET /open/api/v1/resource/knowledge/blogger/contents

获取博主内容列表。

---

## GET /open/api/v1/resource/knowledge/lives

获取知识库直播列表。

---

## POST /open/api/v1/resource/knowledge/live/follow

关注直播。