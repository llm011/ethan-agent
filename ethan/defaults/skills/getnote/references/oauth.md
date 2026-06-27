## 配置方式

### 方式一：直接配置 API Key（推荐）

只需提供两个值：
- `GETNOTE_API_KEY` = `gk_live_xxx`
- `GETNOTE_CLIENT_ID` = `cli_xxx`

把它们写入 `~/.ethan/.secrets/getnote.env`（每行 `KEY="value"`）：
```
GETNOTE_API_KEY="gk_live_xxx"
GETNOTE_CLIENT_ID="cli_xxx"
```
该文件权限应为 0600，永远不会进入代码仓库或模型上下文。配置后跑 shell 的 curl 时，`$GETNOTE_API_KEY` 会自动注入子进程环境，无需 get_secret。

### 方式二：OAuth 登录

需要先安装 CLI：
```bash
npm install -g @getnote/cli
getnote auth login
```

---

## 如何获取 API Key

1. 访问：https://www.biji.com/settings/api
2. 创建应用，获取 Client ID
3. 获取 API Key

或参考：https://github.com/iswalle/getnote-cli