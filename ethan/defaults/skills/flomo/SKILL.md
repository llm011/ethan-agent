---
name: flomo
trigger: flomo|浮墨|浮墨笔记|flomoapp|记灵感|灵感记录|卡片笔记|碎片笔记|快速记一下|随手记|闪念|闪念笔记
description: flomo 浮墨笔记助手 — 通过私有 API 读取/搜索/写入/编辑笔记，或通过 Webhook 写入。适合碎片化快速记录；长笔记/知识管理用 getnote。
---

# flomo Skill

## 适用边界

**flomo（本技能）**：短笔记、灵感、闪念、碎片化快速记录。**仅在用户点名 flomo/浮墨，或语境明确是"记个灵感/闪念/卡片"时才用**。

- 用户只说"记一下/存一下/我的笔记"等泛化词 → **默认走内置 `knowledge_*`**（系统知识库），不要默认跳到本技能
- 收藏外部文章/视频/链接 → **走 getnote**
- 用户明确提到 flomo / 浮墨，或语境是"记个灵感/闪念/卡片" → **走本技能**

---

## 工具概览

本技能通过以下内置工具操作 flomo，**无需浏览器自动化**：

| 工具 | 功能 | 数据通道 | 前置条件 |
|------|------|---------|---------|
| `flomo_query` | 搜索/查询笔记 | flomo 私有 API | 客户端已登录 |
| `flomo_tags` | 标签列表 + 频率 | flomo 私有 API | 客户端已登录 |
| `flomo_create` | 创建笔记 | flomo 私有 API | 客户端已登录 |
| `flomo_edit` | 编辑已有笔记 | flomo 私有 API | 客户端已登录 |
| `flomo_write` | Webhook 写入 | Webhook iwh API | `set_secret("flomo_webhook_key", ...)` |

### 原理

- **私有 API**：直接调用 `flomoapp.com/api/v1`，从 flomo 桌面客户端的 `config.json` 提取 `access_token`，用 MD5 签名 + Bearer 鉴权。这是 flomo 网页版和客户端共用的后端 API。
- **Webhook**：POST 到 `flomoapp.com/iwh/{key}/`，仅支持写入，不需要客户端登录。
- **跨平台**：macOS（沙盒版 + 非沙盒版）和 Windows 均支持，自动检测客户端数据目录。

---

## 读取/搜索笔记

```
flomo_query(keyword="关键词", tag="闪念/思考", days=7, limit=20)
```

参数：
- `keyword`：关键词搜索（不区分大小写）
- `tag`：按标签过滤（如 `闪念/思考`）
- `days`：最近 N 天
- `start_date` / `end_date`：日期范围（YYYY-MM-DD）
- `limit`：最大结果数（默认 20）

返回每条笔记的 slug、URL、标签和内容摘要。

---

## 读取标签列表

```
flomo_tags(prefix="闪念", limit=50)
```

参数：
- `prefix`：按前缀过滤（如 `闪念`）
- `days`：仅统计最近 N 天的标签
- `limit`：最大返回数（默认 50）

**写入笔记前建议先调用 `flomo_tags` 确认可用标签，优先复用存量标签。**

---

## 写入笔记

### 方式 1：私有 API 创建（推荐）

```
flomo_create(content="笔记内容 #标签")
```

- 需本机 flomo 客户端已登录
- 返回完整 memo 对象（slug + URL + tags + created_at）
- 支持纯文本，`#标签` 放末尾

### 方式 2：Webhook 写入（备选）

```
flomo_write(content="笔记内容 #标签")
```

- 需先配置 webhook key：`set_secret(name="flomo_webhook_key", value="<key>")`
- 获取 key：flomo → 设置 → API 及第三方工具 → Webhook URL
- 仅支持写入，不支持读取
- 频率限制：约 10 条/分钟

---

## 编辑笔记

```
flomo_edit(slug="NDA5MDA2OTY", content="更新后的内容 #标签")
```

- `slug` 可传 slug 或完整 memo URL（`https://v.flomoapp.com/mine/?memo_id=...`）
- 保留原 memo 的图片和置顶状态，仅更新文本
- 需本机 flomo 客户端已登录

---

## 标签规范

> 用户 flomo 现有 400+ 标签，加笔记时**优先复用存量标签**。

### 五大主框架类目

| 类目 | 含义 | 常见子标签 |
|------|------|-----------|
| `#领域` | 知识 / 认知领域 | 领域/财富、领域/成长、领域/思维模型、领域/心理学、领域/写作 |
| `#项目` | 进行中的项目 | 项目/AI、项目/写作、项目/时间管理、项目/如何阅读 |
| `#输入` | 外部输入源 / 素材 | 输入/书、输入/电影、输入/得到、输入/帆书、输入/网络 |
| `#闪念` | 突发灵感、临时收集 | 闪念/思考、闪念/收集、闪念/生活、闪念/微信文章 |
| `#永久` | 长期沉淀的精华笔记 | 永久/思考、永久/素材、永久/名词、永久/沟通 |

### 格式纪律
- 标签以 `#` 开头、紧跟文字、无空格（`#阅读` ✓，`# 阅读` ✗）
- 多级用 `/`（`#阅读/认知觉醒`），深度以 2-3 层为主
- **标签置底**：统一放在 content 末尾，多标签空格分隔
- **不确定时先 `flomo_tags` 确认**，仅有真正新领域/新项目时才新建

---

## 前置条件

### 私有 API 工具（query / tags / create / edit）
- 本机已安装 flomo 桌面客户端（macOS 或 Windows）
- 客户端已登录（token 自动从 `config.json` 提取，无需手动配置）

### Webhook 工具（write）
- 用户提供 webhook key，通过 `set_secret(name="flomo_webhook_key", value="<key>")` 保存
- 不依赖客户端登录态，适合无客户端的环境

---

## 浏览器兜底（API 工具不可用时）

当本机未安装 flomo 客户端、或 token 提取失败时，回退到浏览器自动化。

### 浏览器前置条件
- Chrome 已安装 ethan 扩展，用 **Web UI Token** 连上服务（默认 8910）
- 本机浏览器已登录 flomo（`https://v.flomoapp.com/mine/`）

### ⚠️ OOM 红线
flomo 首页 DOM 极重（侧边栏 400+ 标签），**所有操作一律用 `browser_page eval` 跑紧凑 JS、只回传小 JSON，绝不 snapshot / 整页截图**。

### 读取笔记（浏览器）
```javascript
(async () => {
  const N = 5;
  const cards = [...document.querySelectorAll('.display.showMemoInsight')];
  const data = cards.slice(0, N).map(card => ({
    text: (card.innerText || '').trim().slice(0, 2000),
    images: [...card.querySelectorAll('img[src*="static.flomoapp.com"]')].map(i => i.src)
  }));
  return JSON.stringify(data);
})()
```

### 写入笔记（浏览器）
1. `browser_tab` 打开 `https://v.flomoapp.com/mine/`
2. `browser_page fill` 写入 `div.tiptap.ProseMirror`
3. `browser_page click` 点 `svg.saveBtn`
4. 等 1~2 秒确认已出现在列表顶部

activate_tools: flomo_query, flomo_tags, flomo_create, flomo_edit, flomo_write, set_secret
