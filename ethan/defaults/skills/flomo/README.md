# flomo 浮墨笔记工具

读取/搜索/写入/编辑 flomo 笔记，集成到 ethan-agent 工具体系。

## 功能

| 工具 | 功能 | 数据通道 | 前置条件 |
|------|------|---------|---------|
| `flomo_query` | 搜索/查询笔记 | flomo 私有 API | 客户端已登录 |
| `flomo_tags` | 标签列表 + 频率 | flomo 私有 API | 客户端已登录 |
| `flomo_create` | API 创建笔记 | flomo 私有 API | 客户端已登录 |
| `flomo_edit` | 编辑已有笔记 | flomo 私有 API | 客户端已登录 |
| `flomo_write` | Webhook 写入笔记 | Webhook iwh API | `set_secret("flomo_webhook_key", ...)` |

## 代码来源

### 私有 API（读取/创建/编辑）

来源：**Undertone0809/flomo-crud-skill** — https://github.com/Undertone0809/flomo-crud-skill

借鉴内容：

- API base URL、`api_key`、`app_version` 等固定参数
- 请求签名算法：MD5(排序后的参数 + `API_SECRET`)
- 鉴权方式：`Authorization: Bearer {token}`
- 端点：GET `/memo/updated/`（翻页读取）、PUT `/memo`（创建）、PUT `/memo/{slug}`（编辑）
- 从客户端本地存储提取 `access_token` 的思路
- HTML → Markdown 转换、标签提取等数据处理逻辑

### Webhook 写入

直接 POST `{"content": "..."}` 到 `https://flomoapp.com/iwh/{key}/`，无需参考外部仓库。

### 跨平台适配（本项目扩展）

原项目仅支持 macOS 沙盒版。本项目扩展：

- **macOS 非沙盒版**（官网下载）：`~/Library/Application Support/flomo/`
- **macOS 沙盒版**（App Store）：`~/Library/Containers/com.flomoapp.m/.../flomo/`
- **Windows**：`%APPDATA%/flomo/`
- Token 提取优先从 `config.json` 的 `user.access_token` 读取，兜底从 LevelDB 搜索

