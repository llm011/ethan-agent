---
name: use-browser
version: 0.1.0
description: "通过 browser_session / browser_tab / browser_page 三个工具操作本机 Chrome:创建/接管浏览器 session、管理 tab、执行页面 snapshot/click/fill/type/screenshot/eval。当用户要求操作浏览器、做网页自动化、browser_use/agent-browser 风格页面操作、或需要在本机真实 Chrome 中点击输入时触发。"
---

# 浏览器控制使用规则

本技能指导你用 `browser_session` / `browser_tab` / `browser_page` 三个工具操作 ethan server 所在机器上的真实 Chrome(需已安装并连接 Ethan Browser 扩展)。

## 适用场景

- 用户要求操作浏览器、做网页自动化:创建 session、观察页面、点击、输入、截图、执行 JS。
- 需要操作本机 Chrome 中的 tab、tab group、当前 active tab。

不要用它替代普通网页信息检索;只需查公开网页信息时优先用 web_search / web_fetch。

## 核心原则

1. `session` 是浏览器操作空间,一个 session 对应一个 Chrome Tab Group。
2. `browser_page` 默认作用于该 session 的 active tab;要换目标 tab 先用 `browser_tab` action=activate。
3. `snapshot` 生成的 ref 只对最近一次页面上下文可靠;页面 reload/navigation 后必须重新 snapshot。
4. 默认用结构化 ref 操作;只有 ref 不可用或需要 GUI 级交互时才用 mouse 坐标操作。
5. 坐标是 viewport CSS pixel,不是屏幕绝对坐标。
6. `eval` 权限很高,只在任务需要时使用,不要对不可信页面执行无关脚本。
7. 工具输出是 snake_case JSON。
8. 授权是会话级的:本对话第一次调用任意 browser 工具会请求一次授权,批准后本对话后续操作(含 eval)不再询问。

## 推荐任务流程

### 打开新页面并操作

```
browser_session(action="create", url="https://www.example.com", title="任务")
```

记录返回的 session_id,后续操作用它:

```
browser_page(action="snapshot", session=SID, interactive=true, compact=true, depth=3, format="text")
browser_page(action="click", session=SID, ref="e1")
browser_page(action="fill", session=SID, ref="e2", text="hello")
browser_page(action="screenshot", session=SID)
```

任务结束:默认 release(放掉控制权、保留用户页面),仅在用户明确要求关闭时才 close:

```
browser_session(action="release", session=SID)   # 保留 tab
browser_session(action="close", session=SID)      # 关闭整个 tab group
```

### 接管当前 Chrome tab

用户已在 Chrome 打开目标页面时:

```
browser_session(action="attach_current", title="任务")
```

接管指定 tab:

```
browser_tab(action="user_list")
browser_tab(action="attach", session=SID, tab=TAB_ID)
```

### 多 tab 操作

```
browser_tab(action="open", session=SID, url="https://example.com")
browser_tab(action="list", session=SID)
browser_tab(action="active", session=SID)
browser_tab(action="activate", session=SID, tab=TAB_ID)
browser_tab(action="close", session=SID, tab=TAB_ID)
```

## Snapshot 策略

不要默认 dump 大页面。优先小窗口观察:

```
browser_page(action="snapshot", session=SID, interactive=true, compact=true, depth=3, format="text")
```

常用选项:

- `interactive=true`:只看交互元素,推荐默认。
- `compact=true`:压缩空结构节点。
- `depth=<n>`:限制树深度。
- `selector="#main"`:限定 DOM 子树。
- `cursor=true`:补充 cursor:pointer / onclick / tabindex 元素。
- `urls=true`:需要链接 href 时开启。
- `format="text"`:适合阅读;默认 json 适合解析。

输出过大时按顺序收缩:开 interactive、开 compact、降低 depth、用 selector 限定区域。快照过大会被自动截断并提示缩小范围。

## Page 命令速查

Ref 操作:click / fill / type / hover / select / scroll_into_view(都用 `ref`)。
键盘滚动鼠标:press(`key`) / scroll(`direction`,`pixels`) / mouse(`mouse_action`,`x`,`y`,`delta_x`,`delta_y`)。
读取:get(`what` = title/url/text/value/html/box,后四种需 `ref`)。
截图等待执行:screenshot / wait(`ms` 或 `load`) / eval(`script`)。

screenshot 返回本地文件路径,可直接在飞书发图或在 Web 渲染。

## 常见错误处理

- 浏览器扩展未连接:提示用户安装并启用 Ethan Browser 扩展,在扩展 options 里填好 server 地址和 token。
- ref not found / 浏览器断连:通常是页面跳转或刷新、或扩展重连。重新 snapshot 后重试。
