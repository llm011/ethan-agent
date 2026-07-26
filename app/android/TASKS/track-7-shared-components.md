# Track 7: 共享组件 + 主题系统

> 状态：⬜ 待认领 · 优先级：P1 · 前置依赖：Track 1 已合并

## 目标

升级 Markdown 渲染（Mermaid、代码高亮、Lightbox），引入 Web 的 5 主题系统，扩展路由表。

## 独占文件清单（只能改这些）

- `app/android/app/src/main/kotlin/com/ethan/agent/ui/components/Markdown.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/components/Common.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/theme/Theme.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/navigation/Screen.kt`

**可新建**：
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/components/MermaidBlock.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/components/CodeBlock.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/components/Lightbox.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/theme/Themes.kt`

**严禁触碰**：
- 任何具体 UI 模块（chat/memory/schedule/...）
- `data/EthanRepository.kt`（Track 1 管）
- `core/datastore/`（如需持久化主题，与 Track 1 协调，由 Track 1 在 `AppConfig` 加字段，本 Track 只读用）
- `ui/EthanApp.kt`、`ui/MoreScreen.kt`（Track 9 管）

## 任务清单

### 1. Mermaid 图表渲染（P0）

后端返回的 Markdown 中包含 ` ```mermaid ` 代码块。

需求：
- 新建 `MermaidBlock.kt`，渲染 mermaid 图表
- 方案 A（推荐）：用 WebView + mermaid.js CDN
  - 离线场景下加载本地 assets/mermaid.min.js
  - 主题适配：读 `MaterialTheme.colorScheme.background` 注入到 mermaid 主题（dark/light）
- 方案 B：调后端渲染（无此 API，所以走 A）

