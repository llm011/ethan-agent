# 小红书 CLI 详细使用指南

所有命令基于 `uv run scripts/cli.py`。

## 1. 认证管理 (Authentication)

| 子命令 | 参数 | 说明 |
| :--- | :--- | :--- |
| `check-login` | 无 | 检查当前 Cookie 是否有效 |
| `get-qrcode` | 无 | 获取登录二维码 Data URL |
| `wait-login` | 无 | 阻塞等待扫码完成 |
| `send-code` | `--phone <号码>` | 发送短信验证码 |
| `verify-code` | `--code <验证码>` | 提交验证码登录 |
| `delete-cookies` | `[--account <名>]` | 清除本地登录态 |

## 2. 内容探索 (Exploration)

| 子命令 | 参数 | 说明 |
| :--- | :--- | :--- |
| `list-feeds` | 无 | 获取首页推荐 |
| `search-feeds` | `--keyword <词> [--sort-by <排序>]` | 搜索笔记 |
| `get-feed-detail` | `--feed-id <ID> --xsec-token <Token>` | 获取正文与评论 |
| `user-profile` | `--user-id <ID> --xsec-token <Token>` | 获查看用户资料 |

**搜索筛选器 (`--sort-by`)**: 综合、最新、最多点赞、最多评论、最多收藏。

## 3. 内容发布 (Publication)

| 子命令 | 参数 | 说明 |
| :--- | :--- | :--- |
| `fill-publish` | `--title-file <路径> --content-file <路径> --images <绝对路径/URL>` | 填装图文（不发布） |
| `click-publish` | 无 | 点击当前页面的发布按钮 |
| `save-draft` | 无 | 保存为草稿 |
| `publish` | `--title-file <路径> --content-file <路径> --images <绝对路径/URL>` | 一步到位发布图文 |
| `publish-video`| `--title-file <路径> --content-file <路径> --video <绝对路径>` | 一步到位发布视频 |

## 4. 长文模式 (Long Article)

1. `long-article`: 填写内容并进入排版页。
2. `select-template --name <模板名>`: 选择排版样式。
3. `next-step --content-file <摘要路径>`: 进入发布页填写描述。
4. `click-publish`: 确认发布。

---

## 全局参数

- `--headless`: 使用无头模式运行 Chrome（未登录时会自动降级）。
- `--account <name>`: 使用特定账号隔离。
- `--host/--port`: 连接远程 CDP 调试地址。
