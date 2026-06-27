# 标签 - references/tags.md

## POST /open/api/v1/resource/note/tags/add

添加标签。

### 请求头
```
Authorization: $GETNOTE_API_KEY
X-Client-ID: $GETNOTE_CLIENT_ID
```

### 请求体
```json
{
  "note_id": "笔记ID",
  "tags": ["标签1", "标签2"]
}
```

---

## POST /open/api/v1/resource/note/tags/delete

删除标签。

### 请求头
```
Authorization: $GETNOTE_API_KEY
X-Client-ID: $GETNOTE_CLIENT_ID
```

### 请求体
```json
{
  "note_id": "笔记ID",
  "tags": ["标签1"]
}
```