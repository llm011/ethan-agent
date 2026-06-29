---
name: dev-browser
trigger: "复杂网页流程|网页脚本|playwright|批量抓取|多步网页操作|网页自动化脚本|遍历页面|循环抓取|dev-browser|browser script"
description: "用 dev-browser 跑沙箱 JavaScript 脚本操控浏览器，拿到完整 Playwright API（goto/click/locator/evaluate/循环/条件）。适合一个脚本搞定的复杂多步流程、批量抓取、需要循环或判断的网页任务。简单的单步操作请优先用 agent-browser。需要把多页数据聚合成结构化结果时尤其合适。"
metadata:
  requires:
    bins: ["dev-browser"]
---

# dev-browser

进阶浏览器技能。把一段 **JavaScript** 喂给 `dev-browser`，它在 QuickJS WASM 沙箱里跑，给你**完整 Playwright Page API**。

**什么时候用它而不是 agent-browser：** 任务需要循环、条件判断、把多页数据聚合成一个结构化结果、或一次脚本完成多步操作。**简单的单步操作（开个页面、点一下、读个文字）请用 `agent-browser`，更省 token。**

## 前置检查（第一次用先做）

```bash
dev-browser status
```

- **守护进程正常** → 直接用。
- **command not found** → 装：
  ```bash
  brew install dev-browser      # macOS 首选
  npm install -g dev-browser    # 跨平台
  ```
- **报缺浏览器 / 第一次用** → 装 Chromium（只需一次）：
  ```bash
  dev-browser install
  ```

## 核心套路

用 heredoc 把脚本喂进去。脚本里有预连接好的 `browser` 全局：

```bash
dev-browser <<'EOF'
const page = await browser.getPage("main");
await page.goto("https://example.com", { waitUntil: "domcontentloaded" });
console.log(await page.title());
EOF
```

- `browser.getPage("main")`：拿/建一个命名页面，**同名页面在多次脚本调用间常驻**（导航一次，后续脚本接着用）。
- 返回的是**完整 Playwright Page**：`goto` / `click` / `fill` / `locator` / `evaluate` / `screenshot` 全都有 → https://playwright.dev/docs/api/class-page
- `console.log` 的内容就是回到 agent 的输出。**只 log 你需要的，别把整个 DOM 打出来**——这点要靠你自己控制 token。

## 沙箱限制（重要）

脚本在 QuickJS 里跑，**不是 Node.js**。以下都**没有**：`require/import`、`process`、`fs/path/os`、`fetch/WebSocket`、`__dirname`。

能用的全局：

| 全局 | 用途 |
|------|------|
| `browser` | 预连接的浏览器句柄 |
| `console.log/warn/error/info` | 输出（log/info → stdout，warn/error → stderr） |
| `setTimeout / clearTimeout` | 定时器 |
| `await saveScreenshot(buf, name)` | 存截图到 `~/.dev-browser/tmp/<name>`，返回路径 |
| `await writeFile(name, data)` | 写文件到 tmp，返回路径 |
| `await readFile(name)` | 从 tmp 读文件 |

文件 I/O 全部 `await`，且只能在 `~/.dev-browser/tmp/` 内，逃不出去。

## browser API

| 方法 | 说明 |
|------|------|
| `browser.getPage(name)` | 按名拿/建页面（跨脚本常驻），或用 `listPages()` 里的 targetId 接已有 tab |
| `browser.newPage()` | 匿名页面，脚本结束自动清理 |
| `browser.listPages()` | 列所有 tab：`[{id, url, title, name}]` |
| `browser.closePage(name)` | 关闭命名页面 |

## 复用登录态

连你**正在跑的 Chrome**（带现成登录态）：

```bash
# 先让 Chrome 开调试端口：chrome --remote-debugging-port=9222
dev-browser --connect <<'EOF'
const tabs = await browser.listPages();
console.log(JSON.stringify(tabs, null, 2));
EOF

# 或指定 CDP 端点
dev-browser --connect http://localhost:9222 <<'EOF' ...
```

命名 browser 实例隔离状态：`dev-browser --browser my-project <<'EOF' ...`（该实例的命名页面常驻）。

## 典型场景

**批量抓取并聚合成 JSON：**
```bash
dev-browser <<'EOF'
const page = await browser.getPage("main");
const results = [];
for (const id of ["a", "b", "c"]) {
  await page.goto(`https://example.com/item/${id}`, { waitUntil: "domcontentloaded" });
  results.push({ id, title: await page.title(), price: await page.locator(".price").textContent() });
}
console.log(JSON.stringify(results, null, 2));   // 只回聚合结果，省 token
EOF
```

**多步表单 + 截图存盘：**
```bash
dev-browser <<'EOF'
const page = await browser.getPage("main");
await page.goto("https://example.com/login", { waitUntil: "domcontentloaded" });
await page.fill("#user", "alice");
await page.fill("#pass", "secret");
await page.click("button[type=submit]");
await page.waitForLoadState("networkidle");
const path = await saveScreenshot(await page.screenshot({ fullPage: true }), "after-login.png");
console.log("saved:", path);
EOF
```

## 注意

- 沙箱不是 Node，别在脚本里 `require`/`fetch`/碰 `fs`——会直接报错。
- 慢页面记得 `await page.waitForLoadState("networkidle")`。
- 密码别明文回显到给用户的回复里。
- 用完不用每次关，守护进程和命名页面会留着；要清理用 `dev-browser stop`。
