---
name: flomo
trigger: flomo|浮墨|浮墨笔记|flomoapp|记灵感|灵感记录|卡片笔记|碎片笔记|快速记一下|随手记|闪念|闪念笔记
description: flomo 浮墨笔记助手 — 写入短笔记/灵感/卡片（Webhook）+ 读取最近笔记（api_key）。适合碎片化快速记录；长笔记/知识管理用 getnote。
---

# flomo Skill

通过 flomo API 写入和读取笔记，支持标签、Markdown、续写卡片。
**纯 HTTP 调用，不依赖浏览器自动化**。

## 适用边界

**flomo（本技能）**：短笔记、灵感、闪念、碎片化快速记录。一句话到几段话，标签化归档。
**getnote**：长笔记、知识管理、笔记列表/详情/搜索/删除、知识库维护。

- 用户只说"记笔记/存笔记/我的笔记"等泛化词 → **走 getnote**（getnote 已声明"笔记"优先）
- 用户明确提到 flomo / 浮墨，或语境是"记个灵感/闪念/卡片" → **走本技能**
- 不确定时优先 getnote（它功能更全，且支持搜索历史）

## 两套凭据

flomo 有两套独立的凭据，用途不同：

| 凭据 | 用途 | 获取方式 | 环境变量 |
|------|------|----------|----------|
| Webhook key | **写入**笔记 | flomo App → 设置 → 「API 及第三方工具」→ Webhook URL 里的 key | `$FLOMO_WEBHOOK_KEY` |
| api_key | **读取**笔记列表/标签 | flomo Web 端登录后从 DevTools 获取（见下方） | `$FLOMO_API_KEY` |

两套 key 互不通用：webhook key 不能用于读取，api_key 不能用于写入。

## 凭据配置

### 1. Webhook key（写入用）

**获取地址**：flomo App → 设置 → 「API 及第三方工具」
- Webhook URL 格式：`https://flomoapp.com/iwh/<key>/`
- 提取 `<key>` 部分

**配置**：
```bash
file_write(path="$HOME/.ethan/.secrets/flomo.env", content='FLOMO_WEBHOOK_KEY="<webhook-key>"')
chmod 600 ~/.ethan/.secrets/flomo.env
```

### 2. api_key（读取用）

**获取地址**：在浏览器打开 `https://v.flomoapp.com/mine/` 登录后获取。

**获取步骤**：
1. 用浏览器打开 `https://v.flomoapp.com/mine/`
2. 如果跳转到登录页，用微信扫码或手机号登录
3. 登录后，按 F12 打开 DevTools → Console，执行：
```javascript
// 从 cookie 中查找
document.cookie.match(/flomo_token=([^;]+)/)?.[1] || 
// 或从 localStorage 查找
Object.keys(localStorage).filter(k => k.toLowerCase().includes('token') || k.toLowerCase().includes('key'))
  .map(k => k + '=' + localStorage.getItem(k))
```
4. 把获取到的 token/key 值告诉 Agent

**配置**：
```bash
file_write(path="$HOME/.ethan/.secrets/flomo.env", content='FLOMO_WEBHOOK_KEY="<webhook-key>"\nFLOMO_API_KEY="<api-key>"')
chmod 600 ~/.ethan/.secrets/flomo.env
```

### 登录态过期检测

读取接口返回以下信号时，说明 api_key 已过期，需重新登录获取：
- `{"code":-1,"message":"请登录"}` 或类似登录失效提示
- HTTP 401/403
- 返回 HTML 登录页面（而非 JSON）

**处理**：引导用户重新打开 `https://v.flomoapp.com/mine/` 登录，按上述步骤重新获取 api_key。

---

## 写入笔记（Webhook）

### 入口
```
POST https://flomoapp.com/iwh/$FLOMO_WEBHOOK_KEY/
```

### 请求格式
`Content-Type: application/json`，body 只有一个字段 `content`：

```bash
curl -s -X POST 'https://flomoapp.com/iwh/$FLOMO_WEBHOOK_KEY/' \
  -H "Content-Type: application/json" \
  -d '{"content":"今天读完了《认知觉醒》第一章 #阅读/认知觉醒"}'
```

### 响应格式
成功：`{"code": 0, "msg": "success", "data": {...}}`
失败：`{"code": <非0>, "msg": "<错误原因>", "data": null}`

