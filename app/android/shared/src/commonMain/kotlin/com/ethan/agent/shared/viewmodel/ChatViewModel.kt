package com.ethan.agent.shared.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.AskUserInfo
import com.ethan.agent.core.model.ChatMessage
import com.ethan.agent.core.model.ChatStreamEvent
import com.ethan.agent.core.model.ConsentInfo
import com.ethan.agent.core.model.FileSignature
import com.ethan.agent.core.model.ModeEntry
import com.ethan.agent.core.model.ModelEntry
import com.ethan.agent.core.model.ModelSelection
import com.ethan.agent.core.model.OnboardingStatus
import com.ethan.agent.core.model.Quote
import com.ethan.agent.core.model.ToolStep
import com.ethan.agent.core.model.Usage
import com.ethan.agent.core.model.WaitForUserInfo
import com.ethan.agent.core.model.ambiguousCandidates
import com.ethan.agent.core.model.fullId
import com.ethan.agent.core.model.isAmbiguous
import com.ethan.agent.core.model.resolveModel
import com.ethan.agent.shared.EthanRepository
import com.ethan.agent.shared.UiMessage
import com.ethan.agent.shared.UiMessageImage
import com.ethan.agent.shared.ShareBus
import kotlinx.datetime.Clock
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

enum class ConnectionState { Idle, Streaming, Reconnecting, Disconnected }

private const val MAX_AUTO_RECONNECT = 3
private val RECONNECT_DELAYS_MS = longArrayOf(1_000, 3_000, 10_000)

/** 待发送的图片：内存临时持有，发送后清空。不落 DB。 */
data class PendingImage(
    val dataUrl: String,        // "data:image/png;base64,..." 用于预览
    val base64Data: String,     // 无前缀的 base64，发送时用
    val mediaType: String,      // "image/png" 等
    val filename: String,
)

/**
 * 流式中发送时排队的消息（对齐 Web 的 queued messages）：本轮生成结束后按顺序
 * 自动作为下一轮发出。images 复用 PendingImage，出队时原样走 sendMessage 的完整路径。
 */
data class QueuedMessage(
    val id: Long,
    val text: String,
    val images: List<PendingImage> = emptyList(),
)

data class ChatUiState(
    val sessionId: String? = null,
    val title: String = "新对话",
    val messages: List<UiMessage> = emptyList(),
    val models: List<ModelEntry> = emptyList(),
    val modes: List<ModeEntry> = emptyList(),
    /** 选中模型，复合键 `provider/id`（见 ModelEntry.fullId） */
    val selectedModel: String? = null,
    val selectedMode: String = "",
    val inputText: String = "",
    val pendingImages: List<PendingImage> = emptyList(),
    /** 流式中排队的消息（见 QueuedMessage），输入框上方可见、可删可取回编辑 */
    val queuedMessages: List<QueuedMessage> = emptyList(),
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
    val autoConsent: Boolean = false,
    val serverUrl: String = "",
) {
    /**
     * 旧会话/默认模型存的纯 id/alias 命中多个同名模型：歧义，需用户显式选择。
     * true 时禁用发送，避免静默切到另一个 provider（可能涉及计费/隐私）。
     *
     * **派生而非存储**：models 与 selectedModel 是并行加载的（三条 cached flow 先后到达），
     * 若把它当独立字段写入，先到的流写下的值会被后到的流按旧快照覆盖，出现「该报的没报、
     * 不该报的报死」（见 PR #324 评审）。这里统一从当前 (models, selectedModel) 推导，
     * 任何写入顺序都收敛到同一个结果，与 web 端 `ambiguousLegacy` 的算法一致。
     */
    val modelAmbiguous: Boolean get() = models.isAmbiguous(selectedModel)

    /** 歧义时的同名候选（供 UI 列「一键候选」），非歧义为空。 */
    val ambiguousCandidates: List<ModelEntry> get() = models.ambiguousCandidates(selectedModel)
}

