---
name: use-browser
version: 0.3.0
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
7. 工具输出是 snake_case JSON；每次返回含 `_hint` 字段，说明本次输出的字段含义和下一步用法（如 snapshot 的 ref 格式、get 的 value 字段）。交互操作（click/fill/type/press 等）的返回还含 `_step` 字段，表示当前会话累计操作步数。
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

1. **`click_selector` / `fill_selector`** — 用 CSS/XPath/text 直接定位 + CDP mouse 真实点击（不依赖 snapshot，绕过 ref 失效和 covered-by 拦截）
2. `selector` 缩小 snapshot 区域重新取 ref（如 `selector="#form"`）
3. `get action="html"` 读取目标区域 HTML，从中找稳定 selector
4. `click_vlm` — 截图发给多模态 LLM 识别坐标后点击（终极 fallback，适用于 Canvas/图片按钮/Semi-UI 自定义组件等 AX 树不可靠的场景）
5. `eval` 直接操作 DOM（`document.querySelector(...).click()`，但对 React 组件可能无效）
6. 以上都失败则上报 blocker

## Selector 直接操作（不依赖 snapshot）

当 snapshot 截断、ref 失效、或 covered-by 拦截时，用 selector 操作绕过：

```
# CSS selector 点击
browser_page(action="click_selector", session=SID, selector=".radio-M-plus")

# XPath 点击
browser_page(action="click_selector", session=SID, xpath="//button[text()='提交']")

# 按文本点击（取第 nth 个匹配）
browser_page(action="click_selector", session=SID, text="字节范", nth=0)

# 填输入框（兼容 React）
browser_page(action="fill_selector", session=SID, selector="#search-input", text="关键词")

# 悬停
browser_page(action="hover_selector", session=SID, selector=".dropdown-trigger")

# 等待元素出现（轮询，默认 10s 超时）
browser_page(action="wait_for_element", session=SID, selector=".result-item", timeout=15000)

# 按文本滚动定位
browser_page(action="scroll_to_text", session=SID, text="绩效总结")

# 提取页面内容
browser_page(action="extract_content", session=SID, selector=".main-content")

# 查找元素列表
browser_page(action="find_elements", session=SID, selector="button.btn-primary")

# 获取元素属性
browser_page(action="find_attributes", session=SID, selector="a.download", attributes=["href", "title"])

# 检查元素是否存在
browser_page(action="check_exist", session=SID, selector=".loading-spinner")

# 输入+回车（搜索框场景）
browser_page(action="input_enter", session=SID, selector="#search-box", text="查询内容")

# 边滚动边查找元素
browser_page(action="scroll_find", session=SID, selector=".lazy-loaded-item", scroll_times=5)
```

**优势**：不依赖 snapshot ref，不会因截断或 covered-by 失败。底层用 eval 获取坐标 + CDP mouse 真实点击（不是 eval .click()），对 React/Semi-UI 组件有效。

## VLM 视觉点击

当 AX 树和 selector 都不可靠时（Canvas 应用、图片按钮、自定义组件），用 VLM 视觉点击：

```
browser_page(action="click_vlm", session=SID, prompt="字节范 M+ 按钮")
```

流程：截图 → 发给多模态 LLM 识别坐标 → CDP mouse 点击。需要当前模型支持视觉（如 claude-sonnet、gpt-4o）。

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

### Tab 整理（批量分组/移出/排序/清理）

**核心原则：整理 ≠ 关闭。** 用户要求"整理 tab"时，目标是把散乱的标签归类分组，而不是关掉它们。

#### 绝对禁止

- **❌ 不要关闭已创建的 tab group（session）** —— 分组是整理的最终产出，不是临时容器。创建的分组必须保留给用户
- **❌ 不要关闭用户正在浏览的有内容的标签** —— 除非明确属于下面"可以关闭"的类别
- **❌ 不要用 `browser_page(action="eval")` 调用 `chrome.tabs.*` / `chrome.tabGroups.*` API** —— 内容脚本无权调用这些扩展 API，必定失败。标签管理只通过 `browser_tab` 和 `browser_session` 工具完成
- **❌ 不要绕弯路** —— 不要 find_tools、不要找其他技能/脚本，直接用 `browser_tab` + `browser_session`
- **❌ 不要创建"临时 session"整理完后关掉** —— session 就是 Chrome Tab Group，创建即分组，整理完保持打开

