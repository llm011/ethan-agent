---
name: xiaohongshu
title: 小红书自动化
description: |
  小红书自动化技能。通过 Ethan 浏览器工具操作小红书：搜索笔记、查看详情、发布内容、社交互动。
  使用 eval JS 直接提取数据，搜索用 URL 直跳，详情必须从搜索页点击进入（xsec_token 反爬）。
version: 2.2.0
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

## Python CDP 引擎（可选后端）

本技能额外内置一个基于 Python + Chrome DevTools Protocol 的独立 CLI 工程位于 `scripts/cdp_engine/`。它通过直连 CDP 调试端口操作 Chrome，不依赖 Ethan 浏览器工具，可在 headless、批量、远程场景下使用。

### 何时用 CDP 引擎

- **批量/高速场景**：一次拉几十上百条搜索结果、批量下载封面图、批量发布多篇
- **headless / 服务器端**：无 GUI 环境（如 macmini 后台任务），脚本无人值守
- **需要稳定 JSON 输出**：CDP 引擎所有子命令统一返回结构化 JSON，便于后续脚本串联
- **远程 CDP**：可通过 `--host/--port` 连接远程已调试 Chrome

### 何时用浏览器工具（默认后端）

- **已登录 Chrome**：用户当前 Chrome 已扫码登录小红书，复用 session 即可
- **单次操作 / 可视化交互**：发布笔记时需人工确认内容、查看页面状态
- **快速验证**：搜索一两篇、看个详情、给一条评论点赞
- **需要截图给用户**：`browser_page` action=screenshot

### 调用方式

所有 CDP 引擎子命令均通过 `uv` 运行，工作目录为本 skill 根目录：

```bash
uv run --project scripts/cdp_engine scripts/cdp_engine/cli.py <subcommand> [options]
```

首次运行 `uv` 会自动按 `scripts/cdp_engine/pyproject.toml`（依赖 `requests>=2.28.0`、`websockets>=12.0`）创建隔离环境，无需手动 `pip install`。

### 子命令速查

| 场景 | 子命令 |
|------|--------|
| 登录态检查 | `check-login` |
| 扫码登录 | `get-qrcode` → 展示 → `wait-login` |
| 短信登录 | `send-code --phone <号码>` → `verify-code --code <验证码>` |
| 首页推荐 | `list-feeds` |
| 搜索笔记 | `search-feeds --keyword <词> [--sort-by 最多点赞/最新/最多评论/最多收藏]` |
| 笔记详情 | `get-feed-detail --feed-id <ID> --xsec-token <Token>` |
| 用户资料 | `user-profile --user-id <ID> --xsec-token <Token>` |
| 填装发布 | `fill-publish --title-file <路径> --content-file <路径> --images <绝对路径/URL>` |
| 一键发布 | `publish --title-file <路径> --content-file <路径> --images <绝对路径/URL>` |
| 视频发布 | `publish-video --title-file <路径> --content-file <路径> --video <绝对路径>` |
| 确认发布 | `click-publish` |
| 保存草稿 | `save-draft` |

完整参数表见 `references/cli-usage.md`。

### 全局参数

- `--headless`：使用无头 Chrome（未登录会自动降级到有头模式以便扫码）
- `--account <name>`：多账号隔离
- `--host/--port`：连接远程 CDP 调试地址

### 注意

- CDP 引擎独立维护登录态（cookies 存于本地文件），与浏览器工具的 Chrome session **互不相通**，首次使用需独立扫码
- xsec_token 反爬对 CDP 引擎同样有效：`get-feed-detail` 必须传入从 `search-feeds` 返回的 token，不能凭空捏造
- 发布流程遵循同一铁律：标题 ≤ 20 字、图片/视频路径必须绝对路径
- 若本机未装 `uv`，可参考 https://docs.astral.sh/uv/ 安装

## 全局约束

- **禁止 snapshot**：不要用 `action=snapshot`，DOM 太复杂且 ref 会 detach
- **禁止直接打开帖子 URL**：小红书 xsec_token 反爬，必须从列表页点击进入
- **搜索可以 URL 直跳**：搜索页不受 xsec_token 限制
- 图片懒加载：优先取 `img.src`，其次 `data-src`
- 出现验证码时用 `browser_page` action=screenshot 截图给用户
- 连续访问 3-4 篇后插入 10-20 秒长等待，避免触发验证
- 创建浏览器会话时用 `browser_session` action=attach_current（连接已有 Chrome），不要用 action=create
