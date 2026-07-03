---
name: use-browser
version: 0.2.1
trigger: "浏览器|打开网页|网页操作|自动填表|网页截图|点击页面|输入文本|操作我的浏览器|我的浏览器|本机 Chrome|浏览器 cookie|扩展工具|真实 tab|接管当前页面"
fast_path: true
description: "主浏览器技能：通过 browser_session / browser_tab / browser_page 三个工具操作本机 Chrome（需 Ethan Browser 扩展）。嵌入本机真实 Cookie，能操作用户已登录的浏览器、接管当前 tab、做 snapshot/click/fill/screenshot/eval。当用户要求操作浏览器、网页自动化、点击输入、或需要用到本机真实 Chrome（含登录态）时触发。兜底用 agent-browser。"
---

# 浏览器控制使用规则

本技能指导你用 `browser_session` / `browser_tab` / `browser_page` 三个工具操作 ethan server 所在机器上的真实 Chrome（需已安装并连接 Ethan Browser 扩展）。

## 适用场景

- 用户要求操作浏览器、做网页自动化：创建 session、观察页面、点击、输入、截图、执行 JS。
- 需要操作本机 Chrome 中的 tab、tab group、当前 active tab。
- **需要复用用户登录态/cookie**：直接接管用户已登录的 Chrome tab（`attach_current`），不必重新登录。

不要用它替代普通网页信息检索；只需查公开网页信息时优先用 web_search / web_fetch。

## 与 agent-browser 的分工

| | use-browser（本技能） | agent-browser |
|--|--|--|
| 浏览器 | 本机真实 Chrome（用户日常用的那个） | 内置独立 Chrome（自带 profile，与用户浏览器隔离） |
| 登录态/cookie | ✅ 复用用户真实 cookie，已登录的站直接操作 | 独立 profile，需自己登录或导入 |
| 接管当前 tab | ✅ `attach_current` 接管用户正在看的 tab | ❌ 只能自己 open |
| 依赖 | Ethan Browser 扩展 + 本机 Chrome | agent-browser CLI |
| 定位 | **主技能**——只要本机有扩展就用它 | **兜底**——扩展没装/不可用、或需要隔离环境时 |

**默认走本技能**。只有以下情况才退到 agent-browser：扩展未安装/未连接、需要隔离的独立 profile、或 server 不在本机（无法连扩展）。

## 核心原则

1. `session` 是浏览器操作空间，一个 session 对应一个 Chrome Tab Group。
2. `browser_page` 默认作用于该 session 的 active tab；要换目标 tab 先用 `browser_tab` action=activate。
3. `snapshot` 生成的 ref 只对最近一次页面上下文可靠；页面 reload/navigation 后必须重新 snapshot。
4. 默认用结构化 ref 操作；只有 ref 不可用或需要 GUI 级交互时才用 mouse 坐标操作。
5. 坐标是 viewport CSS pixel，不是屏幕绝对坐标。
6. `eval` 权限很高，只在任务需要时使用，不要对不可信页面执行无关脚本。
7. 工具输出是 snake_case JSON；交互操作（click/fill/type/press 等）的返回中含 `_step` 字段，表示当前会话累计操作步数。
8. 授权是会话级的：本对话第一次调用任意 browser 工具会请求一次授权，批准后本对话后续操作（含 eval）不再询问。

## 步骤预算

任务开始前先估算预期步数，在任务说明里写出来（如"预计 8 步完成"）。每次交互操作返回的 `_step` 字段是当前累计步数：

- **步数 ≥ 20**：进入收尾模式——只做必要的剩余步骤，不再探索新路径。
- **步数 ≥ 30**：立即停止，输出中间结论报告（已完成什么、剩余什么、建议下一步），不再继续操作。

复杂任务（登录+多步流程）预算可放宽到 40，但须在任务开始时明确说明。

## 失败重试策略

同一元素/操作连续失败的处理路径：

