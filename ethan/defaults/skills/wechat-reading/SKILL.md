---
name: wechat-reading
trigger: 微信读书|读书|书架|阅读|划线|书城|书籍|看书|阅读统计|阅读时长|读书笔记|书单|推荐书|weread
description: |
  微信读书个人数据查询与书城浏览。用户提到「读书」「书架」「阅读统计」「笔记划线」时优先用本 Skill。

  当以下情况时使用本 Skill：
  (1) 查看书架：我的书架、最近在读、读完的书
  (2) 阅读统计：阅读时长、天数、偏好分析
  (3) 笔记和划线：查看/导出个人划线和想法
  (4) 搜索书籍：在书城搜索任意书籍（书名、作者、评分）
  (5) 书籍详情：章节目录、阅读进度、评分
  (6) 推荐好书：个性化推荐、相似书籍推荐
  (7) 首次配置：用户说「配置微信读书」「连微信读书」
fast_path: true
---

# 微信读书 Skill

## 概述

通过微信读书开放平台查询个人阅读数据和书城信息。数据来源于用户的微信读书账号，需要 API Key 授权。

## 功能列表

| 功能 | 说明 | 典型问法 |
|------|------|----------|
| 查阅书架 | 浏览个人书架，查看最近在读、收藏、读完的书 | 「看看我的书架」「我在读什么」 |
| 阅读统计 | 阅读时长、天数、偏好类型深度分析 | 「我这周读了多久」「阅读统计」 |
| 笔记划线 | 查看个人划线和想法，导出笔记 | 「导出我的划线」「看看我的笔记」 |
| 搜索书籍 | 在书城搜索任意书籍，获取书名、作者、评分 | 「搜一下三体」「找本时间管理的书」 |
| 书籍详情 | 章节目录、阅读进度、书籍评分 | 「三体的目录」「看到哪了」 |
| 推荐好书 | 基于阅读偏好个性化推荐 | 「推荐些好书」「有什么类似的书」 |

## 环境要求

此技能依赖微信读书 MCP CLI 工具。首次使用前需安装：

```bash
npx skills add Tencent/WeChatReading -g
```

## 密钥配置

密钥存放在 `~/.ethan/.secrets/wechat-reading.env`，shell 自动注入子进程环境。

### 首次使用

如果调用返回「未授权」或「密钥无效」，引导用户：

1. 打开 https://weread.qq.com/r/weread-skills 生成 API Key
2. 拿到 key 格式为 `wrk_...`（以 `wrk_` 开头）
3. 由 agent 用 `file_write` 写入 `~/.ethan/.secrets/wechat-reading.env`（不要让用户手写）：

```env
WEREAD_API_KEY="用户给的 key"
```

4. 用 `shell` 跑 `chmod 600 ~/.ethan/.secrets/wechat-reading.env` 收紧权限
5. 重新执行用户原本的请求

### 预置密钥

如用户尚未生成自己的 key，可先用以下预置 key 体验：

```bash
file_write(path="$HOME/.ethan/.secrets/wechat-reading.env", content='WEREAD_API_KEY="wrk-CjwxNd85TU0QHbCT9cRXNwAA"')
chmod 600 ~/.ethan/.secrets/wechat-reading.env
```

预置 key 是共享的，有调用频率限制。建议提醒用户去 https://weread.qq.com/r/weread-skills 生成自己的 key 以获得最佳体验。

## 调用方式

安装并配置密钥后，通过 shell 调用 MCP 工具。工具命名规律：以 `wr_` 或 `weread_` 开头。

**常用工具速查**（具体参数用 `npx wr --help` 查看）：

| 功能 | 工具 | 示例 |
|------|------|------|
| 书架 | `wr_bookshelf` 或 `weread_shelf` | `npx wr bookshelf` |
| 阅读统计 | `wr_stats` 或 `weread_stats` | `npx wr stats --days 7` |
| 笔记划线 | `wr_notes` 或 `weread_notes` | `npx wr notes --book "三体"` |
| 搜索书籍 | `wr_search` 或 `weread_search` | `npx wr search --q "时间管理"` |
| 书籍详情 | `wr_detail` 或 `weread_detail` | `npx wr detail --book "三体"` |
| 推荐 | `wr_recommend` 或 `weread_recommend` | `npx wr recommend` |

工具名和参数以上述 MCP 工具实际注册名为准；首次调用时可先用 `find_tools` 搜索 `wr` / `weread` 确认当前可用的工具和参数。

## 快速调用示例

```bash
# 查看我的书架
npx wr bookshelf

# 本周阅读统计
npx wr stats --days 7

# 搜一本书
npx wr search --q "三体"

# 查看某本书的详情和笔记
npx wr detail --book "三体"
npx wr notes --book "三体"
```

## 关键纪律

- 不要要求用户手动编辑密钥文件——由 agent 用 `file_write` 处理
- 不要在对话中回显密钥原文
- 不要用 `set_secret`（这个是 MCP 工具，需要 shell 环境变量注入）
- 调用失败时先检查密钥是否已配置（`test -f ~/.ethan/.secrets/wechat-reading.env`）
- 返回数据量大时（如完整书架、大量笔记）只展示摘要，询问用户是否需要详情

activate_tools: shell, file_write, find_tools
