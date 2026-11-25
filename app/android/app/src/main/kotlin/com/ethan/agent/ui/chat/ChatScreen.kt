package com.ethan.agent.ui.chat

import androidx.compose.foundation.layout.WindowInsets
import com.ethan.agent.shared.viewmodel.ChatUiState
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.FileSignature
import com.ethan.agent.core.model.Quote
import com.ethan.agent.shared.UiMessage
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import androidx.compose.foundation.gestures.animateScrollBy

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    state: ChatUiState,
    onInputChange: (String) -> Unit,
    onSend: () -> Unit,
    onModelSelected: (String) -> Unit,
    onModeSelected: (String) -> Unit,
    onQuote: (Quote?) -> Unit,
    onUpload: (ByteArray, String) -> Unit,
    onAddImage: (dataUrl: String, base64Data: String, mediaType: String, filename: String) -> Unit,
    onRemoveImage: (Int) -> Unit,
    onConsent: (Boolean) -> Unit,
    onDismissConsent: () -> Unit,
    onAskUserRespond: (String) -> Unit = {},
    onWaitForUserRespond: (String) -> Unit = {},
    onStop: () -> Unit,
    onOnboardingChange: (String, String) -> Unit,
    onCompleteOnboarding: () -> Unit,
    onDismissOnboarding: () -> Unit,
    onClearError: () -> Unit,
    onScrollToBottom: () -> Unit = {},
    onResumeStream: () -> Unit = {},
    onOpenDrawer: () -> Unit = {},
    onToggleAutoConsent: () -> Unit = {},
    onSignFile: suspend (String) -> FileSignature? = { null },
    // 运行中「补充信息」：立即注入当前 run（区别于流式中发送 = 排队）
    onInject: (String) -> Unit = {},
    // 排队消息管理：× 移除 / 点击取回输入框编辑（对齐 Web 的 QueuedMessages）
    onQueueRemove: (Long) -> Unit = {},
    onQueueEdit: (Long) -> Unit = {},
    // 右上角「重新拉取会话最新内容」
    onReloadSession: () -> Unit = {},
) {
    val snackbar = remember { SnackbarHostState() }
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var showPlusSheet by remember { mutableStateOf(false) }
    // 超级权限「关→开」时的二次确认（开启是高危方向，必须让用户明确知道代价）
    var showAutoConsentConfirm by remember { mutableStateOf(false) }
    // 阅读模式（双击气泡进入）：非空时全屏覆盖在聊天页之上
    var readingMessage by remember { mutableStateOf<UiMessage?>(null) }
    var shareDefaultIndex by remember { mutableStateOf<Int?>(null) }
    // 全屏编辑模式（对齐 Web 的「展开为 Markdown 编辑器」）：长文本写作时输入框
    // 只有 5 行上限，展开后占满全屏（Dialog usePlatformDefaultWidth=false）
    var showFullEditor by remember { mutableStateOf(false) }
    // 渐进加载：初始只渲染最后 10 条，向上滚动加载更多
    val pageSize = 10
    var visibleCount by remember { mutableStateOf(pageSize) }
    // 切换会话时重置并滚到底部
    LaunchedEffect(state.sessionId) {
        visibleCount = pageSize
        // 等 recompose 完再滚到底部
        if (state.messages.isNotEmpty()) {
            listState.scrollToItem((state.messages.size.coerceAtMost(pageSize) - 1).coerceAtLeast(0))
        }
    }
    val totalCount = state.messages.size
    val visibleMessages = remember(state.messages, visibleCount) {
        if (totalCount <= visibleCount) state.messages
        else state.messages.subList(totalCount - visibleCount, totalCount)
    }
    val hasMoreMessages = totalCount > visibleCount

    // 新消息到达时保持 visibleCount 同步（避免看不到新消息）
    LaunchedEffect(totalCount) {
        if (totalCount <= pageSize) {
            visibleCount = pageSize
        } else if (visibleCount >= totalCount - pageSize) {
            // 用户已接近看全部，跟进新消息
            visibleCount = visibleCount.coerceAtLeast(totalCount.coerceAtMost(visibleCount + 1))
        }
    }

    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        uri ?: return@rememberLauncherForActivityResult
        val name = queryDisplayName(context, uri)
        val isImage = context.contentResolver.getType(uri)?.startsWith("image/") == true
        if (isImage) {
            copyAndAddImage(context, uri, name, onAddImage)
        } else {
            copyToTempAndUpload(context, uri, name, onUpload)
        }
    }

    // 自动滚到底部（新消息到达且用户已在底部）
    val isAtBottom by remember {
        derivedStateOf {
            val info = listState.layoutInfo
            val last = info.visibleItemsInfo.lastOrNull()
            last == null || last.index >= info.totalItemsCount - 1
        }
    }

    LaunchedEffect(state.messages.size) {
        if (visibleMessages.isNotEmpty()) {
            if (isAtBottom || visibleMessages.size <= pageSize) {
                listState.animateScrollToItem(visibleMessages.lastIndex + if (hasMoreMessages) 1 else 0)
            }
        }
    }

    // 流式输出的跟随滚动：内容在最后一条消息**内部**增长（正文变长 / 工具步骤变多）时
    // 条数不变，上面的 size-effect 不会触发 —— 表现为「得一直手动往下滑才能看到最新输出」
    // （用户反馈 #5）。这里盯住最后一条消息的尾部特征，变化即跟滚。
    // 只在用户本来就贴着底部（isAtBottom）时跟：主动上滑翻历史时不打扰，
    // 跟滚到底后 snapshotFlow 会经 onScrollToBottom() 自动清掉未读计数。
    val lastMessageTailKey = state.messages.lastOrNull()?.let { msg ->
        msg.content.length * 16 + msg.toolSteps.size + msg.cards.size
    } ?: 0

    // 末条消息比视口高时 animateScrollToItem 只能把它**顶对齐**，最新输出仍整段藏在
    // 视口下方 —— 这正是「气泡没有跟随到底部固定」的另一半原因。所以主体改用过冲量
    // 补滚（末项底边超出视口底部的像素），任意高度的消息都能贴住底部；
    // animateScrollToItem 只在末项根本不在屏上时兜底用一次 —— 若每次跟滚都先
    // scrollToItem，视口会被强拉到末项顶部再滚回底部，流式期间就是一路抖动。
    suspend fun followToBottom() {
        val lastIndex = visibleMessages.lastIndex + if (hasMoreMessages) 1 else 0
        val info = listState.layoutInfo
        val visible = info.visibleItemsInfo.lastOrNull()
        if (visible == null || visible.index < lastIndex) {
            listState.animateScrollToItem(lastIndex)
        }
        val fresh = listState.layoutInfo
        val last = fresh.visibleItemsInfo.lastOrNull() ?: return
        val overshoot = last.offset + last.size - fresh.viewportEndOffset
        if (overshoot > 0) listState.animateScrollBy(overshoot.toFloat())
    }

    LaunchedEffect(lastMessageTailKey) {
        if (visibleMessages.isNotEmpty() && isAtBottom) {
            followToBottom()
        }
    }

    // 监听滚动位置，控制"滚到底部"FAB 和未读计数
    LaunchedEffect(listState) {
        snapshotFlow { isAtBottom }.distinctUntilChanged().collect { atBottom ->
            if (atBottom) {
                onScrollToBottom()
            }
        }
    }

    // 说明：App 从后台恢复时的「探活 + 接流」已收敛到 ChatViewModel 的
    // observeAppLifecycle（订阅 AppLifecycleBus，由 MainActivity 的进程级 ON_START 投递）。
    //
    // 这里原先挂了一个 `repeatOnLifecycle(RESUMED) { onResumeStream() }`，两个问题：
    //   1. 它**只**接流、不探活 —— 服务端已经不可达时，它会不停地对着一个死地址重试，
    //      界面却没有任何「离线」表达，这正是「放一会儿自己变离线且回不来」的成因之一；
    //   2. Activity 的 RESUMED 在内部页面跳转时也会触发，比进程级 ON_START 吵得多，
    //      每次跳转都打一次 resume 请求。
    // 现在统一由 ViewModel 去抖后处理（探活通了才接流），这里不再重复触发。
    // 随之一起去掉了 `LocalLifecycleOwner` 与 `repeatOnLifecycle` 的 import。
    // `onResumeStream` 参数保留：断线横幅上的「重连」按钮仍用它（那是用户主动触发，
    // 与这里的自动恢复是两回事）。

    // 「分享到 Ethan」的图片/文件：订阅 pendingUri（而非 LaunchedEffect(Unit) 只跑一次），
    // app 已在前台时再次分享也能触发上传。
    val pendingUri by com.ethan.agent.shared.ShareBus.pendingUri.collectAsState()
    LaunchedEffect(pendingUri) {
        val sharedUri = pendingUri ?: return@LaunchedEffect
        val uri = Uri.parse(sharedUri)
        val name = queryDisplayName(context, uri)
        val isImage = context.contentResolver.getType(uri)?.startsWith("image/") == true
        if (isImage) {
            copyAndAddImage(context, uri, name, onAddImage)
        } else {
            copyToTempAndUpload(context, uri, name, onUpload)
        }
        // 原子消费，避免误清消费期间到达的新分享
        com.ethan.agent.shared.ShareBus.consumeUri(sharedUri)
    }

    ErrorSnackbar(state.error, onClearError, snackbar)

    if (showPlusSheet) {
        ChatOptionsSheet(
            state = state,
            onModelSelected = onModelSelected,
            onModeSelected = onModeSelected,
            onPickFile = { filePicker.launch("*/*") },
            onClose = { showPlusSheet = false },
        )
    }
    ChatInteractionDialogs(
        state = state,
        onOnboardingChange = onOnboardingChange,
        onCompleteOnboarding = onCompleteOnboarding,
        onDismissOnboarding = onDismissOnboarding,
        onConsent = onConsent,
        onDismissConsent = onDismissConsent,
        onAskUserRespond = onAskUserRespond,
        onWaitForUserRespond = onWaitForUserRespond,
    )

    Scaffold(
        // 外层 Scaffold 已不再分发 inset（见 EthanApp.kt），这里自己的顶栏要负责
        // 状态栏区域，否则标题会被状态栏文字压住。
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        topBar = {
            ChatHeader(
                state = state,
                onOpenDrawer = onOpenDrawer,
                onReloadSession = onReloadSession,
                onShare = { shareDefaultIndex = it },
                snackbar = snackbar,
            )
        },
        snackbarHost = { SnackbarContainer(snackbar) },
        floatingActionButton = {
            if (state.showScrollToBottom) {
                BadgedBox(
                    badge = {
                        if (state.unreadCount > 0) {
                            Surface(
                                shape = RoundedCornerShape(50),
                                color = MaterialTheme.colorScheme.error,
                                modifier = Modifier.size(16.dp),
                            ) {
                                Box(contentAlignment = Alignment.Center) {
                                    Text(
                                        text = if (state.unreadCount > 9) "9+" else state.unreadCount.toString(),
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onError,
                                    )
                                }
                            }
                        }
                    },
                ) {
                    FloatingActionButton(
                        onClick = {
                            scope.launch { listState.animateScrollToItem(state.messages.lastIndex) }
                        },
                    ) {
                        Icon(Icons.Default.KeyboardArrowDown, contentDescription = "滚到底部")
                    }
                }
            }
        },
    ) { padding ->
        if (state.isLoading) {
            LoadingBox(Modifier.padding(padding))
            return@Scaffold
        }

        ChatConnectionBanner(state.connectionState, onResumeStream)

        // 消息列表 + 输入栏垂直排列：输入栏不再覆盖消息列表底部，
        // 从根本上解决底部内容被遮挡、滑不动的问题
        Column(
            Modifier
                .fillMaxSize()
                .padding(top = padding.calculateTopPadding())
                .imePadding(),
        ) {
            // 消息列表
            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).padding(horizontal = 12.dp),
                // 底部留白：列表与输入栏是紧邻排列的，没有这个 padding 时最后一条消息
                // 紧贴输入栏上边缘，流式输出时最新一行看起来像被输入区压住（用户反馈
                // #6「内容区域太靠下，往上收一点」）。24dp ≈ 两行文字的呼吸感，
                // 末条消息能滚到输入栏上方可见的位置。
                contentPadding = PaddingValues(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (state.messages.isEmpty()) {
                    item {
                        EmptyChatState(
                            modifier = Modifier.fillParentMaxSize(),
                            onQuickAction = { text ->
                                onInputChange(text)
                                onSend()
                            },
                        )
                    }
                } else {
                    // "加载更多"指示器
                    if (hasMoreMessages) {
                        item(key = "__load_more__") {
                            Box(
                                modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text(
                                    "上滑加载更多…",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                    itemsIndexed(visibleMessages, key = { index, msg ->
                        "${state.sessionId ?: ""}#${state.messages.size - visibleMessages.size + index}#${msg.role}"
                    }) { _, msg ->
                        MessageBubble(
                            message = msg,
                            serverUrl = state.serverUrl,
                            sessionId = state.sessionId,
                            signFile = onSignFile,
                            userIdentity = state.userIdentity,
                            onLongPress = {
                                // 长按：为空消息做不了什么（没有可引用的正文），直接忽略
                                if (msg.content.isNotBlank()) {
                                    onQuote(Quote(role = msg.role, content = msg.content))
                                }
                            },
                            // 双击进入阅读模式（对齐 Web 的阅读模式入口）
                            onOpenReading = { readingMessage = msg },
                        )
                    }
                }
            }

            // 检测滚动到顶部，加载更多历史消息
            val isAtTop by remember {
                derivedStateOf {
                    listState.firstVisibleItemIndex == 0 &&
                        listState.firstVisibleItemScrollOffset == 0
                }
            }
            LaunchedEffect(isAtTop, hasMoreMessages) {
                if (isAtTop && hasMoreMessages) {
                    val prevCount = visibleMessages.size
                    visibleCount = (visibleCount + pageSize).coerceAtMost(totalCount)
                    // 加载后滚动到之前的第一条（新增了 items 在顶部）
                    val added = visibleCount - prevCount
                    if (added > 0) {
                        // +1 是因为有 "加载更多" item
                        listState.scrollToItem(added + if (totalCount > visibleCount) 1 else 0)
                    }
                }
            }

            ChatInputPanel(
                state = state,
                onInputChange = onInputChange,
                onSend = onSend,
                onStop = onStop,
                onModelSelected = onModelSelected,
                onQuote = onQuote,
                onRemoveImage = onRemoveImage,
                onInject = onInject,
                onQueueRemove = onQueueRemove,
                onQueueEdit = onQueueEdit,
                onToggleAutoConsent = onToggleAutoConsent,
                onOpenOptions = { showPlusSheet = true },
                onConfirmAutoConsent = { showAutoConsentConfirm = true },
                onOpenFullEditor = { showFullEditor = true },
            )
        }
    }

    // 阅读模式：全屏覆盖在聊天页之上（不在 Scaffold 里，避免继承 padding/FAB）。
    // 这样退出时聊天页的滚动位置原封不动 —— 用户回到的就是离开时那一屏。
    //
    // 返回键必须先关阅读模式：阅读模式是覆盖层而非导航目的地，全 app 没有别的
    // BackHandler，按返回键事件会直接落到 NavController 把 chat 路由 pop 掉 ——
    // 表现为「只是退出了阅读模式，会话页也跟着一起退了」（用户反馈 #3）。
    // enabled 挂在 readingMessage 上：没有覆盖层时不拦截，返回键照常退出会话。
    BackHandler(enabled = readingMessage != null) {
        readingMessage = null
    }
    BackHandler(enabled = shareDefaultIndex != null) {
        shareDefaultIndex = null
    }
    // 全屏编辑模式：Dialog 占满全屏（usePlatformDefaultWidth=false），顶部 关闭/标题/发送，
    // 正文多行输入吃满剩余空间。返回键由 Dialog 自身的 onDismissRequest 处理（收起而非退出会话）。
    if (showFullEditor) {
        ChatFullEditor(
            state = state,
            onInputChange = onInputChange,
            onSend = onSend,
            onClose = { showFullEditor = false },
        )
    }

    readingMessage?.let { msg ->
        ReadingModeScreen(message = msg, onClose = { readingMessage = null })
    }
    shareDefaultIndex?.let { idx ->
        ShareModeScreen(
            messages = state.messages,
            defaultSelectedIndex = idx,
            onClose = { shareDefaultIndex = null },
        )
    }

    // 超级权限二次确认：只在关→开时弹一次。取消则不改状态（保持关闭）。
    // 与 Web/Desktop 的文案保持一致（三端同一份说明）。
    if (showAutoConsentConfirm) {
        ChatAutoConsentConfirmation(
            onClose = { showAutoConsentConfirm = false },
            onToggleAutoConsent = onToggleAutoConsent,
        )
    }
}
