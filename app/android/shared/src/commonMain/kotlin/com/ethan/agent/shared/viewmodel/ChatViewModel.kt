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
import com.ethan.agent.core.model.UserIdentity
import com.ethan.agent.core.model.WaitForUserInfo
import com.ethan.agent.core.model.ambiguousCandidates
import com.ethan.agent.core.model.fullId
import com.ethan.agent.core.model.isAmbiguous
import com.ethan.agent.core.model.resolveModel
import com.ethan.agent.shared.AppLifecycleBus
import com.ethan.agent.shared.EthanRepository
import com.ethan.agent.shared.UiMessage
import com.ethan.agent.shared.UiMessageImage
import com.ethan.agent.shared.ShareBus
import kotlinx.datetime.Clock
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
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

/**
 * 与后端的连接状态。**这是界面上「离线」的唯一来源** —— 判定依据只有一条：
 * 网络路径是否还能用（探活结果 / SSE 流是否还活着），不是「有没有在生成」。
 *
 * 早期版本只有 [Idle] / [Streaming] / [Reconnecting] / [Disconnected] 四态，且
 * `Disconnected` 只在**一次生成失败**时写入 —— 没有生成在跑时永远是 `Idle`，
 * 于是「切回前台后发现服务端已经连不上」没有任何状态可以表达。现在补一个
 * [Offline] 专门表示「探活失败」，并把 `Disconnected` 收窄为「生成中断且重连失败」。
 */
enum class ConnectionState {
    /** 空闲且已确认可达（或尚未探活）。 */
    Idle,

    /** 正在流式接收。 */
    Streaming,

    /** 正在重连 / 正在探活，界面上是「重连中…」。 */
    Reconnecting,

    /**
     * 生成流断了、且自动重连也没接回来。此时 run 可能还在服务端跑，
     * 用户可以点「重连」手动再试（区别于 [Offline]：那条路走的是整机不可达）。
     */
    Disconnected,

    /**
     * 服务端不可达（探活失败）。与 [Disconnected] 分开是因为**恢复方式不同**：
     * 这里没有「重连当前 run」可言，只能等网络回来 / 用户改地址。
     */
    Offline,
}

/**
 * 生成流的自动重连参数。
 *
 * 指数退避 1s / 2s / 4s…，封顶 [MAX_RECONNECT_DELAY_MS]。退避只用于「同一轮生成内
 * 反复接不上」的场景；一次成功即清零，避免把偶发抖动累积成越来越长的等待。
 */
private const val MAX_AUTO_RECONNECT = 4
private const val INITIAL_RECONNECT_DELAY_MS = 1_000L
private const val MAX_RECONNECT_DELAY_MS = 30_000L

/** 第 [attempt] 次（0 起）重连前等待的毫秒数：1s → 2s → 4s → 8s… 封顶 30s。 */
private fun reconnectDelayMs(attempt: Int): Long {
    var delay = INITIAL_RECONNECT_DELAY_MS
    repeat(attempt) {
        delay = (delay * 2).coerceAtMost(MAX_RECONNECT_DELAY_MS)
    }
    return delay
}

/**
 * 前台探活的最小间隔。
 *
 * 手机上「切回前台」发生得非常频繁 —— 下拉通知栏、切个 App 回来、甚至解锁屏幕都会触发。
 * 每次都打一次 /health 既费电又会把服务端打出一串无用请求。5 秒内的重复触发直接丢弃：
 * 真断线不会在 5 秒内自愈，而用户来回切屏的体感延迟几乎为零。
 */
