package com.ethan.agent.ui.chat

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.ChatMessage
import com.ethan.agent.core.model.ChatStreamEvent
import com.ethan.agent.core.model.ConsentInfo
import com.ethan.agent.core.model.ModeEntry
import com.ethan.agent.core.model.ModelEntry
import com.ethan.agent.core.model.OnboardingStatus
import com.ethan.agent.core.model.Quote
import com.ethan.agent.core.model.ToolStep
import com.ethan.agent.core.model.Usage
import com.ethan.agent.data.EthanRepository
import com.ethan.agent.data.UiMessage
import retrofit2.HttpException
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.File
import javax.inject.Inject

enum class ConnectionState { Idle, Streaming, Reconnecting, Disconnected }

data class ChatUiState(
    val sessionId: String? = null,
    val title: String = "新对话",
    val messages: List<UiMessage> = emptyList(),
    val models: List<ModelEntry> = emptyList(),
    val modes: List<ModeEntry> = emptyList(),
    val selectedModel: String? = null,
    val selectedMode: String = "",
    val inputText: String = "",
    val isLoading: Boolean = false,
    val isStreaming: Boolean = false,
    val isResuming: Boolean = false,
    val isStopping: Boolean = false,
    val connectionState: ConnectionState = ConnectionState.Idle,
    val showScrollToBottom: Boolean = false,
    val unreadCount: Int = 0,
    val error: String? = null,
    val consent: ConsentInfo? = null,
    val quote: Quote? = null,
    val onboarding: OnboardingStatus? = null,
    val showOnboarding: Boolean = false,
    val agentName: String = "",
    val userInfo: String = "",
)

@HiltViewModel
class ChatViewModel @Inject constructor(
    private val repository: EthanRepository,
    savedStateHandle: SavedStateHandle,
) : ViewModel() {
    private val _state = MutableStateFlow(ChatUiState())
    val state: StateFlow<ChatUiState> = _state.asStateFlow()
    private var streamJob: Job? = null

    init {
        val sessionId = savedStateHandle.get<String>("sessionId")
        loadInitial(sessionId)
    }

    private fun loadInitial(sessionId: String?) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val models = repository.getModels()
                val modes = repository.getModes()
                val settings = repository.getAgentSettings()
                val onboarding = repository.getOnboardingStatus()

                if (sessionId != null) {
                    val session = repository.getSession(sessionId)
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
                                )
                            },
                        )
                    }
                } else {
                    _state.update {
                        it.copy(selectedModel = settings.defaultModel.ifBlank { models.firstOrNull()?.id })
                    }
                }

                _state.update {
                    it.copy(
                        models = models,
                        modes = modes,
                        onboarding = onboarding,
                        showOnboarding = onboarding.firstTime,
                        isLoading = false,
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun onInputChange(text: String) { _state.update { it.copy(inputText = text) } }
    fun onModelSelected(model: String) { _state.update { it.copy(selectedModel = model) } }
    fun onModeSelected(mode: String) { _state.update { it.copy(selectedMode = mode) } }
    fun setQuote(quote: Quote?) { _state.update { it.copy(quote = quote) } }
    fun clearQuote() { _state.update { it.copy(quote = null) } }
    fun setShowScrollToBottom(show: Boolean) { _state.update { it.copy(showScrollToBottom = show) } }
    fun clearUnread() { _state.update { it.copy(unreadCount = 0) } }

    /** 发送消息：流式发送中则 inject，否则普通发送 */
    fun sendMessage() {
        val current = _state.value
        val text = current.inputText.trim()
        if (text.isEmpty()) return

        if (current.isStreaming && streamJob?.isActive == true) {
            injectMessage(text)
            return
        }

        if (text.startsWith("/")) {
            handleSlashCommand(text)
            return
        }

        viewModelScope.launch {
            val userMessage = UiMessage(role = "user", content = text, quote = current.quote, createdAt = System.currentTimeMillis() / 1000)
            _state.update {
                it.copy(
                    inputText = "",
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

            val history = _state.value.messages.map { ChatMessage(it.role, it.content) }
            val assistantIndex = _state.value.messages.size
            _state.update { it.copy(messages = it.messages + UiMessage(role = "assistant", content = "", isStreaming = true, createdAt = System.currentTimeMillis() / 1000)) }

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
                val isNoActiveRun = (e is HttpException && e.code() == 409) ||
                    (e is com.ethan.agent.core.network.ApiException && e.code == 409)
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
        val streamStartMs = System.currentTimeMillis()
        var ttfbMs: Long? = null
        var firstContentMs: Long? = null

        fun flush(force: Boolean = false) {
            val now = System.currentTimeMillis()
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
                    event.content != null -> {
                        if (firstContentMs == null) {
                            firstContentMs = System.currentTimeMillis()
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
            val totalDurationMs = System.currentTimeMillis() - streamStartMs
            val generationDurationMs = firstContentMs?.let { System.currentTimeMillis() - it }
            _state.update { s ->
                val msgs = s.messages.toMutableList()
                if (assistantIndex < msgs.size) msgs[assistantIndex] = msgs[assistantIndex].copy(
                    isStreaming = false,
                    usage = usage,
                    ttfbMs = ttfbMs,
                    totalDurationMs = totalDurationMs,
                    generationDurationMs = generationDurationMs,
                )
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

    fun uploadAttachment(file: File, filename: String) {
        viewModelScope.launch {
            try {
                val path = repository.uploadFile(file, filename)
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