| code | 含义 | 处理 |
|------|------|------|
| 0 | 成功 | 笔记已写入，展示给用户确认 |
| -1 | key 失效 / 频率限制 | 引导用户检查 key 或稍后重试 |
| 其他 | 服务异常 | 把 raw response 原样反馈给用户 |

---

## 读取笔记（api_key）

### 入口
```
GET https://flomoapp.com/api/v1/memo/list?timestamp=<unix时间戳>&api_key=$FLOMO_API_KEY
```

### 请求参数
| 参数 | 必填 | 说明 |
|------|------|------|
| timestamp | 是 | Unix 时间戳（秒），`$(date +%s)` |
| api_key | 是 | 从 flomo Web 端获取的 api_key |
| page | 否 | 页码，从 1 开始，默认 1 |
| size | 否 | 每页条数，默认 20，建议设 5-20 |

### 请求示例
```bash
curl -s "https://flomoapp.com/api/v1/memo/list?timestamp=$(date +%s)&api_key=$FLOMO_API_KEY&size=5"
```

### 响应格式
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "memos": [
      {
        "id": "xxx",
        "content": "笔记正文（含 Markdown 和标签）",
        "created_at": 1783879000,
        "tags": ["#阅读/认知觉醒"],
        "files": []
      }
    ],
    "total": 100,
    "page": 1,
    "size": 5
  }
}
```

### 读取时的登录态检测
如果返回以下任一情况，说明 api_key 过期，需引导用户重新登录：
- `{"code":-1,"message":"请登录"}` 或类似
- 返回 HTML 页面（非 JSON）
- `code` 非 0 且 message 含"登录"/"授权"/"token"

**处理流程**：
1. 告诉用户："flomo 登录态已过期，需要重新登录获取 api_key"
2. 引导用户在浏览器打开 `https://v.flomoapp.com/mine/`
3. 登录后按「凭据配置」章节重新获取 api_key
4. 用 `file_write` 更新 `~/.ethan/.secrets/flomo.env`
5. 重新执行读取请求

---

## 能力索引

| 能力 | 实现方式 | 说明 |
|------|----------|------|
| 写入笔记 | Webhook POST | body 只含 `content` 字段 |
| 带标签写入 | content 内嵌 `#tag` | 标签写在内容末尾，多级用 `/` 分隔 |
| Markdown 富文本 | content 支持 MD | 标题、列表、引用、代码块、链接、图片 `![](url)` |
| 读取最近笔记 | GET `/api/v1/memo/list` | 需要 api_key，返回最近 N 条 |
| 读取标签列表 | GET `/api/v1/tag/list` | 需要 api_key，返回所有标签 |
| 续写卡片 | 同标签新笔记 | Webhook 无法编辑旧笔记；"续写"用相同标签 + 引用关键词 |
| 标签索引维护 | file_read/write 本地缓存 | `~/.ethan/.cache/flomo-tags.txt` 记录常用标签 |
| 批量导入 | 循环 curl | 多条笔记分多次 POST，每条间隔 ≥100ms |

---

## 标签规范

### 格式
- 单级：`#工作` `#阅读` `#灵感`
- 多级：`#阅读/认知觉醒` `#工作/项目A/会议`
- 标签必须以 `#` 开头，后面紧跟文字（不要空格）
- 标签内不要有空格，多词用 `-` 或 `_` 连接：`#读书笔记-认知觉醒`

### 位置
- **标签置底**：标签统一放在笔记内容末尾，不要放在开头
- 多个标签用空格分隔：`内容... #阅读 #灵感`
- 多级标签作为分类时，单级标签作为状态：`内容... #阅读/认知觉醒 #未完成`

### 示例
```
今天读完《认知觉醒》第一章，核心观点：元认知是改变的起点。

- 元认知 = 知道自己在想什么
- 改变的第一步是"看见"自己的思维过程

#阅读/认知觉醒 #未完成
```

---

## 本地标签索引

路径：`~/.ethan/.cache/flomo-tags.txt`

格式：每行一个标签 + 简短说明，`#` 开头的行为注释：
```
# flomo 标签索引 — 由 Agent 自动维护，请勿手动编辑
# 格式：<标签> <Tab> <说明>

#阅读/认知觉醒    认知觉醒相关读书笔记
#阅读            通用阅读笔记
#工作/项目A       项目A 相关记录
#灵感            突发的灵感想法
```

