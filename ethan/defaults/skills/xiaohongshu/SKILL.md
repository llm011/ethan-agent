---
name: xiaohongshu
title: 小红书自动化
description: |
  小红书自动化技能。通过 Ethan 浏览器工具操作小红书：搜索笔记、查看详情、发布内容、社交互动。
  使用 eval JS 直接提取数据，搜索用 URL 直跳，详情必须从搜索页点击进入（xsec_token 反爬）。
version: 2.1.0
author: Ethan
platforms: [linux, macos]
trigger:
  - 小红书
  - xiaohongshu
  - 红薯
  - xhs
  - 在小红书搜
  - 小红书找
  - 发小红书
  - 小红书发布
  - 小红书登录
  - 小红书点赞
  - 小红书评论
  - 小红书收藏
---

# 小红书自动化

通过 Ethan 浏览器工具（browser_session / browser_tab / browser_page）操作小红书。核心原则：
- **eval JS 提取数据**：不用 snapshot（DOM 复杂、ref 易 detach），直接执行 JS 提取结构化数据
- **搜索用 URL 直跳**：搜索用拼 URL 跳转，不打开首页再输入
- **详情必须点击进入**：小红书有 xsec_token 反爬，直接打开帖子 URL 会 404，必须在搜索/列表页通过 JS click 卡片进入
- **操作间隔**：每步之间 wait 2-3 秒，避免反爬
- **禁用 snapshot**：不要用 `action=snapshot`，只用 `action=eval` 执行 JS

## 前置条件

- Chrome 中已登录小红书（未登录时搜索受限）
- 浏览器工具可用（需先 `browser_session` action=attach_current）

## 意图路由

根据用户意图读取对应 reference 获取详细操作步骤：

| 意图 | 对应 reference |
|------|----------------|
| 搜索笔记、查看详情、首页推荐、用户主页 | `references/xhs-explore.md` |
| 发布图文、视频 | `references/xhs-publish.md` |
| 评论、回复、点赞、收藏 | `references/xhs-interact.md` |
| 竞品分析、热点追踪、批量运营 | `references/xhs-content-ops.md` |

## 核心操作速查

### 搜索笔记（5 步）
1. `browser_session` action=attach_current
2. `browser_tab` action=open → `https://www.xiaohongshu.com/search_result?keyword={encodeURIComponent(关键词)}&source=web_search_source_normal`
3. `browser_page` action=wait, ms=3000
4. `browser_page` action=eval → JS 提取搜索结果（标题、链接、作者、点赞数）
5. 返回结构化结果

### 查看详情（从搜索页点击进入，5 步）
⚠️ **绝对不能直接 browser_tab open 帖子链接**（会被 xsec_token 反爬拦截到 404）。

1. 确保当前在搜索结果页
2. `browser_page` action=eval → JS 点击目标卡片（按 index 或标题匹配）
3. `browser_page` action=wait, ms=3000
4. `browser_page` action=eval → JS 提取正文/图片/标签/评论
5. 查看完毕后 `browser_page` action=eval → `window.history.back()` 返回搜索页

### 点赞/收藏（3 步）
1. 在详情页 `browser_page` action=eval → JS 找到按钮并 click
2. `browser_page` action=wait, ms=1000
3. 确认状态变化

## 全局约束

- **禁止 snapshot**：不要用 `action=snapshot`，DOM 太复杂且 ref 会 detach
- **禁止直接打开帖子 URL**：小红书 xsec_token 反爬，必须从列表页点击进入
- **搜索可以 URL 直跳**：搜索页不受 xsec_token 限制
- 图片懒加载：优先取 `img.src`，其次 `data-src`
- 出现验证码时用 `browser_page` action=screenshot 截图给用户
- 连续访问 3-4 篇后插入 10-20 秒长等待，避免触发验证
- 创建浏览器会话时用 `browser_session` action=attach_current（连接已有 Chrome），不要用 action=create