private const val FOREGROUND_PROBE_DEBOUNCE_MS = 5_000L

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
    /**
     * 最近一次探活的结论：false = 服务端不可达。
     *
     * 与 [connectionState] 并存而不是合并：探活是**周期性**的，而 connectionState 还带着
     * 「正在生成」「正在重连」这些瞬时含义。true 时不显示任何东西，false 时界面挂一条离线提示。
     */
    val reachable: Boolean = true,
    /** 正在探活（前台探活进行中），用于避免重复发起。 */
    val isProbing: Boolean = false,
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
    /**
     * 用户身份（显示名 / 头像），用于用户气泡的头像与名字行。
     *
     * 未设置时是空对象 —— 气泡回落成首字母 / 人形图标，不会因为拿不到而空一块。
     */
    val userIdentity: UserIdentity = UserIdentity(),
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

    /**
     * [observeDraftPersistence] 最近一次落盘的 (槽位 key, 文本)。
     *
     * key 用来判「会话槽位切了没」：切了就说明旧槽位的草稿已经失去意义（要么刚发出去、
     * 要么属于上一个会话），要显式删掉。
     * 文本用来做写盘去重 —— 值没变、槽位没变就不必再打一次磁盘。
     */
    private var lastSavedKey: String? = null
    private var lastSavedText: String? = null

    /**
     * 最近一次被 [clearDraft] / [loadInitial] 消费掉的 (槽位 key, 文本)，即「已经交给
     * 输入框、或已经发出去」的那份草稿。
     *
     * 必须记下来，不能靠「文本是不是空的」来判：草稿在恢复 / 发送那一刻就已经离开了
     * 磁盘语义，但**旧 VM 的订阅者手里还攥着它**，debounce 一到就会拿陈旧 state 把它
     * 写回磁盘 —— 下次打开 APP 又冒出来，这就是线上「输入框残留上一次 query」的成因。
     *
     * 匹配「槽位 + 文本」两者而不是只比 key：同一会话在消费之后用户还会接着打下一段
     * 草稿，那是要正常落盘的，只按 key 拦会把该会话后续的草稿全丢掉。
     * 比较用 trim 后的正文 —— 发送路径传进来的是 `inputText.trim()`，而订阅者看到的是
     * 未 trim 的原值，两者必须归一化后才能对上。
     */
    private var consumedKey: String? = null
    private var consumedText: String? = null

    /** 前台探活的串行化闸门：同一时刻只允许一次探活在飞。 */
    private var probeJob: Job? = null

    /**
     * 离线后的持续探活循环（独立于 [probeJob]）。
     *
     * 单独放一个 job 而不是复用 [probeJob]：这个循环要按退避一直重试到服务端回来，
     * 长的可能挂几个小时。如果它占着 [probeJob]，[probeAndRecover] 的早退判断
     * （`if (probeJob?.isActive == true) return`）会把之后所有的前台事件全部吞掉，
     * 用户切回来多少次都不会再探活一次。
     */
    private var onlineProbeJob: Job? = null

    /** 上一次前台探活的时刻（毫秒），用于 [FOREGROUND_PROBE_DEBOUNCE_MS] 去抖。 */
    private var lastProbeAtMs: Long = 0

    init {
        loadInitial(sessionId)
        observeSharedText()
        observeAutoConsent()
        observeDraftPersistence()
        observeAppLifecycle()
    }

    /**
     * App 切回前台时主动探活 + 接流。
     *
     * 这是「放一会儿就自己变离线」的主修复点。两种断线都要处理：
     *   1. **被挂起**：进程在后台被冻结，`onPause` 之后没有任何回调告诉我们连接没了。
     *      手里那个 `isStreaming = true` 是陈旧的死状态 —— 探活能发现服务端还好着，
     *      于是只需要重新接流（resume），界面立刻回到在线。
     *   2. **真断线**：服务端重启 / 网络换了。探活失败 → 标记 [ConnectionState.Offline]，
     *      并起一个带退避的探活循环，直到服务端回来为止（回来即自动清掉离线态）。
     *
     * 去抖的理由见 [FOREGROUND_PROBE_DEBOUNCE_MS]：切后台再回来在手机上是高频动作。
     */
    private fun observeAppLifecycle() {
        viewModelScope.launch {
            AppLifecycleBus.foregroundEvents.collect {
                val now = Clock.System.now().toEpochMilliseconds()
                if (now - lastProbeAtMs < FOREGROUND_PROBE_DEBOUNCE_MS) return@collect
                lastProbeAtMs = now
                probeAndRecover()
            }
        }
    }

    /**
     * 探活一次；失败则进入离线态并启动后台探活循环，成功则恢复并接回进行中的 run。
     *
     * 并发保护：探活是「串行化 + 合并」的 —— 已经在飞就复用那一次，不排队。
     * 否则用户快速切几次屏会叠出一串探活，最后到达的响应可能比最先到的还早，
     * 把已恢复的在线态又盖回离线（经典的乱序覆盖）。
     */
    private fun probeAndRecover() {
        if (probeJob?.isActive == true) return
        probeJob = viewModelScope.launch {
            _state.update { it.copy(isProbing = true) }
            val healthy = try {
                repository.isServerHealthy()
            } catch (e: Exception) {
                if (e is kotlinx.coroutines.CancellationException) throw e
                false
            }
            _state.update { it.copy(isProbing = false, reachable = healthy) }

            if (healthy) {
                // 探活通了：先把断线态收回在线，再尝试接回那轮还在跑的生成。
                //
                // 顺序很重要 —— `markOnline()` 会把 connectionState 从
                // Disconnected/Offline 收成 Idle，而它**不动 isStreaming**。
                // 所以下面判「有没有活要接」必须看 isStreaming（那才是「本地认为
                // 还有一轮生成在跑」的真实来源），不能看 connectionState。
                val hadActiveRun = _state.value.isStreaming
                markOnline()
                if (hadActiveRun) resumeStreamIfNeeded(force = true)
            } else {
                markOffline()
            }
        }
    }

    /**
     * 进入离线态，并**确保**后台探活循环在跑。
     *
     * 收敛成一个方法而不是各处直接写 `connectionState = Offline`：离线态一旦进入就必须
     * 有人负责把它带回来，否则界面会永久卡在「网络已断开，正在自动重连…」而实际什么都
     * 没在重试（横幅按设计不给按钮，用户连手动重试都点不到）。
     * 之前有三条独立路径写离线态，只有探活那条顺带起了循环 —— 生成失败/重连失败那两条
     * 会把用户丢进这个死状态。现在只留这一个入口，忘记起循环在结构上就不可能了。
     *
     * 循环放**独立** job（[onlineProbeJob]）而不是 [probeJob]：它要长时间退避重试，
     * 而 probeJob 是「一次探活」的闸门，让它一直占着会让后续前台事件全部早退。
     */
    private fun markOffline() {
        _state.update { it.copy(connectionState = ConnectionState.Offline, reachable = false) }
        startOnlineProbeLoop()
    }

    /**
     * 离线后持续探活，直到恢复为止（退避 1s/2s/4s… 封顶 30s）。
     *
     * 不设「最大重试次数」：这里的重试对象是「用户把手机掏出电梯 / 走出地库」这种
     * 恢复时间完全不可知的外因，放弃重试等于让用户回来还得手动操作一次。
     * 循环本身极轻（一次 GET），且用户离开页面时随 viewModelScope 一起取消。
     *
     * 幂等：已经有一个循环在跑就直接返回，避免每次前台事件都叠一个新的。
     */
    private fun startOnlineProbeLoop() {
        if (onlineProbeJob?.isActive == true) return
        onlineProbeJob = viewModelScope.launch {
            var attempt = 0
            while (true) {
                delay(reconnectDelayMs(attempt))
                // 已经被别处（另一次探活 / 成功的 resume）恢复了 —— 退出，别重复探。
                if (_state.value.reachable) return@launch
                val healthy = try {
                    repository.isServerHealthy()
                } catch (e: Exception) {
                    if (e is kotlinx.coroutines.CancellationException) throw e
                    false
                }
                if (healthy) {
                    val hadActiveRun = _state.value.isStreaming
                    markOnline()
                    if (hadActiveRun) resumeStreamIfNeeded(force = true)
                    return@launch
                }
                attempt += 1
            }
        }
    }

    /**
     * 把界面从各种「断线态」收回在线态。
     *
     * **只回收断线态**（Offline / Disconnected）—— 正在生成（Streaming）或正在重连
     * （Reconnecting）时不能碰：那两个状态由各自的流程负责推进，这里覆盖会把
     * 「重连中…」的提示抹掉，用户看不到正在发生的事情。
     */
    private fun markOnline() {
        _state.update {
            if (it.connectionState == ConnectionState.Offline ||
                it.connectionState == ConnectionState.Disconnected
            ) {
                // 断线态收干净了，当初为它显示的错误文案也一并清掉，
                // 否则会留下一条「连接断开」的红字挂在一个已经恢复的界面上。
                it.copy(connectionState = ConnectionState.Idle, reachable = true, error = null)
            } else {
                it.copy(reachable = true)
            }
        }
    }

    /**
     * 接回进行中的生成。
     *
     * @param force 探活刚证明服务端是通的：此时**跳过 [isStreaming] 检查**。
     *   后台被挂起时 `isStreaming` 会停在 true（陈旧状态，没有任何回调会清它），
     *   而 `resumeStream()` 的第一句就是 `if (isStreaming) return` —— 不 force 的话
     *   这条「接回断流」的路会被自己的陈旧状态挡在门外，界面就永久卡在离线/断线。
     */
    private fun resumeStreamIfNeeded(force: Boolean = false) {
        if (_state.value.sessionId == null) return
        if (_state.value.isResuming) return
        if (!_state.value.reachable) return
        if (!force && _state.value.isStreaming) return
        // 走 force 时先清掉那个陈旧的 isStreaming，让 resumeStream 放行。
        if (force && _state.value.isStreaming) {
            _state.update { it.copy(isStreaming = false) }
        }
        resumeStream()
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
            //
            // 恢复前必须先把这个会话槽位的草稿读走并**立刻从持久层删掉**
            // （`saveDraft(sessionId, "")` 即 remove key）：否则这条草稿会在磁盘上
            // 一直活着，而输入框只在 inputText 为空时才回填，用户一清空输入框它又冒
            // 出来，表现成「输入框里老是残留上一次的 query」。
            // 读取放在最前面是因为下面一长串 `launch` 里任何一处清了 inputText，
            // 之后的读都可能读不到 —— 先把值攥在手里，再开始写。
            launch {
                try {
                    val saved = repository.draft(sessionId)
                    if (saved.isNotBlank()) {
                        // 先登记「这份草稿已消费」（把值攥在手里、同时记下来），再删盘上的
                        // 记录，最后才回填输入框。顺序不能换：登记必须发生在删除之前，
                        // 否则旧 VM 的订阅者可能在两者之间把这份文本写回磁盘。
                        // 登记与删除之间没有挂起点（同在 Main.immediate），不会被打断。
                        consumedKey = draftKeyOf(sessionId)
                        consumedText = saved
                        repository.saveDraft(sessionId, "")
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

            // 用户身份（气泡头像 / 名字行）。与设置页共用同一个接口，改完回来 pull 一次
            // 就能看到新头像 —— 拿不到就保持空对象，气泡回落成首字母，不当成错误。
            launch {
                try {
                    val identity = repository.getUserIdentity()
                    _state.update { it.copy(userIdentity = identity) }
                } catch (_: Exception) { }
            }

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
     *
     * **不写空草稿**：`saveDraft(sid, "")` 会删掉 key，而下面已经为「切 key 时清旧槽位」
     * 单独留了一处显式清理。空文本由「发送路径显式 clearDraft」和「loadInitial 消费即删」
     * 两处保证，这里就不必再跟着每次 inputText 归零打一遍磁盘。
     * （历史版本在这里无条件写 —— 连同「读草稿 → 写回」竞争一起，会把已恢复的草稿重新
     * 落盘，用户一清空输入框它就再冒出来。）
     */
    private fun observeDraftPersistence() {
        viewModelScope.launch {
            combine(_state.map { it.inputText }, _state.map { it.sessionId }) { text, sid -> text to sid }
                .debounce(400)
                .collect { (text, sid) ->
                    val key = draftKeyOf(sid)
                    val prevKey: String? = lastSavedKey
                    if (text == lastSavedText && key == prevKey) return@collect
                    // 会话 id 从 `@new` 迁到真实 id、或切到别的会话：旧槽位里的草稿
                    // 已经失去意义（要么刚发出去、要么属于上一个会话），显式清掉。
                    // 不依赖「空文本才清」——恢复期间读到的内容此刻还在 state 里，
                    // 按文本判空会漏清（见上面「不写空草稿」的说明）。
                    if (prevKey != null && prevKey != key) {
                        runCatching { repository.saveDraft(sessionIdOf(prevKey), "") }
                    }
                    lastSavedKey = key
                    lastSavedText = text
                    // 被消费过的槽位、且正文仍是当初被消费的那一份 —— 说明这是「陈旧
                    // state 的写回」（旧 VM 订阅者手上那份恢复了却没清掉的值，debounce
                    // 到点），不能再落盘把它复活。只拦这一种：用户在消费之后接着打的
                    // **新**草稿必须能存下来，所以必须比对正文，不能只比槽位。
                    // 归一化 trim：发送路径传进 clearDraft 的是 `inputText.trim()`。
                    val isStaleWriteBack = key == consumedKey && text.trim() == consumedText
                    if (!isStaleWriteBack) {
                        // 不是陈旧写回 —— 消费标记已完成使命，清掉；正文为空则交给
                        // 「切槽位」那条路径去删，这里不写空串（见本函数头部说明）。
                        consumedKey = null
                        consumedText = null
                        if (text.isNotBlank()) runCatching { repository.saveDraft(sid, text) }
                    }
                }
        }
    }

    /**
     * 清掉某个会话槽位的持久化草稿，并把它登记为「已消费」（见 [consumedKey]）。
     *
     * 调用点：[sendInternal]（消息发出去 / 转成排队消息之后）与 `/new`。
     *
     * 不能只靠「inputText 归零 → 订阅者把空串写下去」：那条链路会经过 400ms 的 debounce，
     * 期间进程被杀 / 被回收，输入框下次打开就又把刚发出去的那条 query 回填了 ——
     * 也就是「发送过的历史 query 被当成草稿恢复」。
     *
     * @param text 被消费掉的那份草稿正文。写回守卫靠它区分「陈旧的写回」和「用户新打的
     *   草稿」，传错会让守卫失效或误伤，调用方必须传实际消费掉的那一份。
     */
    private suspend fun clearDraft(sessionId: String?, text: String) {
        runCatching { repository.saveDraft(sessionId, "") }
        consumedKey = draftKeyOf(sessionId)
        consumedText = text
    }

    private fun draftKeyOf(sid: String?): String = sid ?: "@new"

    private fun sessionIdOf(key: String): String? = if (key == "@new") null else key

    override fun onCleared() {
        super.onCleared()
        // 页面销毁时 debounce 窗口里的那次写会随 viewModelScope 一起被取消 ——
        // 用独立作用域把最后一份草稿补上，否则「打完字立刻返回」会丢。
        // 空文本不补写：那等于删 key，而订阅者已经为「切槽位」显式清过了。
        val text = _state.value.inputText
        if (text.isBlank()) return
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

    /** 发送消息：流式发送中则排队，否则普通发送 */
    fun sendMessage() {
        val current = _state.value
        sendInternal(current.inputText.trim(), current.pendingImages, fromQueue = false)
    }

    /**
     * 统一发送路径。[fromQueue] = 出队直发（drainQueue 调用）：不碰输入框 ——
     * 那里可能是用户在生成期间打的新草稿，覆盖等于丢字（web 出队也不经过输入框），
     * 也不能把草稿挂的 quote 误带给排队的消息。
     */
    private fun sendInternal(text: String, images: List<PendingImage>, fromQueue: Boolean) {
        if (text.isEmpty() && images.isEmpty()) return
        val current = _state.value
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
            // 内容已经变成排队消息，不再是草稿 —— 立刻删掉持久化记录（debounce 不可靠）。
            // `text.isNotBlank()` 同 sendInternal：只有空白的内容不当成草稿删。
            if (text.isNotBlank()) {
                viewModelScope.launch { clearDraft(current.sessionId, text) }
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
            val userMessage = UiMessage(
                role = "user", content = text,
                // 出队直发不带 quote：草稿上挂的 quote 属于用户正在写的那条，不能误带给排队的消息
                quote = if (fromQueue) null else current.quote,
                createdAt = Clock.System.now().toEpochMilliseconds() / 1000, images = uiImages,
            )
            _state.update {
                it.copy(
                    // 出队直发不碰输入框（可能是用户正在打的新草稿）
                    inputText = if (fromQueue) it.inputText else "",
                    pendingImages = if (fromQueue) it.pendingImages else emptyList(),
                    quote = if (fromQueue) it.quote else null,
                    messages = it.messages + userMessage,
                    isStreaming = true,
                    connectionState = ConnectionState.Streaming,
                    error = null,
                )
            }
            // 清掉「已发出去的那条 query」，否则它下次打开 APP 还会被回填成 draft。
            // 不靠「inputText 归零 → 订阅者写空串」那条链路：它要过 400ms 的 debounce，
            // 进程在窗口里被杀就清不掉了（这正是线上残留的来源），所以这里显式删（幂等）。
            //
            // 删完立刻把**当前**输入框内容（流式期间用户接着打的那段）补写一份，
            // 它是真正的「未发送草稿」：此刻它既不在输入框里（已被清空）、也没被订阅者
            // 落盘（debounce 还没到），不补写就等于丢字。出队直发没动输入框，跳过。
            //
            // 两个条件缺一不可：`text.isNotBlank()` —— 发送传进来的是 trim 过的内容，
            // 用户敲空白/误触发送时不该把已有草稿删掉；补写的 `remaining` 天然是非空白的
            // （含空白就交给订阅者去删）。
            val remainingDraft = _state.value.inputText
            if (!fromQueue && text.isNotBlank()) {
                clearDraft(current.sessionId, text)
                if (remainingDraft.isNotBlank()) {
                    runCatching { repository.saveDraft(current.sessionId, remainingDraft) }
                }
            }

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
                    // 跑完即证明连接是通的 —— 把离线态一并清掉
                    // （用户可能是在离线提示还挂着的时候重试并成功的）。
                    _state.update { it.copy(connectionState = ConnectionState.Idle, reachable = true) }
                    // 正常跑完，放行队首
                    drainQueue()
                } catch (e: Exception) {
                    // SSE 断连后自动重连（指数退避），失败才显示横幅
                    val reconnected = autoReconnect(sessionId, assistantIndex)
                    if (!reconnected) {
                        // 失败收场不 drain：队列原样保留给用户处理。
                        //
                        // autoReconnect 已经判过「是整机不可达（Offline）还是 run 接不回来
                        // （Disconnected）」，这里只在它没动过状态时补一个 Disconnected ——
                        // 否则会把 Offline 覆盖掉，用户看到「已断开 + 一个重连按钮」，
                        // 而真正的问题是网络根本不通。
                        if (_state.value.connectionState != ConnectionState.Offline) {
                            _state.update { it.copy(connectionState = ConnectionState.Disconnected, error = repository.friendlyError(e)) }
                        }
                        _state.update { it.copy(isStreaming = false) }
                    } else {
                        // 重连后接续跑完，同样放行队首
                        drainQueue()
                    }
                }
                // 用户主动停止（stopStreaming 取消本 job）走不到任何 drain：队列保留
            }
        }
    }

    /** 本轮生成正常结束后取出队首消息自动发出 */
    private fun drainQueue() {
        val state = _state.value
        val next = state.queuedMessages.firstOrNull() ?: return
        // 模型歧义未解时先不出队：sendInternal 会早退，出队即丢；留在队列里等
        // 用户选完模型再发（下一条消息跑完后会再次 drain）
        if (state.modelAmbiguous) return
        _state.update { it.copy(queuedMessages = it.queuedMessages - next) }
        // 直发，不经过输入框：输入框里可能是用户在生成期间打的新草稿，覆盖等于丢字
        sendInternal(next.text, next.images, fromQueue = true)
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

    /**
     * App 从后台恢复时调用，尝试接回进行中的 SSE 流。204 = 无活跃 run，静默返回。
     *
     * 直接调用（UI、外部入口）会被 [isStreaming] 挡住，这是对的：用户不该在
     * 生成正常跑着的时候手动再开一条流。内部的「探活成功后接回」走
     * [resumeStreamIfNeeded]，它在下去之前会先把陈旧的 `isStreaming` 清掉。
     */
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
            val localContent = if (reuseLast) msgs.getOrNull(lastIdx)?.content.orEmpty() else ""
            try {
                collectSseStream(
                    flow = repository.resumeStream(
                        sessionId,
                        hasProgress = localContent.isNotEmpty(),
                    ),
                    assistantIndex = assistantIndex,
                    onFirstEvent = { gotAnyEvent = true },
                    // 复用旧气泡时必须带上它已有的正文（app 切回前台、rotating 等场景），
                    // 否则回放会把已渲染的内容覆盖掉 —— 见 appendContent 的说明。
                    localContent = localContent,
                )
                // 接上了 → 连接是通的，离线态清掉。
                _state.update { it.copy(connectionState = ConnectionState.Idle, reachable = true) }
            } catch (e: Exception) {
                // 自动重连：曾经收到过事件（说明 run 仍活跃）、或本地已经有渲染进度
                // （说明这是一次「接续」而不是「接一条还没存在的流」）时尝试。
                //
                // 后者是后台挂起后的关键场景：进程被冻结时第一次 resume 往往直接失败，
                // 而本地气泡里已经有半截正文 —— 早先只按 gotAnyEvent 判，这种情况会
                // 被直接判成 Disconnected，用户回来看到的就是「已断开」且不再自愈。
                if (gotAnyEvent || localContent.isNotEmpty()) {
                    val reconnected = autoReconnect(sessionId, assistantIndex)
                    if (!reconnected && _state.value.connectionState != ConnectionState.Offline) {
                        _state.update { it.copy(connectionState = ConnectionState.Disconnected, error = repository.friendlyError(e)) }
                    }
                } else {
                    // 首次就没接上：区分「服务端不可达」和「run 已结束」。
                    // 204（无活跃 run）走的是空流、不抛异常，所以能走到这里的失败都是真错误。
                    if (e !is com.ethan.agent.core.network.ApiException) {
                        markOffline()
                    } else {
                        _state.update { it.copy(connectionState = ConnectionState.Disconnected, error = repository.friendlyError(e)) }
                    }
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
     * 断连后自动重连（指数退避 1s/2s/4s/8s…，封顶 30s）。
     *
     * 返回 true 表示成功接回流，false 表示全部重试失败或 run 已结束。
     *
     * 与 [observeAppLifecycle] 的分工：这里修的是「生成进行中、流断了」；那条路修的是
     * 「界面停在离线态、需要重新探活」。两者共用同一套退避参数，但触发源不同。
     */
    private suspend fun autoReconnect(sessionId: String, assistantIndex: Int): Boolean {
        for (attempt in 0 until MAX_AUTO_RECONNECT) {
            _state.update { it.copy(connectionState = ConnectionState.Reconnecting) }
            delay(reconnectDelayMs(attempt))
            try {
                var gotEvent = false
                // 带上气泡里已经渲染出来的正文：重连的 backlog 是从头回放的，
                // 交给 appendContent 做「回放 vs 增量」甄别，避免内容被清空重填或重复。
                val localContent = _state.value.messages
                    .getOrNull(assistantIndex)?.content.orEmpty()
                collectSseStream(
                    flow = repository.resumeStream(sessionId, hasProgress = localContent.isNotEmpty()),
                    assistantIndex = assistantIndex,
                    onFirstEvent = { gotEvent = true },
                    localContent = localContent,
                )
                // 204（无活跃 run）返回空流：run 已结束，不算重连成功
                if (!gotEvent) {
                    _state.update { it.copy(connectionState = ConnectionState.Idle, reachable = true) }
                    return false
                }
                _state.update { it.copy(connectionState = ConnectionState.Idle, reachable = true) }
                return true
            } catch (e: Exception) {
                if (e is kotlinx.coroutines.CancellationException) throw e
                // 重连时拿不到 HTTP 响应（连接被拒 / 超时 / DNS 挂了）→ 这是整机不可达，
                // 不是「run 接不回来」。交给后台探活循环去等网络恢复，别在这里空转重试
                // （markOffline 会确保那个循环在跑）。
                //
                // 判据用 `!is ApiException`（commonMain 里没有 java.net 那套异常）：
                // ApiException 意味着**拿到了**响应，服务端是活着的，那才该继续重试。
                if (e !is com.ethan.agent.core.network.ApiException) {
                    markOffline()
                    return false
                }
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
                    // /new 是「彻底开一个新对话、输入框清空」。输入框里那段文字不一定
                    // 已经落过盘（debounce 可能还没到），所以两个槽位都得处理：
                    //   ① 旧会话槽位：里面可能是更早存下的、或刚好落盘的那份文本；
                    //   ② `@new` 槽位：新建会话场景就存在这里。漏了它，下次 `loadInitial(null)`
                    //      会把输入框里那段文字又读回来（「清空输入框 → 重启又冒出来」）。
                    // 两处都要**登记被消费的正文**，否则订阅者随后那次 debounce 写回
                    // 会把它们复活。正文取此刻输入框的值 —— 正是接下来要被丢掉的那份。
                    val previousSessionId = _state.value.sessionId
                    val discarded = _state.value.inputText
                    clearDraft(previousSessionId, discarded)
                    clearDraft(null, discarded)
                    _state.value = ChatUiState(
                        models = _state.value.models,
                        modes = _state.value.modes,
                        selectedModel = _state.value.selectedModel,
                        selectedMode = _state.value.selectedMode,
                        // 身份是「用户级」的，不随会话切换而失效 —— 忘了带上它，
                        // /new 之后气泡头像会突然变回人形图标，直到重新进页面才恢复。
                        userIdentity = _state.value.userIdentity,
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
