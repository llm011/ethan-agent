---
name: agent-browser
trigger: "抓取网页|爬网页|网页自动化脚本|批量抓取|多步网页流程|遍历页面|agent-browser|browser script|scrape|automate web|登录网站|网页脚本"
description: "兜底浏览器技能：用 agent-browser CLI 操控内置独立 Chrome（自带 profile，与用户本机 Chrome 隔离）。打开网页、点击/填表、读取内容、截图、跑 JS。snapshot 输出极省 token（~300 vs 全 DOM 的 ~4000）。当 use-browser 不可用（未装扩展/server 不在本机）、需要隔离 profile、或做批量抓取/多步脚本时使用。日常浏览器操作优先用 use-browser。"
metadata:
  requires:
    bins: ["agent-browser"]
---

# agent-browser

**定位：兜底浏览器技能**。日常浏览器操作（点击、填表、截图、接管当前 tab）优先用 `use-browser`——它能复用用户本机 Chrome 的真实 cookie 和登录态。只有以下情况才用本技能：

- 本机没装 Ethan Browser 扩展 / 扩展没连上
- server 不在本机（远程跑、没法连本机扩展）
- 需要一个**隔离的独立 profile**（不想动用户日常 Chrome、或要测干净登录流程）
- 批量抓取 / 多步网页脚本（agent-browser CLI 更适合写循环）

用 `agent-browser` 这个原生 CLI 操控内置独立 Chrome。守护进程在命令之间常驻，所以多条命令会复用同一个浏览器会话。

## 前置检查（第一次用先做）

```bash
agent-browser --version
```

- **能输出版本号** → 直接往下用。
- **command not found** → 装 CLI（任选其一）：
  ```bash
  brew install agent-browser      # macOS 首选
  npm install -g agent-browser    # 跨平台
  ```
- **报找不到浏览器 / 第一次用** → 下载内置 Chrome（只需一次）：
  ```bash
  agent-browser install
  ```

装好后告诉用户「浏览器能力已就绪」，再继续。

## 核心套路（AI 必须按这个来）

不要凭空猜选择器。**先 snapshot 拿 `@ref`，再用 `@ref` 操作**：

```bash
agent-browser open example.com          # 1. 打开
agent-browser snapshot -i               # 2. 拿可交互元素的 @e1 @e2 ... 引用
agent-browser fill @e3 "user@x.com"     # 3. 用引用填表/点击
agent-browser click @e5
agent-browser get text                  # 4. 读页面文字
agent-browser close                     # 5. 用完关掉
```

`snapshot -i` 只输出可交互元素，最省 token；要读正文用 `agent-browser get text`。

## 命令速查

| 用途 | 命令 |
|------|------|
| 打开/导航 | `open <url>`、`back`、`forward`、`reload` |
| 看页面结构 | `snapshot -i`（仅交互元素）、`snapshot -c`（精简）、`snapshot -d <n>`（限深度） |
| 点击 | `click <@ref\|css>`、`dblclick`、`hover` |
| 输入 | `fill <sel> <text>`（清空再填）、`type <sel> <text>`、`press <key>`（如 `Enter`、`Control+a`） |
| 选择/勾选 | `select <sel> <val>`、`check <sel>`、`uncheck <sel>` |
| 按语义找元素 | `find role button click --name 提交`、`find text "登录" click` |
| 读取信息 | `get text [sel]`、`get html [sel]`、`get value <sel>`、`get url`、`get title`、`get attr <name> <sel>` |
| 判断状态 | `is visible <sel>`、`is enabled <sel>`、`is checked <sel>` |
| 等待 | `wait <sel>`、`wait <ms>`、`wait --load networkidle`（慢页面） |
| 滚动 | `scroll down [px]`、`scrollintoview <sel>` |
| 截图 | `screenshot [path]`、`screenshot --full`、`screenshot --annotate`（带编号标注，给视觉模型看） |
| 导出 PDF | `pdf <path>` |
| 跑 JS | `eval "<js>"` |
| 上传/下载 | `upload <sel> <files...>`、`download <sel> <path>` |
| 控制台/报错 | `console`、`errors` |
| 关闭 | `close` |

## 复用登录态（很重要）

默认每次是干净的无痕会话。要让网站记住登录，用持久 profile 或命名会话：

```bash
# 持久 profile：cookies / IndexedDB / 缓存都留着，下次还在
agent-browser --profile ~/.ethan/browser-profiles/default open mail.example.com

# 命名会话：自动存取 cookies + localStorage
agent-browser --session-name gmail open mail.example.com

# 复用用户已经开着的 Chrome（连它现成的登录态）
agent-browser --auto-connect snapshot
```

首次登录后，同一个 `--profile` / `--session-name` 后续都免登录。建议把需要登录的站点固定用一个 profile 路径。

## 命令链式调用（省往返）

守护进程常驻，可以在一条 shell 里用 `&&` 串起来：

```bash
agent-browser open example.com && agent-browser wait --load networkidle && agent-browser snapshot -i
```

## 常见整活

**搜索并读结果：**
```bash
agent-browser open "https://www.google.com/search?q=关键词" && agent-browser wait --load networkidle && agent-browser get text
```

**登录某网站（先看表单长啥样）：**
```bash
agent-browser --session-name mysite open https://mysite.com/login && agent-browser snapshot -i
# 看到 @ref 后：
agent-browser fill @e1 "用户名" && agent-browser fill @e2 "密码" && agent-browser click @e3
```

**给页面截图给用户看：**
```bash
agent-browser open <url> && agent-browser wait --load networkidle && agent-browser screenshot /tmp/page.png --full
# 然后用 Read 工具打开 /tmp/page.png 看
```

## 注意

- 页面没加载完就 snapshot 会拿不到元素 → 加一句 `wait --load networkidle`。
- 涉及账号密码时，优先 `--session-name` 复用已登录态，避免反复输密码；密码别明文打印到回复里。
- 任务做完记得 `agent-browser close`，除非用户还要继续在同一会话上操作。
