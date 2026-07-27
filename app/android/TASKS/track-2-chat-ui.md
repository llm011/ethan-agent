# Track 2: Chat UI 增强

> 状态：⬜ 待认领 · 优先级：P1 · 前置依赖：Track 1 已合并

## 目标

让 ChatScreen 真正用上后端的全部 Chat 能力，并补齐 Web 已有的交互细节。

## 独占文件清单（只能改这些）

- `app/android/app/src/main/kotlin/com/ethan/agent/ui/chat/ChatScreen.kt`
- `app/android/app/src/main/kotlin/com/ethan/agent/ui/chat/ChatViewModel.kt`

**严禁触碰**：
- `ui/components/`（Track 7 管）
- `data/EthanRepository.kt`（Track 1 管）
- `ui/EthanApp.kt`（Track 9 管）
- 其他 UI 模块

## 当前实现

ChatScreen 已有：
- ✅ SSE 流式接收 + 50ms 节流刷新
- ✅ Consent 授权弹窗
- ✅ 附件上传（GetContent `*/*`）
- ✅ Quote 引用回复（长按消息）
- ✅ Slash 命令 `/new`、`/compact`、`/help`、`/sessions`
- ✅ Tool Timeline 渲染
- ✅ Model/Mode 切换

## 缺失功能（本 Track 任务）

### 1. Stop 停止生成（P0）

后端：`POST /api/chat/{id}/stop`（Track 1 已加 Repository 方法）

需求：
- 流式发送过程中，发送按钮变为 Stop 按钮（图标 `Icons.Filled.Stop`）
- 点击 Stop 调用 `repository.stopGeneration(sessionId)`
- 停止后已生成部分保留，末尾追加 `[已停止]` 灰色标记
- Stop 按钮在等待后端响应期间显示 loading 状态

参考 Web：[desktop/src/components/chat/ChatInput.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/chat/ChatInput.tsx) 中的 Stop 按钮

### 2. Stream Resume 重连（P0）

后端：`GET /api/chat/{id}/stream`（204 表示无活跃 run）

需求：
- 进入会话时，先调 `repository.streamResume(sessionId)` 尝试接回放
- 如果返回 204，正常显示历史消息
- 如果返回 SSE 流，按 `ChatSseClient.streamChat` 同样的事件解析逻辑处理
- 顶部状态条显示「正在重连…」/「生成中」/「已停止」
- App 从后台恢复时也触发重连（用 `Lifecycle.Event.ON_RESUME`）

参考 Web：[desktop/src/components/chat/chat-view.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/chat/chat-view.tsx) 中的 `streamResume` 调用

### 3. Inject 运行中补充信息（P1）

后端：`POST /api/chat/{id}/inject`（409 = 无活跃 run）

需求：
- 流式发送过程中，输入框可用，placeholder 变为「补充信息给 Agent…」
- 发送时调用 `repository.injectMessage(sessionId, text)` 而非 streamChat
- 409 错误显示 snackbar「无活跃生成，已切换为普通消息」并降级为普通发送

### 4. active_run 状态展示（P1）

后端：`GET /api/sessions/{id}` 返回 `active_run` 字段

需求：
- 会话顶部状态条：红点 = 生成中、灰点 = 空闲
- 后台轮询（3s）刷新 active_run 状态（复用 Sessions 的 poll 机制）

### 5. 滚动到底部按钮（P1）

参考 Web 已修复的实现。

需求：
- LazyColumn 滚动到中间位置时，右下角浮起一个 FAB（向下箭头）
- 点击平滑滚到底部
- 用户手动滚到底部后 FAB 消失
- 新消息到达时若用户已在底部，自动滚；否则不强制滚（仅显示 FAB + 红点未读数）

参考：[desktop/src/components/chat/message-list.tsx](file:///Users/jsongo/code/life/ethan-ai/desktop/src/components/chat/message-list.tsx)

### 6. 错误重连提示（P2）

需求：
- SSE 连接断开（非正常 done）时显示「连接断开，点击重连」横幅
- 点击重连调用 `streamResume`

## 实现建议

### ViewModel 状态扩展

```kotlin
data class ChatUiState(
    // 已有字段...
    val isGenerating: Boolean = false,        // 替代原 streaming，含义更清晰
    val isResuming: Boolean = false,           // 重连中
    val isStopping: Boolean = false,           // stop 调用中
    val activeRunId: String? = null,           // 当前活跃 run
    val showScrollToBottom: Boolean = false,   // 滚动按钮可见性
    val unreadCount: Int = 0,                  // 用户不在底部时的新消息数
    val connectionState: ConnectionState = ConnectionState.Idle,
)

enum class ConnectionState { Idle, Streaming, Reconnecting, Disconnected }
```

### 重连逻辑

```kotlin
fun resumeStream(sessionId: String) {
    viewModelScope.launch {
        _state.update { it.copy(isResuming = true) }
        try {
            repository.streamResume(sessionId).collect { event ->
                // 同 streamChat 的事件处理
            }
        } catch (e: HttpException) {
            if (e.code() == 204) {
                // 无活跃 run，正常显示历史
            } else {
                _state.update { it.copy(error = friendlyError(e)) }
            }
        }
        _state.update { it.copy(isResuming = false) }
    }
}
```

### 生命周期监听

在 ChatScreen 中：

```kotlin
val lifecycleOwner = LocalLifecycleOwner.current
LaunchedEffect(sessionId) {
    lifecycleOwner.lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
        vm.resumeStream(sessionId)
    }
}
```

## 验收标准

- [ ] 发送过程中能 Stop，已生成部分保留并标记 `[已停止]`
- [ ] 杀进程重启后进入有活跃 run 的会话，能接回 SSE 流
- [ ] 发送过程中能 Inject 补充信息
- [ ] 会话顶部状态条显示生成中/空闲
- [ ] 滚动到中间时显示「滚到底部」FAB
- [ ] 编译通过、lint 无 error

## 不要做的事

- ❌ 不要改 `ChatSseClient`（Track 1 管）
- ❌ 不要改 `EthanRepository`（Track 1 管）
- ❌ 不要实现 Mermaid / 代码高亮 / Annotations（属于 Track 7/8）
- ❌ 不要改底部导航或路由（Track 9 管）