1. **第 1 次失败**：重新 snapshot，用新 ref 重试。
2. **第 2 次失败**：换策略——用 `selector` 缩小 snapshot 范围、或换 `eval` 方式操作，再试一次。
3. **第 3 次失败**：停止重试，上报 blocker：说明目标、已尝试方法、失败原因，让用户介入。

**绝不对同一操作重试超过 3 次。**

## 截图原则

截图（screenshot）开销大，严格限制使用：

- **任务最终验证时截一次**：需要向用户展示结果、或验证关键操作是否生效时。
- **真正无法用 snapshot 判断的视觉问题**：如样式渲染、图片加载、动画状态。
- 其他情况用 `snapshot` 或 `get` 替代，不要用截图观察页面状态。

## AX 树不稳定的兜底路径

当 ref not found 或元素定位失败时，按顺序尝试：

1. `selector` 缩小 snapshot 区域重新取 ref（如 `selector="#form"`）
2. `get action="html"` 读取目标区域 HTML，从中找稳定 selector
3. `eval` 直接操作 DOM（`document.querySelector(...).click()`）
4. 三种都失败则上报 blocker

## 推荐任务流程

### 打开新页面并操作

```
browser_session(action="create", url="https://www.example.com", title="任务")
```

记录返回的 session_id，后续操作用它：

```
browser_page(action="snapshot", session=SID, interactive=true, compact=true, depth=3, format="text")
browser_page(action="click", session=SID, ref="e1")
browser_page(action="fill", session=SID, ref="e2", text="hello")
```

任务结束：默认 release（放掉控制权、保留用户页面），仅在用户明确要求关闭时才 close：

```
browser_session(action="release", session=SID)   # 保留 tab
browser_session(action="close", session=SID)      # 关闭整个 tab group
```

### 接管当前 Chrome tab

用户已在 Chrome 打开目标页面时：

```
browser_session(action="attach_current", title="任务")
```

### 多 tab 操作

```
browser_tab(action="open", session=SID, url="https://example.com")
browser_tab(action="list", session=SID)
browser_tab(action="activate", session=SID, tab=TAB_ID)
browser_tab(action="close", session=SID, tab=TAB_ID)
```

## Snapshot 策略

不要默认 dump 大页面。优先小窗口观察：

```
browser_page(action="snapshot", session=SID, interactive=true, compact=true, depth=3, format="text")
```

常用选项：

- `interactive=true`：只看交互元素，推荐默认。
- `compact=true`：压缩空结构节点。
- `depth=<n>`：限制树深度。
- `selector="#main"`：限定 DOM 子树。
- `cursor=true`：补充 cursor:pointer / onclick / tabindex 元素。
- `urls=true`：需要链接 href 时开启。
- `format="text"`：适合阅读；默认 json 适合解析。

输出过大时按顺序收缩：开 interactive、开 compact、降低 depth、用 selector 限定区域。快照过大会被自动截断并提示缩小范围。

**非必要不重复 snapshot**：已有 ref 时直接操作，不要每步都重取全页面快照。

## 任务结束报告

任务完成或中止时，输出三段结构化结论：

1. **完成了什么**：已验证/已完成的操作和结果（客观描述）
2. **发现的问题**：未达预期的地方，或操作中遇到的异常（如有）
3. **下一步建议**：用户需要手动处理的事项，或后续可以继续的操作

## Page 命令速查

Ref 操作：click / fill / type / hover / select / scroll_into_view（都用 `ref`）。
键盘滚动鼠标：press(`key`) / scroll(`direction`,`pixels`) / mouse(`mouse_action`,`x`,`y`,`delta_x`,`delta_y`)。
读取：get(`what` = title/url/text/value/html/box，后四种需 `ref`)。
截图等待执行：screenshot / wait(`ms` 或 `load`) / eval(`script`)。

screenshot 返回本地文件路径，可直接在飞书发图或在 Web 渲染。

## 常见错误处理

- 浏览器扩展未连接：提示用户安装并启用 Ethan Browser 扩展，在扩展 options 里填好 server 地址和 token。
- ref not found / 浏览器断连：通常是页面跳转或刷新、或扩展重连。按「AX 树不稳定的兜底路径」处理。
