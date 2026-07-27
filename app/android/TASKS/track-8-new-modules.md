# Track 8: 新模块（Background Tasks / PPT 预览 / Annotations）

> 状态：⬜ 待认领 · 优先级：P2 · 前置依赖：Track 1 + Track 7 已合并

## 目标

新建 3 个 Web 已有但 Android 没有的独立模块。

## 独占文件清单（只能改这些，全部新建）

- `app/android/app/src/main/kotlin/com/ethan/agent/ui/background/BackgroundTasksScreen.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/background/BackgroundTasksViewModel.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/ppt/PptPreviewScreen.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/ppt/PptPreviewViewModel.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/annotations/AnnotationsScreen.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/annotations/AnnotationsViewModel.kt`

**严禁触碰**：
- 任何已存在的 UI 文件
- `ui/EthanApp.kt`、`ui/MoreScreen.kt`（Track 9 管路由注册）
- `ui/navigation/Screen.kt`（Track 7 已加路由声明，本 Track 直接用）
- `data/EthanRepository.kt`、`core/model/`（Track 1 管）

## 模块 A：Background Tasks 后台任务中心

后端：
- `GET /api/background-tasks`（Track 1 已加 Repository 方法）
- `POST /api/background-tasks/{id}/stop`

### 需求

新建 `BackgroundTasksScreen`：
- 顶部 TopAppBar「后台任务」+ 刷新按钮
- 列表卡片显示：
  - task_id（截断显示）
  - task_type（如 `background_search` / `long_running`）
  - status（running / done / failed / cancelled）用 colored badge
  - started_at、duration
  - 进度（如果有 progress 字段）
  - 关联 session_id（可点击跳转 Chat）
- 卡片操作：
  - running 状态：显示「停止」按钮，调 `stopBackgroundTask(id)`
  - done 状态：可查看结果（如有 result_url，跳转 PptPreview 或下载）
- 自动 3s 轮询刷新（有 running 任务时；无则停止）

参考 Web：[desktop/src/components/BackgroundTasksView.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/BackgroundTasksView.tsx)

## 模块 B：PPT 预览

后端：`GET /api/files/deck?session_id=`（Track 1 已加）

### 需求

新建 `PptPreviewScreen`：
- 接收 `sessionId` 路由参数
- 调 `repository.getDeck(sessionId)` 获取 deck.json + pages
- 渲染：
  - 顶部：项目名 + 总页数
  - 主区域：水平分页器（HorizontalPager），每页渲染一张 slide
  - slide 内容用 Markdown 渲染（包括 mermaid、代码块）
  - 底部：页码指示器（1/12）+ 上一页/下一页按钮
- 长按页面弹「导出为图片」菜单（P2，可选）

参考 Web：[desktop/src/pages/ppt-preview.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/pages/ppt-preview.tsx)

## 模块 C：Annotations 标注

后端：
- `GET /api/annotations/{message_id}`（Track 1 已加）
- `GET /api/annotations/batch?ids=`
- `POST /api/annotations`（type: highlight/underline/strike/comment，4 色）
- `DELETE /api/annotations/{anno_id}`

### 需求

新建 `AnnotationsScreen`（管理界面）：
- 列出所有消息的标注（按 message 分组）
- 每条标注显示：type 图标、颜色色块、内容、message 摘要
- 支持删除（滑动或长按）

新建 Composable `AnnotationLayer`（可被 ChatScreen 复用，但本 Track 只实现，不改 ChatScreen）：
- 接收 `messageId` 和 `annotations` 列表
- 渲染高亮/下划线/删除线效果（用 `AnnotatedString` 配合 `SpanStyle`）
- 渲染批注气泡（点击展开/收起）

**协作约定**：ChatScreen 集成 Annotations 由 Track 2 负责（如果 Track 2 已合并，本 Track 提供的 `AnnotationLayer` 可直接被 Track 2 使用；否则本 Track 只实现，不集成）。

参考 Web：
- [desktop/src/lib/api-annotations.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-annotations.ts)
- Web 中标注在阅读模式下渲染：[desktop/src/components/chat/reading-mode.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/chat/reading-mode.tsx)

## ViewModel 状态建议

### BackgroundTasksViewModel

```kotlin
data class BackgroundTasksUiState(
    val tasks: List<BackgroundTask> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
)
```

### PptPreviewViewModel

```kotlin
data class PptPreviewUiState(
    val deck: Deck? = null,
    val pages: List<PptPage> = emptyList(),
    val currentPage: Int = 0,
    val isLoading: Boolean = false,
    val error: String? = null,
)
```

### AnnotationsViewModel

```kotlin
data class AnnotationsUiState(
    val groupedByMessage: Map<String, List<Annotation>> = emptyMap(),
    val isLoading: Boolean = false,
    val error: String? = null,
)
```

## 参考代码

- 后端：
  - [ethan/interface/routers/background_tasks.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/background_tasks.py)（如不存在，grep `background-tasks` 找到具体位置）
  - [ethan/interface/routers/files.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/files.py) 中 deck 端点
  - [ethan/interface/routers/annotations.py](file:///Users/jsongo/code/life/ethan-ai/ethan/interface/routers/annotations.py)
- Web 客户端：
  - [desktop/src/lib/api-annotations.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-annotations.ts)
  - [desktop/src/lib/api-misc.ts](file:///Users/jsongo/code/life/ethan-ai/desktop/src/lib/api-misc.ts) 中 background-tasks 部分

## 验收标准

- [ ] BackgroundTasksScreen 能加载列表，running 任务可停止，自动轮询
- [ ] PptPreviewScreen 能加载 deck，左右滑动切页
- [ ] AnnotationsScreen 能加载并按消息分组，可删除
- [ ] `AnnotationLayer` 组件可被复用（编译通过）
- [ ] 编译通过、lint 无 error

## 不要做的事

- ❌ 不要改 `EthanApp.kt` 注册路由（Track 9 管）
- ❌ 不要改 `MoreScreen.kt` 加入口（Track 9 管）
- ❌ 不要改 `ChatScreen` 集成 annotations（Track 2 管）
- ❌ 不要改 `Screen.kt`（Track 7 已加路由声明）
