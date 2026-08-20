package com.ethan.agent.shared.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.AskUserInfo
import com.ethan.agent.core.model.ChatMessage
import com.ethan.agent.core.model.ChatStreamEvent
import com.ethan.agent.core.model.ConsentInfo
import com.ethan.agent.core.model.ModeEntry
import com.ethan.agent.core.model.ModelEntry
import com.ethan.agent.core.model.OnboardingStatus
import com.ethan.agent.core.model.Quote
import com.ethan.agent.core.model.ToolStep
import com.ethan.agent.core.model.Usage
import com.ethan.agent.core.model.WaitForUserInfo
import com.ethan.agent.shared.EthanRepository
import com.ethan.agent.shared.UiMessage
import com.ethan.agent.shared.UiMessageImage
import com.ethan.agent.shared.ShareBus
import kotlinx.datetime.Clock
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

enum class ConnectionState { Idle, Streaming, Reconnecting, Disconnected }

/** 待发送的图片：内存临时持有，发送后清空。不落 DB。 */
data class PendingImage(
    val dataUrl: String,        // "data:image/png;base64,..." 用于预览
    val base64Data: String,     // 无前缀的 base64，发送时用
    val mediaType: String,      // "image/png" 等
    val filename: String,
)

data class ChatUiState(
    val sessionId: String? = null,
    val title: String = "新对话",
    val messages: List<UiMessage> = emptyList(),
    val models: List<ModelEntry> = emptyList(),
    val modes: List<ModeEntry> = emptyList(),
    val selectedModel: String? = null,
    val selectedMode: String = "",
    val inputText: String = "",
    val pendingImages: List<PendingImage> = emptyList(),
    val isLoading: Boolean = false,
    val isStreaming: Boolean = false,
    val isResuming: Boolean = false,
    val isStopping: Boolean = false,
    val connectionState: ConnectionState = ConnectionState.Idle,
    val showScrollToBottom: Boolean = false,
    val unreadCount: Int = 0,
    val error: String? = null,
    val consent: ConsentInfo? = null,
    val askUser: AskUserInfo? = null,
    /** ask_user 卡片剩余秒数（倒计时，超时自动走 default） */
    val askUserRemaining: Int = 0,
    val waitForUser: WaitForUserInfo? = null,
    /** wait_for_user 卡片剩余秒数（倒计时，超时自动回传 "timeout"） */
    val waitForUserRemaining: Int = 0,
    val quote: Quote? = null,
    val onboarding: OnboardingStatus? = null,
    val showOnboarding: Boolean = false,
    val agentName: String = "",
    val userInfo: String = "",
)