class ChatViewModel(
    private val repository: EthanRepository,
    sessionId: String?,
) : ViewModel() {
    private val _state = MutableStateFlow(ChatUiState())
    val state: StateFlow<ChatUiState> = _state.asStateFlow()
    private var streamJob: Job? = null
    /** 排队消息的自增 id（进程内唯一即可，队列随本轮生成结束而清空） */
    private var queueIdCounter: Long = 0
    private var askUserCountdownJob: Job? = null
    private var waitForUserCountdownJob: Job? = null

    init {
        loadInitial(sessionId)
        observeSharedText()
        observeAutoConsent()
        observeDraftPersistence()
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

    /** 超级权限开关持久化在 DataStore（AppConfig），跨会话/重启保留 */
    private fun observeAutoConsent() {
        viewModelScope.launch {
            try {
                repository.autoConsent.collect { enabled ->
                    if (_state.value.autoConsent != enabled) {
                        _state.update { it.copy(autoConsent = enabled) }
                    }
                }
            } catch (_: Exception) { }
        }
    }

    /**
     * 把任意来源的模型引用（会话存的 model、`agent_settings` 的默认模型）收敛到复合键：
     * 在 [models] 里唯一命中 → 升级为 `provider/id`；歧义（多个 provider 同名）或
     * 模型还没加载到时保持原值不动。
     *
     * 三条并行缓存流都走这一个函数，避免各自实现细微不一致导致状态互相覆盖。
     * 歧义态不在这里存，由 [ChatUiState.modelAmbiguous] 从 (models, selectedModel) 派生。
     */
    private fun upgradeModelRef(models: List<ModelEntry>, ref: String?): String? =
        models.resolveModel(ref)?.fullId ?: ref

    private fun loadInitial(sessionId: String?) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }

            // 恢复该会话上次没发出去的草稿（对齐 Web 的 useInputStore）。
            // 放在最前面且单独 launch：草稿是本地读，不该等网络那一串。
            launch {
                try {
                    val saved = repository.draft(sessionId)
                    if (saved.isNotBlank()) {
                        _state.update { if (it.inputText.isBlank()) it.copy(inputText = saved) else it }
                    }
                } catch (_: Exception) { }
            }

            // 并行加载元数据（cached flow: 先秒出缓存，再网络刷新）
            launch {
                try {
                    repository.cachedModels().collect { models ->
                        _state.update { st ->
                            // 模型列表到达：把当前选中的 ref（可能来自先到的会话/默认模型缓存，
                            // 也可能是旧格式纯 id）收敛一次 —— 唯一命中就升级成复合键，歧义保持原值。
                            st.copy(
                                models = models,
                                selectedModel = st.selectedModel?.let { upgradeModelRef(models, it) }
                                    ?: models.firstOrNull()?.fullId,
                            )
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
                            _state.update { st ->
                                // 默认模型也可能是旧格式纯 id：能唯一解析就升级成复合键，
                                // 解析不出（歧义或模型还没加载到）就保留原值。
                                val raw = settings.defaultModel.ifBlank { st.models.firstOrNull()?.fullId.orEmpty() }
                                    .ifBlank { null }
                                st.copy(
                                    selectedModel = raw?.let { upgradeModelRef(st.models, it) },
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

            // 取 serverUrl 用于拼接历史消息里的图片相对路径
            val serverUrl = repository.config.first().serverUrl
            _state.update { it.copy(serverUrl = serverUrl) }

            // session 详情：cached flow 先秒出缓存数据，再网络刷新
            if (sessionId != null) {
                try {
                    repository.cachedSession(sessionId).collect { session ->
                        _state.update { st ->
                            // session.model 由服务端存储：新会话已是 provider/id 复合键，
                            // 老会话可能是纯 id → 唯一命中就升级，多个同名保持原值等用户选
                            // （歧义态由 ChatUiState.modelAmbiguous 派生，不在这里写）
                            st.copy(
                                sessionId = session.id,
                                title = session.title,
                                selectedModel = upgradeModelRef(st.models, session.model),
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
                                        cards = msg.cards ?: emptyList(),
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
     * 草稿落盘：按 sessionId 各存各的（对齐 Web 的 `useInputStore`）。
     *
     * 实现上**订阅 inputText 的变化**而不是在每个清空点手动调用 —— 输入框被写的地方
     * 有七八处（发送、inject、slash command、分享投递…），逐个补 saveDraft 一定会漏。
     * 看状态变化就没人能漏掉。
     *
     * 攒 400ms 再写：DataStore 是整文件重写 + 内部 Mutex，每敲一个字写一次太费。
     * sessionId 也订阅了 —— 新会话建好后 key 要从 `@new` 迁到真实 id。
     */
    private fun observeDraftPersistence() {
        viewModelScope.launch {
            var lastSavedKey: String? = null
            var lastSavedText: String? = null
            combine(_state.map { it.inputText }, _state.map { it.sessionId }) { text, sid -> text to sid }
                .debounce(400)
                .collect { (text, sid) ->
                    val key = draftKeyOf(sid)
                    val prevKey: String? = lastSavedKey
                    if (text == lastSavedText && key == prevKey) return@collect
                    // 会话 id 变了（新会话刚建好）且旧 key 里没留下内容：把旧 key 清掉，
                    // 否则下次新建会话会把刚才发出去的内容又预填回来。
                    if (prevKey != null && prevKey != key && lastSavedText.isNullOrBlank()) {
                        runCatching { repository.saveDraft(sessionIdOf(prevKey), "") }
                    }
                    lastSavedKey = key
                    lastSavedText = text
                    runCatching { repository.saveDraft(sid, text) }
                }
        }
    }

    private fun draftKeyOf(sid: String?): String = sid ?: "@new"

    private fun sessionIdOf(key: String): String? = if (key == "@new") null else key

    override fun onCleared() {
        super.onCleared()
        // 页面销毁时 debounce 窗口里的那次写会随 viewModelScope 一起被取消 ——
        // 用独立作用域把最后一份草稿补上，否则「打完字立刻返回」会丢。
        val text = _state.value.inputText
        val sid = _state.value.sessionId
        CoroutineScope(Dispatchers.Default).launch {
            runCatching { repository.saveDraft(sid, text) }
        }
    }

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

    /**
     * model 为复合键 `provider/id`（见 ModelEntry.fullId）。
     * 显式选择后歧义态自然消除 —— `modelAmbiguous` 由 (models, selectedModel) 派生，
     * 选中值命中某个 `fullId` 即不再歧义，无需额外清标志位。
     */
    fun onModelSelected(model: String) {
        _state.update { it.copy(selectedModel = model) }
    }
    fun onModeSelected(mode: String) { _state.update { it.copy(selectedMode = mode) } }
    fun toggleAutoConsent() {
        val next = !_state.value.autoConsent
        _state.update { it.copy(autoConsent = next) }
        viewModelScope.launch {
            try { repository.setAutoConsent(next) } catch (_: Exception) { }
            // 会话正在跑时，还要把开关推给那个 run —— 否则开关亮着也不生效，
            // 用户体感是「以开始时的状态为准」。没有活跃 run 时后端 applied=false，
            // 静默忽略即可（偏好已存好，下一次发消息会带上）。
            _state.value.sessionId?.takeIf { it.isNotBlank() }?.let { sid ->
                try { repository.pushAutoConsent(sid, next) } catch (_: Exception) { }
            }
        }
    }

    /** 为文件卡片换 path 级签名（Bearer → ?user=&sig=），供 view/download 直链鉴权 */
    suspend fun signFile(path: String): FileSignature? = try {
        val resp = repository.signFiles(listOf(path))
        resp.signatures[path]?.let { FileSignature(resp.user, it) }
    } catch (_: Exception) { null }
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
        // 模型歧义（旧纯 id 命中多个同名）时不能发：避免静默切到另一个 provider
        if (current.modelAmbiguous) return

        if (current.isStreaming && streamJob?.isActive == true) {
            // 流式中点发送 = 排队（对齐 web）：挂到输入框上方的队列，本轮跑完自动发下一轮。
            // 「补充信息」的即时注入不再占用发送键——它有气泡下方的独立入口（见 ChatScreen
            // 的补充信息行），之前把流式发送全部导去 inject，用户想排队的意图被误伤。
            queueIdCounter += 1
            val item = QueuedMessage(id = queueIdCounter, text = text, images = images)
            _state.update {
                it.copy(
                    queuedMessages = it.queuedMessages + item,
                    inputText = "",
                    pendingImages = emptyList(),
                    quote = null,
                )
            }
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
            // 发出去了就不再是草稿 —— 上面把 inputText 清空后，
            // observeDraftPersistence 会把空串写下去（等于删掉这条记录）。

            var sessionId = current.sessionId
            if (sessionId == null) {
                try {
                    // 落库同样的 fullId：会话表里存的 model 会被「恢复会话」读回来直接发出去，
                    // 存裸 id 等于把同一个 bug 持久化下来。
                    val created = repository.createSession(
                        ModelSelection.effectiveValue(current.models, current.selectedModel)
                            .takeIf { it != ModelSelection.NEED_CHOICE }
                            ?: current.selectedModel,
                        current.selectedMode.ifBlank { null },
                    )
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

            // 发出去之前做最后一道解析：把可能残留的裸 id 升级成 fullId。
            // 前面几处写入（列表默认 / 设置默认 / 会话恢复）都做了升级，但
            // `effectiveValue` 在 models 还没加载完时无法升级，会原样返回裸 id；
            // 这里 models 一定已就绪（sendMessage 依赖它），补这一刀才能保证
            // 后端 `providers/manager.py` 拿到的是 `provider/id`。
            val sendModel = ModelSelection
                .effectiveValue(_state.value.models, _state.value.selectedModel)
                .takeIf { it != ModelSelection.NEED_CHOICE }   // 重名未定：交给后端按原值处理/报错更明确

            streamJob = viewModelScope.launch {
                try {
                    collectSseStream(
                        flow = repository.streamChat(
                            messages = history,
                            model = sendModel,
                            sessionId = sessionId,
                            quote = userMessage.quote,
                            mode = _state.value.selectedMode,
                            autoConsent = _state.value.autoConsent,
                        ),
                        assistantIndex = assistantIndex,
                    )
                    _state.update { it.copy(connectionState = ConnectionState.Idle) }
                } catch (e: Exception) {
                    // SSE 断连后自动重连（指数退避），失败才显示横幅
                    val reconnected = autoReconnect(sessionId, assistantIndex)
                    if (!reconnected) {
                        _state.update { it.copy(isStreaming = false, connectionState = ConnectionState.Disconnected, error = repository.friendlyError(e)) }
                    }
                }
                // 正常跑完（含重连后跑完）就放行队首；失败收场/用户停止（job 被取消，
                // 走不到这里）都不 drain，队列原样保留给用户处理。
                drainQueue()
            }
        }
    }

    /** 本轮生成正常结束后取出队首消息自动发出；失败收场时保留队列不动 */
    private fun drainQueue() {
        val state = _state.value
        if (state.error != null) return
        val next = state.queuedMessages.firstOrNull() ?: return
        _state.update {
            it.copy(
                queuedMessages = it.queuedMessages - next,
                inputText = next.text,
                pendingImages = next.images,
            )
        }
        sendMessage()
    }

    /** 移除排队中的消息（队列 chip 上的 ×） */
    fun queueRemove(id: Long) {
        _state.update { it.copy(queuedMessages = it.queuedMessages.filterNot { q -> q.id == id }) }
    }

    /** 取回排队中的消息到输入框编辑（队列 chip 长按/点击编辑） */
    fun queueEdit(id: Long) {
        val item = _state.value.queuedMessages.firstOrNull { it.id == id } ?: return
        _state.update {
            it.copy(
                queuedMessages = it.queuedMessages - item,
                inputText = item.text,
                pendingImages = item.images,
            )
        }
    }

    /** 运行中向 agent 注入补充信息（聊天页「补充信息」入口）；409 = 无活跃 run，自动降级普通发送 */
    fun injectMessage(text: String) {
        val sessionId = _state.value.sessionId ?: return
        // 不动 inputText：注入框有独立输入区（对齐 web 的 InjectBox），主输入框的草稿不能被误清
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
                    // 复用旧气泡时必须带上它已有的正文（app 切回前台、rotating 等场景），
                    // 否则回放会把已渲染的内容覆盖掉 —— 见 appendContent 的说明。
                    localContent = if (reuseLast) msgs.getOrNull(lastIdx)?.content.orEmpty() else "",
                )
                _state.update { it.copy(connectionState = ConnectionState.Idle) }
            } catch (e: Exception) {
                // 自动重连：仅当曾经收到过事件（说明 run 仍活跃）时尝试
                if (gotAnyEvent) {
                    val reconnected = autoReconnect(sessionId, assistantIndex)
                    if (!reconnected) {
                        _state.update { it.copy(connectionState = ConnectionState.Disconnected, error = repository.friendlyError(e)) }
                    }
                } else {
                    _state.update { it.copy(connectionState = ConnectionState.Disconnected, error = repository.friendlyError(e)) }
                }
            } finally {
                // 仅当追加了新占位且没收到任何事件时才 drop，避免误删复用的旧气泡
                if (!reuseLast && !gotAnyEvent) {
                    _state.update { s -> s.copy(messages = s.messages.dropLast(1)) }
                }
                _state.update { it.copy(isResuming = false, isStreaming = false) }
            }
        }
    }

    /**
     * 断连后自动重连（指数退避 1s/3s/10s）。
     * 返回 true 表示成功接回流，false 表示全部重试失败或 run 已结束。
     */
    private suspend fun autoReconnect(sessionId: String, assistantIndex: Int): Boolean {
        for (attempt in 0 until MAX_AUTO_RECONNECT) {
            _state.update { it.copy(connectionState = ConnectionState.Reconnecting) }
            kotlinx.coroutines.delay(RECONNECT_DELAYS_MS[attempt.coerceAtMost(RECONNECT_DELAYS_MS.lastIndex)])
            try {
                var gotEvent = false
                // 带上气泡里已经渲染出来的正文：重连的 backlog 是从头回放的，
                // 交给 appendContent 做「回放 vs 增量」甄别，避免内容被清空重填或重复。
                val localContent = _state.value.messages
                    .getOrNull(assistantIndex)?.content.orEmpty()
                collectSseStream(
                    flow = repository.resumeStream(sessionId),
                    assistantIndex = assistantIndex,
                    onFirstEvent = { gotEvent = true },
                    localContent = localContent,
                )
                // 204（无活跃 run）返回空流：run 已结束，不算重连成功
                if (!gotEvent) {
                    _state.update { it.copy(connectionState = ConnectionState.Idle) }
                    return false
                }
                _state.update { it.copy(connectionState = ConnectionState.Idle) }
                return true
            } catch (e: Exception) {
                if (e is kotlinx.coroutines.CancellationException) throw e
            }
        }
        return false
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
        /**
         * 断线重连时传入气泡里已有的正文（本地已渲染到的进度）。
         *
         * 重连端点（`GET /chat/{id}/stream` → `_sse_from_run`）会**从头回放**这段 run 的
         * 全部缓冲，而本地 builder 若从空串开始拼，就会出现两个问题：
         *   1. 回放期间气泡被清空再逐字重填，用户看到字「闪没了」；
         *   2. `finally` 用这个不完整/被重写的 builder 覆盖气泡 —— 若回放流在补全之前
         *      结束（run 已 done、缓冲被裁剪），末尾那段内容就永久丢了。
         * 症状就是「最后一个 chunk 的字没打出来」。所以这里带上本地进度，
         * 并在回放时取两者较长者（见 appendContent）。
         */
        localContent: String = "",
    ) {
        val toolSteps = mutableListOf<ToolStep>()
        val cardsCollected = mutableListOf<com.ethan.agent.core.model.FileCard>()
        var usage: Usage? = null
        var content = localContent
        var lastFlushMs = 0L
        var firstEvent = true
        val streamStartMs = Clock.System.now().toEpochMilliseconds()
        var ttfbMs: Long? = null
        var firstContentMs: Long? = null

        /**
         * 合并一个增量 content 事件。
         *
         * 正常续流：重放会从 run 的开头重发整段，因此**不能**直接拼接 —— 那样会把
         * 已经渲染的内容重复一遍（"你好" + 重放的"你好世界" = "你好你好世界"）。
         *
         * 判据：如果服务端这次给的片段正好接在本地已渲染内容的后面（`content` 是
         * `incoming` 的前缀），说明是回放 —— 直接采用服务端的版本（它更权威、
         * 且天然包含本地可能漏掉的部分）。否则才当作真正的增量追加。
         */
        fun appendContent(incoming: String) {
            val current: String = content
            content = when {
                // 回放（含重复回放）：服务端版本覆盖本地，取更长的那份
                incoming.startsWith(current) -> incoming
                // 本地已超前（服务端缓冲被裁剪）：保留本地，忽略这次回放
                current.startsWith(incoming) -> current
                // 真正的新增量
                else -> current + incoming
            }
        }

        fun flush(force: Boolean = false) {
            val now = Clock.System.now().toEpochMilliseconds()
            if (!force && now - lastFlushMs < 50L) return
            lastFlushMs = now
            val snapshot = content
            _state.update { s ->
                val msgs = s.messages.toMutableList()
                if (assistantIndex < msgs.size) msgs[assistantIndex] = msgs[assistantIndex].copy(content = snapshot)
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
                    // event.content 是跨模块的 nullable 属性，编译器不做 smart cast，
                    // 这里先落到局部 val 再用，避免跨模块的 `event.content` 不参与 smart cast
                    event.content != null -> {
                        val chunk = event.content ?: ""
                        if (firstContentMs == null) {
                            firstContentMs = Clock.System.now().toEpochMilliseconds()
                            ttfbMs = firstContentMs!! - streamStartMs
                        }
                        appendContent(chunk)
                        flush()
                        if (_state.value.showScrollToBottom) {
                            _state.update { it.copy(unreadCount = it.unreadCount + 1) }
                        }
                    }
                    event.tool != null -> {
                        val tool = event.tool!!
                        val stepState = event.state ?: "start"
                        // 对齐 web（use-chat-stream.ts 的工具分支）：工具开始时把已累积的
                        // 正文存为该步骤的 thought（工具时间线里展示「调用前的思考」）；
                        // 工具结束时把正文清空——旧文本已进 thought，气泡正文只保留
                        // 最近一段输出，而不是每轮工具之间的文本一直往后堆。
                        val preToolThought = content.trim().takeIf { it.isNotEmpty() }
                        // done/error 事件不回传 thought，而这里是整条重建 step（web 是对象
                        // 展开保留旧字段），所以要从旧 step 把 start 时存的 thought 回填，
                        // 否则一结束 thought 就丢了。
                        val existingIdx = toolSteps.indexOfFirst { event.id != null && it.id == event.id }
                        val existing = if (existingIdx >= 0) toolSteps[existingIdx] else null
                        val step = ToolStep(
                            tool = tool,
                            args = event.args ?: "",
                            state = stepState,
                            durationMs = event.durationMs,
                            genMs = event.genMs,
                            resultPreview = event.resultPreview,
                            resultDetail = event.resultDetail,
                            thought = existing?.thought ?: event.thought ?: preToolThought,
                            intent = event.intent,
                            id = event.id,
                            subSteps = event.subSteps,
                        )
                        if (existingIdx >= 0) toolSteps[existingIdx] = step else toolSteps.add(step)
                        // 工具结束：清空正文（与 web 的 assistantContent = "" 一致）。
                        // 清空后 appendContent 的回放判定依旧自洽——重连回放按同样的
                        // 事件序列重放，done 处同样清空，不会出现正文重复。
                        val clearContent = stepState != "start"
                        if (clearContent) content = ""
                        // 协议假设：服务端 cards 永远随 tool 事件下发（producers.py 把 cards
                        // 挂在 tool 事件上，不存在独立的 cards 事件），故只在此处收集
                        if (event.cards != null) {
                            cardsCollected.addAll(event.cards!!)
                        }
                        _state.update { s ->
                            val msgs = s.messages.toMutableList()
                            if (assistantIndex < msgs.size) msgs[assistantIndex] = msgs[assistantIndex].copy(
                                content = if (clearContent) "" else msgs[assistantIndex].content,
                                toolSteps = toolSteps.toList(),
                                cards = if (cardsCollected.isNotEmpty()) cardsCollected.toList() else msgs[assistantIndex].cards,
                            )
                            s.copy(messages = msgs)
                        }
                    }
                    event.autoConsentDegraded == true -> {
                        // 服务端安全约束：公网来源的 auto_consent 强制降级为逐项弹窗，
                        // 显式提示，避免「开关亮着却仍弹窗」被当成功能坏了
                        _state.update { it.copy(error = "当前经公网访问服务器，超级权限不可用，已降级为逐项确认") }
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
                        cards = if (cardsCollected.isNotEmpty()) cardsCollected.toList() else msgs[assistantIndex].cards,
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
