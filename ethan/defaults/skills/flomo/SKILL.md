---
name: flomo
trigger: flomo|浮墨|浮墨笔记|flomoapp|记灵感|灵感记录|卡片笔记|碎片笔记|快速记一下|随手记|闪念|闪念笔记
description: flomo 浮墨笔记助手 — 通过官方 Webhook 写入短笔记、灵感、卡片，支持标签、续写、本地标签索引。适合碎片化快速记录；长笔记/知识管理用 getnote。
---

# flomo Skill

通过 flomo 官方 Webhook API 写入笔记到浮墨笔记，支持标签、Markdown、续写卡片。
**纯 HTTP 调用，不依赖浏览器**。

## 适用边界

**flomo（本技能）**：短笔记、灵感、闪念、碎片化快速记录。一句话到几段话，标签化归档。
**getnote**：长笔记、知识管理、笔记列表/详情/搜索/删除、知识库维护。

- 用户只说"记笔记/存笔记/我的笔记"等泛化词 → **走 getnote**（getnote 已声明"笔记"优先）
- 用户明确提到 flomo / 浮墨，或语境是"记个灵感/闪念/卡片" → **走本技能**
- 不确定时优先 getnote（它功能更全，且支持搜索历史）

## 调用规范

### 统一入口
```
POST https://flomoapp.com/iwh/<你的key>/
```
- `<你的key>` 是用户专属的 Webhook key（在 flomo App 设置 → 「API 及第三方工具」获取）
- Webhook 仅支持写入，不支持读取已有笔记
- Webhook 不依赖登录态 cookie，key 即凭据

### 鉴权
- API Key 直接放在 URL 路径里，无需 Header 鉴权
- 不要把 key 放到 body 或 query string，只在 URL path 中
- key 严禁泄露，泄露后用户可在 App 内重置

### 请求格式
所有请求都是 `POST`，`Content-Type: application/json`，body 只有一个字段 `content`：

```bash
curl -s -X POST 'https://flomoapp.com/iwh/$FLOMO_WEBHOOK_KEY/' \
  -H "Content-Type: application/json" \
  -d '{"content":"今天读完了《认知觉醒》第一章 #阅读/认知觉醒\n\n核心观点：元认知是改变的起点。"}'
```

### 响应格式
成功：`{"code": 0, "msg": "success", "data": {...}}`
失败：`{"code": <非0>, "msg": "<错误原因>", "data": null}`

| code | 含义 | 处理 |
|------|------|------|
| 0 | 成功 | 笔记已写入，可展示给用户确认 |
| -1 | key 失效 / 频率限制 | 引导用户检查 key 或稍后重试 |
| 其他 | 服务异常 | 把 raw response 原样反馈给用户 |

### Webhook Key 配置

密钥存 `~/.ethan/.secrets/flomo.env`，shell 自动注入成 `$FLOMO_WEBHOOK_KEY`。

**首次使用**：如果 curl 返回 `code != 0` 或连接失败，引导用户：
1. 打开 flomo App → 设置 → 「API 及第三方工具」查看 Webhook URL
2. 从 URL `https://flomoapp.com/iwh/<key>/` 中提取 `<key>` 部分
3. Agent 用 `file_write` 写入（不要让用户手动编辑）：
```bash
file_write(path="$HOME/.ethan/.secrets/flomo.env", content='FLOMO_WEBHOOK_KEY="<key>"')
chmod 600 ~/.ethan/.secrets/flomo.env
```
4. 重新执行用户请求。写入后 shell 环境变量自动注入，后续 curl 无需手动设 URL。

---

## 能力索引