class ChatViewModel(
    private val repository: EthanRepository,
    sessionId: String?,
) : ViewModel() {
    private val _state = MutableStateFlow(ChatUiState())
    val state: StateFlow<ChatUiState> = _state.asStateFlow()
    private var streamJob: Job? = null
    private var askUserCountdownJob: Job? = null
    private var waitForUserCountdownJob: Job? = null

    init {
        loadInitial(sessionId)
        observeSharedText()
    }

    /**
     * 响应式消费「分享到 Ethan」投递的文本：订阅 ShareBus 而非 init 里一次性取值。
     * 这样 app 已在前台时再次分享（onNewIntent 更新 pendingText），也能再次预填进输入框。
     * 图片/文件 URI 由 ChatScreen 层处理上传（需要 ContentResolver），此处仅管文本。
     */
    private fun observeSharedText() {
        viewModelScope.launch {
            ShareBus.pendingText.collect { shared ->
                if (shared.isNullOrBlank()) return@collect
                _state.update {
                    val existing = it.inputText
                    it.copy(inputText = if (existing.isBlank()) shared else "$existing\n$shared")
                }
                // 原子清空，避免误清 collect 期间到达的新分享
                ShareBus.consumeText(shared)
            }
        }
    }

    private fun loadInitial(sessionId: String?) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }

            // 并行加载元数据（cached flow: 先秒出缓存，再网络刷新）
            launch {
                try {
                    repository.cachedModels().collect { models ->
                        _state.update {
                            it.copy(models = models, selectedModel = it.selectedModel ?: models.firstOrNull()?.id)
                        }
                    }
                } catch (_: Exception) { }
            }
            launch {
                try {
                    repository.cachedModes().collect { modes ->
                        _state.update { it.copy(modes = modes) }
                    }
                } catch (_: Exception) { }
            }
            launch {
                try {
                    repository.cachedAgentSettings().collect { settings ->
                        _state.update { it.copy(agentName = settings.agentName) }
                        if (sessionId == null) {
                            _state.update {
                                it.copy(
                                    selectedModel = settings.defaultModel.ifBlank { it.models.firstOrNull()?.id },
                                    isLoading = false,
                                )
                            }
                        }
                    }
                } catch (_: Exception) { }
            }
            launch {
                try {
                    val onboarding = repository.getOnboardingStatus()
                    _state.update { it.copy(onboarding = onboarding, showOnboarding = onboarding.firstTime) }
                } catch (_: Exception) { }
            }

            // session 详情：cached flow 先秒出缓存数据，再网络刷新
            if (sessionId != null) {
                // 取 serverUrl 用于拼接历史消息里的图片相对路径
                val serverUrl = repository.config.first().serverUrl
                try {
                    repository.cachedSession(sessionId).collect { session ->
                        _state.update {
                            it.copy(
                                sessionId = session.id,
                                title = session.title,
                                selectedModel = session.model,
                                selectedMode = session.mode ?: "",
                                messages = session.messages.map { msg ->
                                    UiMessage(
                                        role = msg.role,
                                        content = msg.content,
                                        toolSteps = msg.toolSteps ?: emptyList(),
                                        usage = msg.usage,
                                        quote = msg.quote,
                                        createdAt = msg.createdAt,
                                        images = msg.images?.mapNotNull { img ->
                                            img.url?.let { UiMessageImage(displayUrl = "${serverUrl.trimEnd('/')}/api/${it}") }
                                        } ?: emptyList(),
                                    )
                                },
                                isLoading = false,
                            )
                        }
                    }
                } catch (e: Exception) {
                    // 网络失败且无缓存时才显示错误；有缓存时数据已在 state 中
                    if (_state.value.messages.isEmpty()) {
                        _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
                    } else {
                        _state.update { it.copy(isLoading = false) }
                    }
                }
            } else {
                _state.update { it.copy(isLoading = false) }
            }
        }
    }

    fun onInputChange(text: String) { _state.update { it.copy(inputText = text) } }

    /**
     * 消费跨页面（如 Agenda「拆解该安排」）带来的自动发送 prompt。
     * 等模型就绪后再发送（新会话 isLoading 立即为 false，selectedModel 依赖缓存流）。
     * 10s 兜底：超时仍未就绪则退化为预填输入框（不自动发送）——避免 selectedModel=null
     * 让 createSession 落到后端默认模型，prompt 也不会丢。
     */
    fun autoSendPrompt(prompt: String) {
        if (prompt.isBlank()) return
        viewModelScope.launch {
            val ready = withTimeoutOrNull(10_000) {
                _state.first { !it.isLoading && it.selectedModel != null }
            }
            _state.update { it.copy(inputText = prompt) }
            if (ready != null) sendMessage()
        }
    }

    fun onModelSelected(model: String) { _state.update { it.copy(selectedModel = model) } }
    fun onModeSelected(mode: String) { _state.update { it.copy(selectedMode = mode) } }
    fun setQuote(quote: Quote?) { _state.update { it.copy(quote = quote) } }
    fun clearQuote() { _state.update { it.copy(quote = null) } }

    fun addImage(dataUrl: String, base64Data: String, mediaType: String, filename: String) {
        _state.update { it.copy(pendingImages = it.pendingImages + PendingImage(dataUrl, base64Data, mediaType, filename)) }
    }

    fun removeImage(index: Int) {
        _state.update { it.copy(pendingImages = it.pendingImages.toMutableList().also { it.removeAt(index) }) }
    }

    fun setShowScrollToBottom(show: Boolean) { _state.update { it.copy(showScrollToBottom = show) } }
    fun clearUnread() { _state.update { it.copy(unreadCount = 0) } }

    /** 发送消息：流式发送中则 inject，否则普通发送 */
    fun sendMessage() {
        val current = _state.value
        val text = current.inputText.trim()
        val images = current.pendingImages
        if (text.isEmpty() && images.isEmpty()) return

        if (current.isStreaming && streamJob?.isActive == true) {
            if (text.isNotEmpty()) injectMessage(text)
            return
        }

        // 有图片时不走 slash command
        if (text.startsWith("/") && images.isEmpty()) {
            handleSlashCommand(text)
            return
        }

        viewModelScope.launch {
            // 待发送图片转成 UI 渲染格式（用 dataUrl 即时预览）和 API 格式
            val uiImages = images.map { UiMessageImage(displayUrl = it.dataUrl) }
            val apiImages = images.map { com.ethan.agent.core.model.MessageImage(data = it.base64Data, mediaType = it.mediaType) }
            val userMessage = UiMessage(role = "user", content = text, quote = current.quote, createdAt = Clock.System.now().toEpochMilliseconds() / 1000, images = uiImages)
            _state.update {
                it.copy(
                    inputText = "",
                    pendingImages = emptyList(),
                    quote = null,
                    messages = it.messages + userMessage,
                    isStreaming = true,
                    connectionState = ConnectionState.Streaming,
                    error = null,
                )
            }

            var sessionId = current.sessionId
            if (sessionId == null) {
                try {
                    val created = repository.createSession(current.selectedModel, current.selectedMode.ifBlank { null })
                    sessionId = created.id
                    _state.update { it.copy(sessionId = sessionId, title = created.title) }
                } catch (e: Exception) {
                    _state.update { it.copy(isStreaming = false, connectionState = ConnectionState.Idle, error = repository.friendlyError(e)) }
                    return@launch
                }
            }

            // 当前用户消息带图片；历史消息的图片已由后端转成文件，content 里不含 base64
            val history = _state.value.messages.mapIndexed { idx, msg ->
                val isLastUser = idx == _state.value.messages.lastIndex && msg.role == "user"
                ChatMessage(
                    role = msg.role,
                    content = msg.content,
                    images = if (isLastUser && apiImages.isNotEmpty()) apiImages else null,
                )
            }
            val assistantIndex = _state.value.messages.size
            _state.update { it.copy(messages = it.messages + UiMessage(role = "assistant", content = "", isStreaming = true, createdAt = Clock.System.now().toEpochMilliseconds() / 1000)) }

            streamJob = viewModelScope.launch {
                try {
                    collectSseStream(
                        flow = repository.streamChat(
                            messages = history,
                            model = _state.value.selectedModel,
                            sessionId = sessionId,
                            quote = userMessage.quote,
                            mode = _state.value.selectedMode,
                        ),
                        assistantIndex = assistantIndex,
                    )
                    _state.update { it.copy(connectionState = ConnectionState.Idle) }
                } catch (e: Exception) {
                    _state.update { it.copy(isStreaming = false, connectionState = ConnectionState.Disconnected, error = repository.friendlyError(e)) }
                }
            }
        }
    }

    /** 运行中向 agent 注入补充信息；409 = 无活跃 run，自动降级普通发送 */
    private fun injectMessage(text: String) {
        val sessionId = _state.value.sessionId ?: return
        _state.update { it.copy(inputText = "") }
        viewModelScope.launch {
            try {
                repository.injectMessage(sessionId, text)
            } catch (e: Exception) {
                val isNoActiveRun = e is com.ethan.agent.core.network.ApiException && e.code == 409
                if (isNoActiveRun) {
                    // 后端 run 已结束，前端 isStreaming 是 stale 状态；先清掉再降级，避免 sendMessage 因 isStreaming=true 又回到 injectMessage 形成死循环
                    _state.update { it.copy(isStreaming = false, connectionState = ConnectionState.Idle, inputText = text) }
                    sendMessage()
                } else {
                    _state.update { it.copy(error = repository.friendlyError(e)) }
                }
            }
        }
    }

    /** App 从后台恢复时调用，尝试接回进行中的 SSE 流。204 = 无活跃 run，静默返回。 */
    fun resumeStream() {
        val sessionId = _state.value.sessionId ?: return
        if (_state.value.isStreaming || _state.value.isResuming) return

        streamJob?.cancel()
        streamJob = viewModelScope.launch {
            _state.update { it.copy(isResuming = true, connectionState = ConnectionState.Reconnecting) }
            // 若最后一条已是 isStreaming=true 的 assistant（上次中断的占位），复用它；否则才追加新占位
            val msgs = _state.value.messages
            val lastIdx = msgs.lastIndex
            val reuseLast = lastIdx >= 0 && msgs[lastIdx].role == "assistant" && msgs[lastIdx].isStreaming
            val assistantIndex = if (reuseLast) lastIdx else msgs.size
            if (!reuseLast) {
                _state.update { it.copy(messages = it.messages + UiMessage(role = "assistant", content = "", isStreaming = true)) }
            }
            var gotAnyEvent = false
            try {
                collectSseStream(
                    flow = repository.resumeStream(sessionId),
                    assistantIndex = assistantIndex,
                    onFirstEvent = { gotAnyEvent = true },
                )
                _state.update { it.copy(connectionState = ConnectionState.Idle) }
            } catch (e: Exception) {
                _state.update { it.copy(connectionState = ConnectionState.Disconnected, error = repository.friendlyError(e)) }
            } finally {
                // 仅当追加了新占位且没收到任何事件时才 drop，避免误删复用的旧气泡
                if (!reuseLast && !gotAnyEvent) {
                    _state.update { s -> s.copy(messages = s.messages.dropLast(1)) }
                }
                _state.update { it.copy(isResuming = false, isStreaming = false) }
            }
        }
    }

    /** 停止生成：先调后端 API，再取消本地 job */
    fun stopStreaming() {
        val sessionId = _state.value.sessionId
        if (_state.value.isStopping) return
        _state.update { it.copy(isStopping = true) }

        viewModelScope.launch {
            if (sessionId != null) {
                try { repository.stopChat(sessionId) } catch (_: Exception) { /* 忽略，继续本地清理 */ }
            }
            streamJob?.cancel()
            _state.update { s ->
                val msgs = s.messages.toMutableList()
                val lastIdx = msgs.indexOfLast { it.role == "assistant" }
                if (lastIdx >= 0) {
                    val last = msgs[lastIdx]
                    msgs[lastIdx] = last.copy(
                        content = last.content + if (last.content.isNotEmpty()) " [已停止]" else "[已停止]",
                        isStreaming = false,
                    )
                }
                s.copy(isStreaming = false, isStopping = false, connectionState = ConnectionState.Idle, messages = msgs)
            }
        }
    }

    /** 共享 SSE 事件处理逻辑（streamChat 和 resumeStream 复用） */
    private suspend fun collectSseStream(
        flow: Flow<ChatStreamEvent>,
        assistantIndex: Int,
        onFirstEvent: (() -> Unit)? = null,
    ) {
        val toolSteps = mutableListOf<ToolStep>()
        var usage: Usage? = null
        val contentBuilder = StringBuilder()
        var lastFlushMs = 0L
        var firstEvent = true
        val streamStartMs = Clock.System.now().toEpochMilliseconds()
        var ttfbMs: Long? = null
        var firstContentMs: Long? = null

        fun flush(force: Boolean = false) {
            val now = Clock.System.now().toEpochMilliseconds()
            if (!force && now - lastFlushMs < 50L) return
            lastFlushMs = now
            val content = contentBuilder.toString()
            _state.update { s ->
                val msgs = s.messages.toMutableList()
                if (assistantIndex < msgs.size) msgs[assistantIndex] = msgs[assistantIndex].copy(content = content)
                s.copy(messages = msgs)
            }
        }

        try {
            flow.collect { event ->
                if (firstEvent) {
                    firstEvent = false
                    onFirstEvent?.invoke()
                    _state.update { it.copy(isStreaming = true) }
                }
                when {
                    event.consentRequest == true -> {
                        _state.update {
                            it.copy(
                                consent = ConsentInfo(
                                    requestId = event.requestId ?: "",
                                    tool = event.tool ?: "",
                                    description = event.description ?: "",
                                    detail = event.detail,
                                ),
                            )
                        }
                    }
                    event.askUserRequest == true -> {
                        startAskUserCountdown(
                            AskUserInfo(
                                requestId = event.requestId ?: "",
                                question = event.question ?: "",
                                options = event.options ?: emptyList(),
                                default = event.default ?: "",
                                timeout = event.timeout ?: 20,
                            ),
                        )
                    }
                    event.waitForUserRequest == true -> {
                        startWaitForUserCountdown(
                            WaitForUserInfo(
                                requestId = event.requestId ?: "",
                                prompt = event.prompt ?: "",
                                inputType = event.inputType ?: "confirm",
                                placeholder = event.placeholder ?: "",
                                confirmLabel = event.confirmLabel ?: "已完成",
                                cancelLabel = event.cancelLabel ?: "取消",
                                timeout = event.timeout ?: 300,
                            ),
                        )
                    }
                    event.content != null -> {
                        if (firstContentMs == null) {
                            firstContentMs = Clock.System.now().toEpochMilliseconds()
                            ttfbMs = firstContentMs!! - streamStartMs
                        }
                        contentBuilder.append(event.content)
                        flush()
                        if (_state.value.showScrollToBottom) {
                            _state.update { it.copy(unreadCount = it.unreadCount + 1) }
                        }
                    }
                    event.tool != null -> {
                        val tool = event.tool!!
                        val step = ToolStep(
                            tool = tool,
                            args = event.args ?: "",
                            state = event.state ?: "start",
                            durationMs = event.durationMs,
                            resultPreview = event.resultPreview,
                            resultDetail = event.resultDetail,
                            thought = event.thought,
                            intent = event.intent,
                            id = event.id,
                            subSteps = event.subSteps,
                        )
                        val existing = toolSteps.indexOfFirst { it.id == step.id && step.id != null }
                        if (existing >= 0) toolSteps[existing] = step else toolSteps.add(step)
                        _state.update { s ->
                            val msgs = s.messages.toMutableList()
                            if (assistantIndex < msgs.size) msgs[assistantIndex] = msgs[assistantIndex].copy(toolSteps = toolSteps.toList())
                            s.copy(messages = msgs)
                        }
                    }
                    event.done == true -> { usage = event.usage }
                    event.error != null -> { _state.update { it.copy(error = event.error) } }
                }
            }
        } finally {
            // 无论正常结束还是异常，都要重置 assistant 气泡的 isStreaming，避免 spinner 永久卡住
            flush(force = true)
            val totalDurationMs = Clock.System.now().toEpochMilliseconds() - streamStartMs
            val generationDurationMs = firstContentMs?.let { Clock.System.now().toEpochMilliseconds() - it }
            _state.update { s ->
                val msgs = s.messages.toMutableList()
                if (assistantIndex < msgs.size) {
                    // 防御：流结束/中止时仍处于 running/start 的步骤标记为 cancelled（与后端保存逻辑对齐）
                    val sanitizedSteps = msgs[assistantIndex].toolSteps.map { step ->
                        val newState = if (step.state == "running" || step.state == "start") "cancelled" else step.state
                        val newSubs = step.subSteps?.map { sub ->
                            if (sub.state == "running" || sub.state == "start") sub.copy(state = "cancelled") else sub
                        }
                        if (newState != step.state || newSubs !== step.subSteps) {
                            step.copy(state = newState, subSteps = newSubs)
                        } else {
                            step
                        }
                    }
                    msgs[assistantIndex] = msgs[assistantIndex].copy(
                        isStreaming = false,
                        toolSteps = sanitizedSteps,
                        usage = usage,
                        ttfbMs = ttfbMs,
                        totalDurationMs = totalDurationMs,
                        generationDurationMs = generationDurationMs,
                    )
                }
                s.copy(messages = msgs, isStreaming = false)
            }
        }
    }

    private fun handleSlashCommand(cmd: String) {
        viewModelScope.launch {
            when (cmd) {
                "/new" -> {
                    _state.value = ChatUiState(
                        models = _state.value.models,
                        modes = _state.value.modes,
                        selectedModel = _state.value.selectedModel,
                        selectedMode = _state.value.selectedMode,
                    )
                }
                "/compact" -> {
                    val id = _state.value.sessionId ?: return@launch
                    try {
                        repository.compactSession(id)
                        loadInitial(id)
                    } catch (e: Exception) {
                        _state.update { it.copy(error = repository.friendlyError(e)) }
                    }
                }
                "/help" -> {
                    _state.update {
                        it.copy(
                            inputText = "",
                            messages = it.messages + UiMessage(
                                role = "assistant",
                                content = "可用命令：\n/new - 新建对话\n/compact - 压缩历史\n/sessions - 查看最近会话\n/help - 帮助",
                            ),
                        )
                    }
                }
                "/sessions" -> {
                    try {
                        val sessions = repository.getSessions(limit = 8)
                        val list = sessions.joinToString("\n") { s -> "• ${s.title} (${s.id.take(8)}…)" }
                        _state.update {
                            it.copy(
                                inputText = "",
                                messages = it.messages + UiMessage(role = "assistant", content = "最近会话：\n$list"),
                            )
                        }
                    } catch (e: Exception) {
                        _state.update { it.copy(error = repository.friendlyError(e)) }
                    }
                }
                else -> _state.update { it.copy(inputText = "") }
            }
        }
    }

    fun respondConsent(allowed: Boolean) {
        val consent = _state.value.consent ?: return
        viewModelScope.launch {
            try {
                repository.respondConsent(consent.requestId, allowed)
                _state.update { it.copy(consent = null) }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun dismissConsent() { _state.update { it.copy(consent = null) } }

    // ── ask_user / wait_for_user 交互卡片 ──────────────────────────────────

    /** 收到 ask_user 事件：设置卡片并启动倒计时（超时自动回传 default；空 options 见下）。 */
    private fun startAskUserCountdown(info: AskUserInfo) {
        askUserCountdownJob?.cancel()
        _state.update { it.copy(askUser = info, askUserRemaining = info.timeout) }
        askUserCountdownJob = viewModelScope.launch {
            var remaining = info.timeout
            while (remaining > 0) {
                kotlinx.coroutines.delay(1000)
                // 卡片已被响应/替换则停止
                if (_state.value.askUser?.requestId != info.requestId) return@launch
                remaining -= 1
                _state.update { it.copy(askUserRemaining = remaining) }
            }
            if (_state.value.askUser?.requestId == info.requestId) {
                if (info.options.isEmpty()) {
                    // 空 options：后端校验回传值必须在 options 内，任何回传都会 400，
                    // 回传失败还会恢复卡片（无按钮可点）导致卡死。超时只清卡片不回传，
                    // 由后端 ask-user 自身的超时机制走默认值。
                    _state.update { it.copy(askUser = null) }
                } else {
                    respondAskUser(info.default)
                }
            }
        }
    }

    /** 收到 wait_for_user 事件：设置卡片并启动倒计时（超时自动回传 "timeout"）。 */
    private fun startWaitForUserCountdown(info: WaitForUserInfo) {
        waitForUserCountdownJob?.cancel()
        _state.update { it.copy(waitForUser = info, waitForUserRemaining = info.timeout) }
        waitForUserCountdownJob = viewModelScope.launch {
            var remaining = info.timeout
            while (remaining > 0) {
                kotlinx.coroutines.delay(1000)
                if (_state.value.waitForUser?.requestId != info.requestId) return@launch
                remaining -= 1
                _state.update { it.copy(waitForUserRemaining = remaining) }
            }
            if (_state.value.waitForUser?.requestId == info.requestId) {
                respondWaitForUser("timeout")
            }
        }
    }

    /**
     * ask_user 卡片回传选择；失败恢复卡片可重试（agent 在后端一直等到超时）。
     *
     * 原子认领防双重回传：倒计时归零与用户点击竞态时（cancel 是协作式的，拦不住已越过挂起点的
     * 倒计时协程），先通过 CAS 把卡片从 state 摘除的一方才发请求，后到的一方读到 null 直接返回。
     */
    fun respondAskUser(value: String) {
        val askUser = _state.value.askUser ?: return
        var claimed = false
        _state.update {
            if (it.askUser?.requestId == askUser.requestId) {
                claimed = true
                it.copy(askUser = null)
            } else {
                it
            }
        }
        if (!claimed) return
        askUserCountdownJob?.cancel()
        viewModelScope.launch {
            try {
                repository.respondAskUser(askUser.requestId, value)
            } catch (e: Exception) {
                // 失败恢复卡片以便重试；仅当期间没有新卡片到达时才恢复
                _state.update { if (it.askUser == null) it.copy(askUser = askUser) else it }
                _state.update { it.copy(error = "选择回传失败，请重试：${repository.friendlyError(e)}") }
            }
        }
    }

    /** wait_for_user 卡片回传："done" / "cancel" / 用户文本 / "timeout"。认领防双重回传同 [respondAskUser]。 */
    fun respondWaitForUser(value: String) {
        val waitForUser = _state.value.waitForUser ?: return
        var claimed = false
        _state.update {
            if (it.waitForUser?.requestId == waitForUser.requestId) {
                claimed = true
                it.copy(waitForUser = null)
            } else {
                it
            }
        }
        if (!claimed) return
        waitForUserCountdownJob?.cancel()
        viewModelScope.launch {
            try {
                repository.respondWaitForUser(waitForUser.requestId, value)
            } catch (e: Exception) {
                _state.update { if (it.waitForUser == null) it.copy(waitForUser = waitForUser) else it }
                _state.update { it.copy(error = "回传失败，请重试：${repository.friendlyError(e)}") }
            }
        }
    }

    fun uploadAttachment(data: ByteArray, filename: String) {
        viewModelScope.launch {
            try {
                val path = repository.uploadAttachment(data, filename)
                val prefix = "[Uploaded file: $filename at $path]"
                _state.update { it.copy(inputText = prefix + if (it.inputText.isBlank()) "" else "\n${it.inputText}") }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun onOnboardingChange(agentName: String, userInfo: String) {
        _state.update { it.copy(agentName = agentName, userInfo = userInfo) }
    }

    fun completeOnboarding() {
        viewModelScope.launch {
            try {
                repository.completeOnboarding(_state.value.agentName, _state.value.userInfo)
                _state.update { it.copy(showOnboarding = false) }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun dismissOnboarding() { _state.update { it.copy(showOnboarding = false) } }
    fun clearError() { _state.update { it.copy(error = null) } }
}
