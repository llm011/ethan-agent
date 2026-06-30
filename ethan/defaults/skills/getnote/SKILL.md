---
name: getnote
trigger: 笔记|记笔记|笔记本|我的笔记|记到笔记|存到笔记|biji|get笔记
description: |
  Get笔记 - 保存、搜索、管理个人笔记和知识库。**用户提到「笔记」时优先用本 skill。**

  **当以下情况时使用此 Skill**：
  (1) 用户提到「笔记」相关的任何操作：记笔记、存到笔记、查笔记、看我的笔记、改/删笔记等
  (2) 保存纯文本/图片笔记、说「记到 Get笔记」「存到 biji」
  (3) 查看笔记列表/详情、更新、删除
  (4) 管理知识库或标签：「加到笔记知识库」「建知识库」「加标签」
  (5) 配置 Get笔记：「配置笔记」「连接 Get笔记」

  **不归此 skill 管**：
  - 用户明确说「知识库」且没提「笔记」（如「存到知识库 / 查知识库」）→ 用内置 `knowledge_add` / `knowledge_search` / `knowledge_read` / `knowledge_edit` 工具，那是 ethan 本地知识库
  - 保存网页/微信链接到笔记 → 交给 `getnote-read-link`
  - 从笔记中搜索已有内容（"找一下笔记里的 XX"）→ 交给 `getnote-read-link`
metadata: {"openclaw": {"requires": {}, "optionalEnv": ["GETNOTE_API_KEY", "GETNOTE_CLIENT_ID", "GETNOTE_OWNER_ID"], "baseUrl": "https://openapi.biji.com", "homepage": "https://biji.com"}}
---

# Get笔记 Skill

## ⚠️ Agent 必读约束

### 🌐 Base URL
```
https://openapi.biji.com
```
所有 API 请求必须使用此 Base URL，不要使用 `biji.com` 或其他地址。

### 🔑 认证
请求头：
- `Authorization: $GETNOTE_API_KEY`（格式：`gk_live_xxx`）
- `X-Client-ID: $GETNOTE_CLIENT_ID`（格式：`cli_xxx`）

凭证存放在 `~/.ethan/.secrets/getnote.env`（`KEY="value"` 形式），运行 shell 工具时会**自动注入子进程环境**，所以在 `shell` 里写 `curl` 时直接用 `$GETNOTE_API_KEY` / `$GETNOTE_CLIENT_ID` 即可，**无需 get_secret，也不要把 key 明文写进回复**。

**每次调用 API 前先检测凭证是否齐全**：用 `shell` 跑

```bash
test -n "$GETNOTE_API_KEY" && test -n "$GETNOTE_CLIENT_ID" && echo READY || echo MISSING
```

- 输出 `READY` → 凭证已配，直接继续。
- 输出 `MISSING` → 凭证缺失，**引导用户提供** `GETNOTE_API_KEY` 和 `GETNOTE_CLIENT_ID`（怎么拿见 [references/oauth.md](references/oauth.md)）。拿到后**由你（agent）写入** `~/.ethan/.secrets/getnote.env`，不要让用户手动编辑文件，也不要把值回显到对话里。写入方式（用 `file_write` 工具，path=`~/.ethan/.secrets/getnote.env`，content 为下面两行）：
  ```
  GETNOTE_API_KEY="<用户给的 key>"
  GETNOTE_CLIENT_ID="<用户给的 client id>"
  ```
  写完用 `shell` 跑 `chmod 600 ~/.ethan/.secrets/getnote.env` 收紧权限。然后**重新执行用户原本的请求**（新的 shell 调用会自动注入刚写入的变量）。

> 说明：getnote 用的是 `.env`（多键、需注入 shell）形式，所以走 `file_write` 写文件，而不是 `set_secret`（`set_secret` 存的是单值文件，不会被 shell 注入）。