#### 可以关闭的标签（清理规则）

只有以下类型的标签可以关闭：
1. **完全重复的标签**：URL 完全相同的多个 tab，只保留一个
2. **明显无用的空白页**：如 `chrome://newtab`、空白的搜索引擎首页（百度/Google 首页但没有搜索内容）
3. **用户明确要求关闭的标签**

其他所有标签都应保留并归入合适的分组。

#### 正确操作流程

```
# 1. 获取所有 tab（包括已分组和未分组的）
browser_tab(action="list")        # 已有 session 管理的 tab
browser_tab(action="user_list")   # 未分组的 tab

# 2. 根据 URL/title 语义分类，规划分组方案（在脑中完成，不要调工具）

# 3. 创建分组（session = Chrome Tab Group，创建后永久保留）
browser_session(action="create", title="分组名", color="blue")

# 4. 批量归入（用 attach_batch 一次性操作，效率最高）
browser_tab(action="attach_batch", session=SID, tabs=[TAB_ID1, TAB_ID2, TAB_ID3])

# 5. 仅关闭重复/无用 tab（严格按清理规则）
browser_tab(action="close", session=SID, tab=TAB_ID)

# 6. 微调：移动 tab 位置、在分组间转移
browser_tab(action="move", session=SID, tab=TAB_ID, index=0)
browser_tab(action="detach", session=SID, tab=TAB_ID)  # 移出分组
```

#### 效率要求

- **用 `attach_batch` 批量操作**，不要一个个 tab 逐个 attach
- **先规划再执行**：看完所有 tab 后一次性规划分组方案，然后按组批量操作
- 分组颜色搭配合理，不同类别用不同颜色区分

#### 分组建议策略

根据 tab 的 URL 和标题自动推断类别，常见分组：
- 工作文档（飞书/Google Docs/Notion 等）
- 代码相关（GitHub/GitLab/代码平台）
- 监控数据（Grafana/APM/数据看板）
- 沟通协作（邮件/IM/会议）
- 学习参考（技术博客/文档/Stack Overflow）
- 生活娱乐（购物/视频/社交）

不必强行覆盖所有类别，根据实际 tab 内容灵活分组。

### 更新 Session（分组颜色/标题）

```
# 修改分组颜色和标题
browser_session(action="update", session=SID, title="工作", color="blue")
```

支持的颜色：`grey`、`blue`、`red`、`yellow`、`green`、`pink`、`purple`、`cyan`、`orange`。

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

输出过大时按顺序收缩：开 interactive、开 compact、降低 depth、用 selector 限定区域。

### Snapshot 分页（大页面必读）

snapshot 完整内容会落盘到 `/tmp/ethan-snapshots/` 下，prompt 里只带首段约 10000 字。返回 JSON 含以下分页字段：

- `snapshot_path`：完整 snapshot 的文件路径
- `total_chars`：完整内容总字符数
- `chunk_offset`：当前段的起始偏移（首段为 0）
- `chunk_length`：当前段的实际长度
- `has_more`：是否还有后续内容

**`has_more=true` 时**，当前 snapshot 字段只是首段，目标元素可能不在里面。用 `snapshot_read` 翻页读取后续内容：

```
browser_page(action="snapshot_read", path=SNAPSHOT_PATH, offset=CHUNK_LENGTH)
```

`offset` 用上次返回的 `chunk_offset + chunk_length`。每次返回新的段落（替代上一段到 prompt 里，不是累加），`has_more=true` 就继续翻，直到找到目标元素的 ref。

找到 ref 后直接用 `click`/`fill` 等操作，ref 仍然有效（只要页面没跳转/刷新）。