| 能力 | 实现方式 | 说明 |
|------|----------|------|
| 写入笔记 | Webhook POST | 单条或多条笔记，多条用空行或 `\n\n` 分隔 |
| 带标签写入 | content 内嵌 `#tag` | 标签写在内容末尾，多级用 `/` 分隔：`#阅读/认知觉醒` |
| Markdown 富文本 | content 支持 MD | 标题、列表、引用、代码块、链接、图片 `![](url)` 均可 |
| 续写卡片 | 同标签新笔记 | Webhook 无法编辑旧笔记；"续写"用相同标签 + 引用关键词实现语义关联 |
| 追加到指定主题 | 同标签 + 引用前文 | 在新笔记中引用旧笔记的关键句作为上下文 |
| 标签索引维护 | file_read/write 本地缓存 | `~/.ethan/.cache/flomo-tags.txt` 记录用户常用标签 |
| 查询已有标签 | file_read 本地缓存 | 写入前先查本地索引，避免重复造标签 |
| 批量导入 | 循环 curl | 多条笔记分多次 POST，每条间隔 ≥100ms 避免频率限制 |
| 历史回顾提示 | 引导用户去 App | Webhook 不支持读取，回顾功能请引导用户打开 flomo App |

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
- 每日 5 分钟复盘可以训练元认知

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
#日记            每日复盘
```

### 维护规则
1. **写入前**：先 `file_read` 读取索引，确认用户提到的标签是否已存在
2. **写入笔记后**：如果用到了新标签或新多级分类，`file_write` 追加到索引末尾（去重）
3. **用户问"我有哪些标签"**：直接读索引展示，不调用 API
4. **索引不存在时**：首次使用自动创建空索引文件
5. **用户纠正标签**：更新索引中对应行

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
  -d '{"content":"## 《认知觉醒》第一章\n\n核心观点：元认知是改变的起点。\n\n- 元认知 = 知道自己在想什么\n- 改变的第一步是看见自己的思维\n\n#阅读/认知觉醒"}'

# 3. 续写：在同标签下追加新思考（引用前文关键词）
curl -s -X POST 'https://flomoapp.com/iwh/$FLOMO_WEBHOOK_KEY/' \
  -H "Content-Type: application/json" \
  -d '{"content":"续「元认知」思考：今天发现写日记本身就是元认知训练，因为写 = 看见。\n\n#阅读/认知觉醒 #延伸思考"}'

# 4. 多级标签
curl -s -X POST 'https://flomoapp.com/iwh/$FLOMO_WEBHOOK_KEY/' \
  -H "Content-Type: application/json" \
  -d '{"content":"项目A 周会决议：下周开始用 ethan agent 做需求拆解 #工作/项目A/会议"}'

# 5. 带图片（必须是公网可访问 URL）
curl -s -X POST 'https://flomoapp.com/iwh/$FLOMO_WEBHOOK_KEY/' \
  -H "Content-Type: application/json" \
  -d '{"content":"截了一张架构图\n\n![](https://example.com/arch.png)\n\n#工作/架构"}'
```

---

## 避坑指南

### 1. Webhook key 失效
- **症状**：curl 返回 `{"code":-1,"msg":"..."}`
- **原因**：用户在 App 内重置了 key，或 key 被风控
- **处理**：引导用户重新获取 key 并写入 `~/.ethan/.secrets/flomo.env`

### 2. 频率限制
- **症状**：连续写入多条时部分失败
- **原因**：flomo 对 Webhook 有频率限制（具体未公开，约 10 条/分钟）
- **处理**：批量写入时每条间隔 ≥100ms；失败时 sleep 1s 重试一次

### 3. key 写在 body 或 query
- **错误**：`?key=xxx` 或 body 里带 `{"key":"xxx"}`
- **正确**：key 只在 URL path：`https://flomoapp.com/iwh/xxx/`
- **原因**：Webhook 设计就是 path-based，body 只认 `content`

### 4. 图片上传
- **限制**：Webhook 不支持直接上传图片文件
- **方案**：图片需先上传到图床或对象存储，得到公网 URL 后用 `![](url)` 嵌入
- **替代**：引导用户在 flomo App 内手动粘贴图片

### 5. 标签格式错误
- **错误**：`# 阅读`（# 后有空格）、`#阅读 认知`（标签内空格会被截断）
- **正确**：`#阅读/认知觉醒`、`#读书笔记-认知觉醒`

### 6. 内容为空或超长
- **空内容**：`{"content":""}` 会被拒绝，写入前确认 content 非空
- **超长**：单条建议 < 5000 字，超长时拆分为多条续写

### 7. 读取已有笔记
- **限制**：Webhook 只写不读，无法通过 API 查询历史笔记
- **替代**：
  - 用本地标签索引 `~/.ethan/.cache/flomo-tags.txt` 查询标签列表
  - 引导用户打开 flomo App 查看历史
  - Agent 可在内存中维护近期写入的笔记摘要（每次写入后简短记录），便于用户追问"刚才记了什么"

### 8. 多条笔记合并
- **错误**：用 `---` 或 `***` 分隔多条笔记放在一次 POST
- **正确**：每条笔记单独 POST，确保每条都有独立的时间戳和标签
- **例外**：如果是同一主题的连续思考，可以合并为一条带小标题的笔记

---

## 关键纪律

- **API Key 从 shell 环境变量 `$FLOMO_WEBHOOK_KEY` 获取**，URL 拼接成 `https://flomoapp.com/iwh/$FLOMO_WEBHOOK_KEY/`，不要手写在请求 body 里
- **Webhook 只支持写入**，不要尝试用 GET 读取笔记或标签列表
- **标签置底**：标签统一放在 content 末尾，不要放开头
- **多级标签用 `/`**：`#阅读/认知觉醒`，单级标签作为状态：`#未完成`
- **写入前查本地索引**：避免重复造标签，先 `file_read ~/.ethan/.cache/flomo-tags.txt`
- **写入后更新索引**：用到新标签时 `file_write` 追加到索引末尾
- **批量写入间隔 ≥100ms**：避免触发频率限制
- **失败时展示 raw response**：不要编造成功，把 `{"code":...,"msg":...}` 原样反馈给用户
- **续写而非编辑**：用户说"追加到上一条"时，用相同标签 + 引用前文关键词写新笔记，明确告知用户这是"续写卡片"而非原地编辑
- **图片用 URL 嵌入**：`![](https://...)`，不支持本地文件上传

activate_tools: shell, file_write, file_read