Scope 权限：`note.content.read`（读取）、`note.content.write`（写入）、`note.recall.read`（搜索）。完整列表见 [references/api-details.md](references/api-details.md#scope-权限列表)。

### 🔢 笔记 ID 处理规则（重要！）
笔记 ID 是 **64 位整数（int64）**，超出 JavaScript `Number.MAX_SAFE_INTEGER`，直接 `JSON.parse` 会**静默丢失精度**。

**正确做法**：始终把 ID 当字符串处理，在 `JSON.parse` 之前替换：
```javascript
const safe = text.replace(/"(id|note_id|parent_id|follow_id|live_id)"\s*:\s*(\d+)/g, '"$1":"$2"');
const data = JSON.parse(safe);
```

### 🔒 安全规则
- 笔记数据属于用户隐私，不在群聊中主动展示笔记内容
- 若配置了 `GETNOTE_OWNER_ID`，检查 sender_id 是否匹配；不匹配时回复「抱歉，笔记是私密的，我无法操作」
- API 返回 `error.reason: "not_member"` 或错误码 `10201` 时，引导开通会员：https://www.biji.com/checkout?product_alias=6AydVpYeKl
- 创建笔记建议间隔 1 分钟以上，避免触发限流

---

## 指令路由表

> 匹配指令后，用 **read 工具**读取对应的 `references/xxx.md` 获取完整 API 文档。

| 指令 | 角色 | 说明 | 详细文档 |
|------|------|------|----------|
| `/note save` 或「记一下」| 📝 速记员 | 保存文本/链接/图片笔记（含异步轮询流程） | [references/save.md](references/save.md) |
| `/note search` 或「搜一下」| 🔍 搜索官 | 全局语义搜索 + 知识库语义搜索 | [references/search.md](references/search.md) |
| `/note list` 或「最近的笔记」| 📋 整理师 | 浏览列表、查看详情、更新、删除 | [references/list.md](references/list.md) |
| `/note kb` 或「知识库」| 📚 图书管理员 | 知识库 CRUD + 博主订阅 + 直播订阅 | [references/knowledge.md](references/knowledge.md) |
| `/note tag` 或「加标签」| 🏷️ 标签员 | 添加/删除标签 | [references/tags.md](references/tags.md) |
| `/note config` 或「配置笔记」| ⚙️ 配置 | 配置 API Key 和 Client ID | [references/oauth.md](references/oauth.md) |

---

## 自然语言路由

```
包含 URL（`biji.com/note/share_note/*` 或 `d.biji.com/*` 短链）  → /note save（link 模式，同步返回 note_id）
包含 URL（`biji.com/note/{note_id}` 内链）    → /note list（查看详情）
其他 URL                   → /note save（link 模式，异步返回 task_id）
包含图片                    → /note save（image 模式）
「记/存/保存/收藏」          → /note save（text 模式）
「搜/找找/有没有 XX」        → /note search
「最近/列表/看看/查笔记」    → /note list
「改/更新/编辑笔记」         → /note list（更新笔记）
「知识库」相关              → /note kb
「标签」相关                → /note tag
「配置/授权/连接笔记」       → /note config
```

**决策原则**：优先匹配最具体的意图。有 URL 就是 `/save link`，有图片就是 `/save image`，不确定时询问用户。

---

## API 路由表

> ⚠️ **构造请求时必须使用下表中的完整路径**，Base URL 为 `https://openapi.biji.com`。如果收到 404，说明路径不对，请对照此表检查。

### 笔记

| 方法 | 路径 | 说明 | 详细文档 |
|------|------|------|----------|
| POST | `/open/api/v1/resource/note/save` | 新建笔记（文本/链接/图片） | [save.md](references/save.md) |
| POST | `/open/api/v1/resource/note/task/progress` | 查询异步任务进度 | [save.md](references/save.md) |
| GET  | `/open/api/v1/resource/note/list` | 笔记列表（分页） | [list.md](references/list.md) |
| GET  | `/open/api/v1/resource/note/detail` | 笔记详情 | [list.md](references/list.md) |
| POST | `/open/api/v1/resource/note/update` | 更新笔记 | [list.md](references/list.md) |
| POST | `/open/api/v1/resource/note/delete` | 删除笔记 | [list.md](references/list.md) |
| POST | `/open/api/v1/resource/note/sharing` | 创建笔记分享链接 | [list.md](references/list.md) |
| POST | `/open/api/v1/resource/note/tags/add` | 添加标签 | [tags.md](references/tags.md) |
| POST | `/open/api/v1/resource/note/tags/delete` | 删除标签 | [tags.md](references/tags.md) |
| GET  | `/open/api/v1/resource/image/upload_token` | 获取图片上传凭证 | [save.md](references/save.md) |

### 搜索

| 方法 | 路径 | 说明 | 详细文档 |
|------|------|------|----------|
| POST | `/open/api/v1/resource/recall` | 全局语义搜索 | [search.md](references/search.md) |
| POST | `/open/api/v1/resource/recall/knowledge` | 知识库语义搜索 | [search.md](references/search.md) |

### 知识库

| 方法 | 路径 | 说明 | 详细文档 |
|------|------|------|----------|
| GET  | `/open/api/v1/resource/knowledge/list` | 我的知识库列表 | [knowledge.md](references/knowledge.md) |
| GET  | `/open/api/v1/resource/knowledge/subscribe/list` | 订阅知识库列表 | [knowledge.md](references/knowledge.md) |
| POST | `/open/api/v1/resource/knowledge/create` | 创建知识库 | [knowledge.md](references/knowledge.md) |
| GET  | `/open/api/v1/resource/knowledge/notes` | 知识库笔记列表 | [knowledge.md](references/knowledge.md) |
| POST | `/open/api/v1/resource/knowledge/note/batch-add` | 添加笔记到知识库 | [knowledge.md](references/knowledge.md) |
| POST | `/open/api/v1/resource/knowledge/note/remove` | 从知识库移除笔记 | [knowledge.md](references/knowledge.md) |
| GET  | `/open/api/v1/resource/knowledge/bloggers` | 知识库博主列表 | [knowledge.md](references/knowledge.md) |
| GET  | `/open/api/v1/resource/knowledge/blogger/contents` | 博主内容列表 | [knowledge.md](references/knowledge.md) |
| GET  | `/open/api/v1/resource/knowledge/blogger/content/detail` | 博主内容详情 | [knowledge.md](references/knowledge.md) |
| GET  | `/open/api/v1/resource/knowledge/lives` | 知识库直播列表 | [knowledge.md](references/knowledge.md) |
| GET  | `/open/api/v1/resource/knowledge/live/detail` | 直播详情 | [knowledge.md](references/knowledge.md) |
| POST | `/open/api/v1/resource/knowledge/live/follow` | 关注直播 | [knowledge.md](references/knowledge.md) |

---

## 通用错误处理

```json
{
  "success": false,
  "error": {
    "code": 10001,
    "message": "unauthorized",
    "reason": "not_member"
  },
  "request_id": "xxx"
}
```

| 错误码 | 说明 | 处理方式 |
|--------|------|----------|
| 10000 | 参数错误 | 检查请求参数 |
| 10001 | 鉴权失败 | 检查 API Key 和 Client ID，或重新授权 |
| 10100 | 数据不存在 | 确认笔记/知识库 ID 正确 |
| 10201 | 非会员 | 引导开通：https://www.biji.com/checkout?product_alias=6AydVpYeKl |
| 10202 | QPS 限流 | 降低频率，查看 rate_limit 字段 |
| 30000 | 服务调用失败 | 稍后重试 |
| 50000 | 系统错误 | 稍后重试 |

详细错误码和限流结构见 [references/api-details.md](references/api-details.md)。