**非必要不重复 snapshot**：已有 ref 时直接操作，不要每步都重取全页面快照。

## 任务结束报告

任务完成或中止时，输出三段结构化结论：

1. **完成了什么**：已验证/已完成的操作和结果（客观描述）
2. **发现的问题**：未达预期的地方，或操作中遇到的异常（如有）
3. **下一步建议**：用户需要手动处理的事项，或后续可以继续的操作

## Page 命令速查

Snapshot：snapshot(`session`, `interactive`, `compact`, `depth`, `selector`) → 返回首段+`snapshot_path`；snapshot_read(`path`, `offset`) 翻页读后续。
Ref 操作：click / fill / type / hover / select / scroll_into_view（都用 `ref`）。
Selector 操作：click_selector(`selector`/`xpath`/`text`, `nth`) / fill_selector(`selector`/`xpath`, `text`) / hover_selector / input_enter(`selector`, `text`)。
查询：find_elements(`selector`) / find_attributes(`selector`, `attributes`) / check_exist(`selector`) / extract_content(`selector`) / wait_for_element(`selector`, `timeout`)。
滚动查找：scroll_to_text(`text`) / scroll_find(`selector`, `scroll_times`)。
VLM：click_vlm(`prompt`)。
键盘滚动鼠标：press(`key`) / scroll(`direction`,`pixels`) / mouse(`mouse_action`,`x`,`y`,`delta_x`,`delta_y`)。
读取：get(`what` = title/url/text/value/html/box，后四种需 `ref`)。
截图等待执行：screenshot / wait(`ms` 或 `load`) / eval(`script`)。

screenshot 返回本地文件路径，可直接在飞书发图或在 Web 渲染。

## 绝对禁止的做法（Anti-Patterns）

以下做法**绝不允许**，违反会导致任务超时或死循环：

1. **❌ 不要用 `delegate_coding` 写 Playwright/Puppeteer/Selenium 脚本来操作浏览器**
   - delegate_coding 有 180s 硬超时，Playwright 安装 Chromium 就要超过这个时间
   - 你已经有 browser_session/browser_tab/browser_page，这就是你的浏览器工具，直接用

2. **❌ 不要用 `shell` 跑 Python 脚本做网页自动化**
   - shell 授权可能被拒绝，即使通过了也不如直接调 browser 工具高效
   - 用户给你的 browser 工具已经能做一切网页操作

3. **❌ 不要在 browser 工具可用时还去找其他路径**
   - 不要尝试 AppleScript 控制浏览器
   - 不要写临时脚本让用户手动跑
   - 不要用 computer_use 截图+点击来操作网页（那是 GUI 桌面工具，不是浏览器工具）

4. **❌ 同一操作失败超过 3 次后不要继续尝试相同方法**
   - 上报 blocker，说明情况，让用户决定

5. **❌ 不要用 `eval` 调用 Chrome 扩展 API（`chrome.tabs.*`、`chrome.tabGroups.*` 等）**
   - 页面内容脚本无权访问这些 API，100% 会报错
   - 标签/分组管理只通过 `browser_tab` 和 `browser_session` 工具完成

**正确做法**：需要操作网页 → 直接调 `browser_session` 创建会话 → `browser_page` 操作页面。就这么简单。

## 降级路径（扩展未连接时）

如果 browser_session 返回"扩展未连接"错误：

1. 告诉用户：浏览器扩展未连接，请检查 Chrome 是否打开、扩展是否启用
2. 如果用户表示无法连接，尝试 `agent-browser`（兜底浏览器，独立 Chrome）
3. 如果 agent-browser 也不可用，用 `web_fetch` 获取网页内容（只能读，不能交互）
4. 对于必须交互的操作（如登录、填表），明确告知用户当前无法完成，建议先修复扩展连接

## 常见错误处理

- 浏览器扩展未连接：提示用户安装并启用 Ethan Browser 扩展，在扩展 options 里填好 server 地址和 token。
- ref not found / 浏览器断连：通常是页面跳转或刷新、或扩展重连。按「AX 树不稳定的兜底路径」处理。