### 维护规则
1. **写入前**：先 `file_read` 读取索引，确认标签是否已存在
2. **写入笔记后**：如果用到了新标签，`file_write` 追加到索引末尾（去重）
3. **用户问"我有哪些标签"**：优先尝试 API 读取标签列表；api_key 不可用时回退到本地索引
4. **索引不存在时**：首次使用自动创建空索引文件

---

## 快速调用示例

```bash
# 1. 写一条简单笔记
curl -s -X POST 'https://flomoapp.com/iwh/$FLOMO_WEBHOOK_KEY/' \
  -H "Content-Type: application/json" \
  -d '{"content":"刚冒出来的想法：把 Agent 的工作流做成可分享的技能包 #灵感"}'

# 2. 带 Markdown 格式的读书笔记
curl -s -X POST 'https://flomoapp.com/iwh/$FLOMO_WEBHOOK_KEY/' \
  -H "Content-Type: application/json" \
  -d '{"content":"## 《认知觉醒》第一章\n\n核心观点：元认知是改变的起点。\n\n- 元认知 = 知道自己在想什么\n\n#阅读/认知觉醒"}'

# 3. 读取最近 5 条笔记
curl -s "https://flomoapp.com/api/v1/memo/list?timestamp=$(date +%s)&api_key=$FLOMO_API_KEY&size=5"

# 4. 续写：在同标签下追加新思考
curl -s -X POST 'https://flomoapp.com/iwh/$FLOMO_WEBHOOK_KEY/' \
  -H "Content-Type: application/json" \
  -d '{"content":"续「元认知」思考：写日记本身就是元认知训练。\n\n#阅读/认知觉醒 #延伸思考"}'

# 5. 读取标签列表
curl -s "https://flomoapp.com/api/v1/tag/list?timestamp=$(date +%s)&api_key=$FLOMO_API_KEY"
```

---

## 避坑指南

### 1. Webhook key vs api_key 混淆
- **写入**用 Webhook key（URL path 里）
- **读取**用 api_key（query 参数里）
- 两者不通用，分别配置到 `$FLOMO_WEBHOOK_KEY` 和 `$FLOMO_API_KEY`

### 2. api_key 过期
- **症状**：读取接口返回"请登录"或 HTML 页面
- **原因**：flomo Web 端登录态有过期时间
- **处理**：引导用户重新打开 `https://v.flomoapp.com/mine/` 登录，重新获取 api_key

### 3. Webhook key 失效
- **症状**：写入返回 `{"code":-1,"msg":"..."}`
- **原因**：用户在 App 内重置了 key
- **处理**：引导用户重新获取 Webhook key

### 4. 频率限制
- **写入**：约 10 条/分钟，批量写入间隔 ≥100ms
- **读取**：未公开限制，但不要频繁轮询

### 5. 标签格式错误
- **错误**：`# 阅读`（# 后有空格）、`#阅读 认知`（标签内空格会被截断）
- **正确**：`#阅读/认知觉醒`、`#读书笔记-认知觉醒`

### 6. 内容为空或超长
- **空内容**：`{"content":""}` 会被拒绝
- **超长**：单条建议 < 5000 字，超长时拆分为多条续写

### 7. 读取接口缺 timestamp
- **错误**：`{"code":-1,"message":"请传入 timestamp"}`
- **正确**：必须带 `timestamp=$(date +%s)` 参数

### 8. 图片上传
- **限制**：Webhook 不支持直接上传图片文件
- **方案**：图片需先上传到图床，得到公网 URL 后用 `![](url)` 嵌入

---

## 关键纪律

- **写入用 `$FLOMO_WEBHOOK_KEY`**：URL `https://flomoapp.com/iwh/$FLOMO_WEBHOOK_KEY/`，key 只在 path，不放 body
- **读取用 `$FLOMO_API_KEY`**：URL `https://flomoapp.com/api/v1/memo/list?timestamp=$(date +%s)&api_key=$FLOMO_API_KEY`
- **登录态过期时主动提示**：读取返回登录失效信号时，立即引导用户重新登录 `https://v.flomoapp.com/mine/`
- **标签置底**：标签统一放在 content 末尾
- **多级标签用 `/`**：`#阅读/认知觉醒`
- **写入前查本地索引**：避免重复造标签
- **批量写入间隔 ≥100ms**：避免触发频率限制
- **失败时展示 raw response**：不要编造成功
- **续写而非编辑**：Webhook 无法编辑旧笔记，"续写"用同标签新笔记

activate_tools: shell, file_write, file_read
