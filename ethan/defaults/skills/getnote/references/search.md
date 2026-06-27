# 搜索 - references/search.md

## POST /open/api/v1/resource/recall

全局语义搜索。

### 请求头
```
Authorization: $GETNOTE_API_KEY
X-Client-ID: $GETNOTE_CLIENT_ID
```

### 请求体
```json
{
  "query": "搜索关键词",
  "limit": 20,
  "cursor": "可选游标"
}
```

### 响应（实际格式，注意不是 `result.notes`）
```json
{
  "success": true,
  "data": {
    "results": [
      {
        "note_id": "1908554212523171768",
        "title": "笔记标题",
        "content": "笔记内容摘要...",
        "note_type": "NOTE",
        "created_at": "2026-04-29 18:22:39"
      }
    ]
  }
}
```

**重要坑点**：
- 返回路径是 `data.results`，不是 `result.notes`
- 笔记对象字段是 `note_id`（字符串），不是 `id`
- 不含 `score` 字段，含 `note_type` 和 `created_at`

---

## POST /open/api/v1/resource/recall/knowledge

知识库语义搜索。

### 请求头
```
Authorization: $GETNOTE_API_KEY
X-Client-ID: $GETNOTE_CLIENT_ID
```

### 请求体
```json
{
  "knowledge_id": "知识库ID",
  "query": "搜索关键词",
  "limit": 20,
  "cursor": "可选游标"
}
```

### 响应
同全局搜索格式。