参考 Web 实现：[packages/shared/src/components/mermaid-block.tsx](file:///Users/jsongo/code/life/ethan-ai/packages/shared/src/components/mermaid-block.tsx)

**重要**：Mermaid 性能优化，参考 `project_memory.md`：
- 必须读取应用强制主题（`documentElement.dark` class）而非仅依赖系统 `prefers-color-scheme`
- 禁止在 `mermaid.render` 前冗余调用 `mermaid.parse`

### 2. 代码块语法高亮（P1）

需求：
- 新建 `CodeBlock.kt`，渲染带语法高亮的代码块
- 顶部显示语言名 + 复制按钮
- 横向滚动
- 方案：用 [Prism4j](https://github.com/JetBrains/prism4j) 或 [Markwon](https://github.com/noties/markwon) 的 syntax-highlight 模块
- 长按代码块弹「复制」菜单

参考 Web 实现：[packages/shared/src/components/code-block.tsx](file:///Users/jsongo/code/life/ethan-ai/packages/shared/src/components/code-block.tsx)

### 3. Lightbox 图片灯箱（P1）

需求：
- 新建 `Lightbox.kt`，点击 Markdown 中的图片放大查看
- 支持双指缩放、双击放大
- 支持左右滑动切换图片（同一条消息内的多张图片）
- 顶部显示「1 / 3」序号
- 点击空白关闭
- 长按弹「保存到相册」菜单（需要写存储权限，可 P2 实现）

参考 Web 实现：[packages/shared/src/chat/lightbox.tsx](file:///Users/jsongo/code/life/ethan-ai/packages/shared/src/chat/lightbox.tsx)

### 4. Markdown.kt 升级（P0）

当前 [Markdown.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/app/src/main/kotlin/com/ethan/agent/ui/components/Markdown.kt) 用 `dev.jeziellago.compose-markdown` 库的 `MarkdownText`。

需求：
- 改造为支持自定义渲染：
  - ` ```mermaid ` 块 → 调 `MermaidBlock`
  - ` ```language ` 块 → 调 `CodeBlock`
  - `![alt](url)` 图片 → 可点击调 `Lightbox`
- 支持内联图片（base64 和 http(s) URL）
- 支持表格渲染（如果当前库不支持，考虑切换到 [Markwon](https://github.com/noties/markwon) + Compose 适配）
- 保留原有的链接点击行为（用 `Intent.ACTION_VIEW` 打开）

### 5. 5 主题系统（P0）

抄 Web 的 5 主题：青瓦 / 暖橙 / 素纸 / 微雾 / 深色

需求：
- 新建 `Themes.kt`，定义 5 套 `ColorScheme`
- 在 [Theme.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/app/src/main/kotlin/com/ethan/agent/ui/theme/Theme.kt) 中：
  - 从 `EthanRepository.config` 读 `themeId`（约定由 Track 1 在 `AppConfig` 加字段 `themeId: String`，默认 `"system"`）
  - 根据 `themeId` 选择 `ColorScheme`
  - `themeId == "system"` 时跟随系统暗黑模式
  - `themeId == "dark"` 强制深色
  - 其他值用对应主题
- 提供 `setThemeId(id: String)` 通过 `EthanRepository.setThemeId(id)` 持久化
  - **协作约定**：Track 1 在 `AppConfig` 加 `themeId: String = "system"` 字段，在 `EthanRepository` 加 `setThemeId(id)` 方法，在 `AppConfigStore` 加持久化逻辑
  - 如果 Track 1 尚未合并，本 Track 先用 `MaterialTheme.colorScheme` 兜底，等 Track 1 合并后再切到 `EthanRepository.config`

参考 Web 实现：[desktop/src/components/chat/themes.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/chat/themes.ts)

5 主题颜色（从 Web 抄过来）：

| 主题 ID | 名称 | 主色调 |
|--------|------|--------|
| `qingwa` | 青瓦 | 青灰色系 |
| `nuancheng` | 暖橙 | 暖橙色系 |
| `suzhi` | 素纸 | 米白素净 |
| `weiwu` | 微雾 | 灰雾朦胧 |
| `dark` | 深色 | Material3 dark |
| `system` | 跟随系统 | 跟随系统设置 |

### 6. 扩展路由表（P0）

在 [Screen.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/app/src/main/kotlin/com/ethan/agent/ui/navigation/Screen.kt) 加新路由：

```kotlin
data object BackgroundTasks : Screen("background-tasks", "后台任务", Icons.Default.BackgroundTasks)
data object PptPreview : Screen("ppt-preview/{sessionId}", "PPT 预览") {
    fun createRoute(sessionId: String) = "ppt-preview/$sessionId"
}
data object Annotations : Screen("annotations/{sessionId}", "标注") {
    fun createRoute(sessionId: String) = "annotations/$sessionId"
}
```

注意：只是声明路由，不实现具体 Screen（具体 Screen 由 Track 8 实现，Track 9 在 EthanApp.kt 注册）。

### 7. 共享 LoadingBox / ErrorSnackbar 增强（P2）

当前 [Common.kt](file:///Users/jsongo/code/life/ethan-ai/app/android/app/src/main/kotlin/com/ethan/agent/ui/components/Common.kt) 的 `LoadingBox` 只是居中转圈。

需求：
- 加 `EmptyState` 组件：图标 + 提示文字 + 可选 CTA 按钮
- 加 `ConfirmDialog` 组件：标题 + 内容 + 确认/取消，用于二次确认（删除等场景）
- `ErrorSnackbar` 支持带「重试」按钮

## 协作约定

由于本 Track 与 Track 1（`AppConfig.themeId` 字段）和 Track 5（Settings 主题入口）有依赖，约定：

- Track 1 在 `AppConfig` 加 `themeId: String = "system"` 字段 + `EthanRepository.setThemeId(id)` 方法（**Track 1 任务清单已声明**）
- Track 5 在 Settings 加主题入口，调 `EthanRepository.setThemeId(id)`
- Track 7（本 Track）实现主题切换的实际效果，从 `EthanRepository.config` 读 `themeId` 应用

如果 Track 1 未合并，本 Track 用 `MaterialTheme.colorScheme` 兜底，先实现 5 主题定义但不持久化。

## 参考代码

- Web 主题：[desktop/src/components/chat/themes.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/chat/themes.ts)
- Web 主题选择器：[desktop/src/components/chat/theme-picker.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/chat/theme-picker.tsx)
- Web Mermaid：[packages/shared/src/components/mermaid-block.tsx](file:///Users/jsongo/code/life/ethan-ai/packages/shared/src/components/mermaid-block.tsx)
- Web 代码块：[packages/shared/src/components/code-block.tsx](file:///Users/jsongo/code/life/ethan-ai/packages/shared/src/components/code-block.tsx)
- Web Lightbox：[packages/shared/src/chat/lightbox.tsx](file:///Users/jsongo/code/life/ethan-ai/packages/shared/src/chat/lightbox.tsx)

## 验收标准

- [ ] Markdown 中的 ` ```mermaid ` 块能渲染为图表
- [ ] 代码块有语法高亮 + 复制按钮
- [ ] 图片点击放大，支持双指缩放
- [ ] 5 主题切换生效（青瓦/暖橙/素纸/微雾/深色）
- [ ] 路由表扩展不破坏现有路由
- [ ] 编译通过、lint 无 error

## 不要做的事

- ❌ 不要改 `EthanRepository`（Track 1 管，约定由 Track 1 加 `themeId` 字段）
- ❌ 不要实现 BackgroundTasks / Ppt / Annotations 的 Screen（Track 8 管）
- ❌ 不要改 `EthanApp.kt` 注册新路由（Track 9 管）
- ❌ 不要切换 `compose-markdown` 库的版本（除非必要，需在 PR 描述说明）
