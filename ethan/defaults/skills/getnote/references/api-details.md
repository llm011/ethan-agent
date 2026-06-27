# API 详情 - references/api-details.md

## Scope 权限列表

- `note.content.read` - 读取笔记
- `note.content.write` - 写入笔记
- `note.recall.read` - 搜索笔记
- `knowledge.read` - 读取知识库
- `knowledge.write` - 管理知识库
- `blogger.read` - 读取博主内容
- `live.read` - 读取直播

---

## 错误码详解

| 错误码 | 说明 | 原因 | 处理方式 |
|--------|------|------|----------|
| 10000 | 参数错误 | 请求参数不正确 | 检查请求参数 |
| 10001 | 鉴权失败 | API Key 或 Client ID 错误 | 重新配置 |
| 10100 | 数据不存在 | 笔记/知识库 ID 不存在 | 确认 ID 正确 |
| 10201 | 非会员 | 需要开通会员 | 引导开通会员 |
| 10202 | QPS 限流 | 请求过于频繁 | 降低频率 |
| 30000 | 服务调用失败 | 第三方服务错误 | 稍后重试 |
| 50000 | 系统错误 | 服务器内部错误 | 稍后重试 |

---

## Rate Limit 限流

响应头部：
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 59
X-RateLimit-Reset: 1700000000
```

---

## 笔记 ID 处理

笔记 ID 是 64 位整数，需要作为字符串处理：

```javascript
// 错误：会丢失精度
const id = data.note.id;

// 正确
const id = String(data.note.id);
```