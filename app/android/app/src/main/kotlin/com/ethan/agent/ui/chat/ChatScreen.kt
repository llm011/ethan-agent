package com.ethan.agent.ui.chat

import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.statusBarsPadding
import com.ethan.agent.shared.viewmodel.ChatUiState
import com.ethan.agent.shared.viewmodel.ConnectionState

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Shield
import androidx.compose.material.icons.filled.VerifiedUser
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
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
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import com.ethan.agent.R
import com.ethan.agent.core.model.FileSignature
import com.ethan.agent.core.model.ModelSelection
import com.ethan.agent.core.model.Quote
import com.ethan.agent.core.model.UserIdentity
import com.ethan.agent.core.model.fullId
import com.ethan.agent.shared.UiMessage
import com.ethan.agent.ui.components.EthanBadge
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.ModelDropdown
import com.ethan.agent.ui.components.SnackbarContainer
import com.ethan.agent.ui.components.ToolTimeline
import com.ethan.agent.ui.components.SimpleMarkdown
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import coil.compose.SubcomposeAsyncImage
import coil.compose.rememberAsyncImagePainter
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.animateScrollBy
import androidx.compose.material.icons.filled.Fullscreen
import androidx.compose.material.icons.filled.Person
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.platform.LocalConfiguration

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
) {
    val snackbar = remember { SnackbarHostState() }
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var showPlusSheet by remember { mutableStateOf(false) }
    // 超级权限「关→开」时的二次确认（开启是高危方向，必须让用户明确知道代价）
    var showAutoConsentConfirm by remember { mutableStateOf(false) }
    // 阅读模式（双击气泡进入）：非空时全屏覆盖在聊天页之上
    var readingMessage by remember { mutableStateOf<UiMessage?>(null) }
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

    // App 从后台恢复时尝试重连
    LaunchedEffect(state.sessionId) {
        if (state.sessionId != null) {
            lifecycleOwner.lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
                onResumeStream()
            }
        }
    }

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

    // Plus button bottom sheet (model/mode/upload)
    if (showPlusSheet) {
        val sheetState = rememberModalBottomSheetState()
        ModalBottomSheet(
            onDismissRequest = { showPlusSheet = false },
            sheetState = sheetState,
        ) {
            Column(
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                Text("选项", style = MaterialTheme.typography.titleMedium)

                // Upload section
                Surface(
                    onClick = { filePicker.launch("*/*"); showPlusSheet = false },
                    shape = MaterialTheme.shapes.small,
                    color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier.padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Icon(Icons.Default.AttachFile, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                        Text("上传图片/文件")
                    }
                }

                HorizontalDivider()

                // 模型选择器 —— 对齐 Web 的 ModelSelect：
                // 显示 alias/description 而非裸 id，右侧标 provider 消歧，选中值为 provider/id。
                // 组件化后与设置页的「默认模型 / 轻量模型」共用同一份实现。
                Text("模型", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (state.modelAmbiguous) {
                    Text(
                        "该模型在多个 provider 下重名，请从下方列表选择要使用的 provider",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
                ModelDropdown(
                    models = state.models,
                    value = state.selectedModel,
                    onValueChange = onModelSelected,
                )

                // 模式选择器 —— Web 上是单个下拉（不是一排 chip）。原来用 Row 排 FilterChip，
                // 选项一多就把最后一个挤到只剩一个字宽换行，窄屏尤其明显。
                if (state.modes.isNotEmpty()) {
                    Text("模式", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    var modeExpanded by remember { mutableStateOf(false) }
                    val currentMode = remember(state.modes, state.selectedMode) {
                        state.modes.firstOrNull { it.key == state.selectedMode }
                    }
                    ExposedDropdownMenuBox(expanded = modeExpanded, onExpandedChange = { modeExpanded = it }) {
                        OutlinedTextField(
                            value = currentMode?.label ?: "",
                            onValueChange = {},
                            readOnly = true,
                            singleLine = true,
                            placeholder = { Text("模式") },
                            leadingIcon = currentMode?.icon?.takeIf { it.isNotBlank() }?.let { icon ->
                                { Text(icon) }
                            },
                            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = modeExpanded) },
                            modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
                        )
                        ExposedDropdownMenu(
                            expanded = modeExpanded,
                            onDismissRequest = { modeExpanded = false },
                            modifier = Modifier.heightIn(max = 360.dp),
                        ) {
                            // 首项是「不指定模式」——对应 Web 的 `__default__` 空选项
                            DropdownMenuItem(
                                text = { Text("默认（不指定）") },
                                onClick = {
                                    onModeSelected("")
                                    modeExpanded = false
                                },
                            )
                            state.modes.forEach { mode ->
                                DropdownMenuItem(
                                    text = {
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            if (mode.icon.isNotBlank()) {
                                                Text(mode.icon)
                                                Spacer(Modifier.width(8.dp))
                                            }
                                            Text(mode.label)
                                        }
                                    },
                                    onClick = {
                                        onModeSelected(mode.key)
                                        modeExpanded = false
                                    },
                                )
                            }
                        }
                    }
                }

                Spacer(Modifier.height(16.dp))
            }
        }
    }

    if (state.showOnboarding) {
        AlertDialog(
            onDismissRequest = onDismissOnboarding,
            title = { Text("欢迎使用 Ethan") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(state.onboarding?.message ?: "为你的 Agent 取个名字吧")
                    OutlinedTextField(
                        value = state.agentName,
                        onValueChange = { onOnboardingChange(it, state.userInfo) },
                        label = { Text("Agent 名称") },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = state.userInfo,
                        onValueChange = { onOnboardingChange(state.agentName, it) },
                        label = { Text("自我介绍") },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 3,
                    )
                }
            },
            confirmButton = { TextButton(onClick = onCompleteOnboarding) { Text("完成") } },
            dismissButton = { TextButton(onClick = onDismissOnboarding) { Text("跳过") } },
        )
    }

    state.consent?.let { consent ->
        AlertDialog(
            onDismissRequest = onDismissConsent,
            title = { Text("需要授权: ${consent.tool}") },
            text = {
                Column {
                    Text(consent.description)
                    consent.detail?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                }
            },
            confirmButton = { TextButton(onClick = { onConsent(true) }) { Text("允许") } },
            dismissButton = { TextButton(onClick = { onConsent(false) }) { Text("拒绝") } },
        )
    }

    // ask_user 选择卡片：问题 + 选项 + 倒计时（超时后端走 default，这里同步展示）
    state.askUser?.let { ask ->
        AlertDialog(
            onDismissRequest = { /* 不可关闭：必须选择，超时自动走默认 */ },
            title = { Text(ask.question) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    if (ask.options.isEmpty()) {
                        // 后端校验回传值必须在 options 内（空 options 时任何回传都会 400），
                        // 无法提供按钮；超时后只清卡片、不回传，由后端超时机制走默认值
                        Text(
                            "无可选选项，${state.askUserRemaining}s 后由服务端按默认值处理",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        ask.options.forEach { opt ->
                            TextButton(
                                onClick = { onAskUserRespond(opt.value) },
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text(
                                    text = opt.label + if (opt.value == ask.default) "（默认）" else "",
                                    modifier = Modifier.fillMaxWidth(),
                                    textAlign = TextAlign.Start,
                                )
                            }
                        }
                        Text(
                            "${state.askUserRemaining}s 后自动选择默认项",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            },
            confirmButton = {},
        )
    }

    // wait_for_user 等待卡片：确认/取消（或文本输入）+ 倒计时
    state.waitForUser?.let { wfu ->
        var textValue by remember(wfu.requestId) { mutableStateOf("") }
        val isText = wfu.inputType == "text"
        AlertDialog(
            onDismissRequest = { /* 不可关闭：必须确认/取消，超时自动回传 timeout */ },
            title = { Text(wfu.prompt, style = MaterialTheme.typography.titleSmall) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (isText) {
                        OutlinedTextField(
                            value = textValue,
                            onValueChange = { textValue = it },
                            placeholder = { Text(wfu.placeholder.ifBlank { "请输入…" }) },
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    Text(
                        "${formatRemainingSeconds(state.waitForUserRemaining)}后超时",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        onWaitForUserRespond(if (isText) textValue.trim().ifBlank { "done" } else "done")
                    },
                ) { Text(wfu.confirmLabel) }
            },
            dismissButton = {
                TextButton(onClick = { onWaitForUserRespond("cancel") }) { Text(wfu.cancelLabel) }
            },
        )
    }

    Scaffold(
        // 外层 Scaffold 已不再分发 inset（见 EthanApp.kt），这里自己的顶栏要负责
        // 状态栏区域，否则标题会被状态栏文字压住。
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        topBar = {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .statusBarsPadding()
                    .padding(horizontal = 4.dp, vertical = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                IconButton(onClick = onOpenDrawer) {
                    Icon(
                        Icons.Default.Menu,
                        contentDescription = "菜单",
                        tint = MaterialTheme.colorScheme.onSurface,
                    )
                }
                Text(
                    text = state.title,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.primary,
                    // 单行 + 省略号：标题过长时不能换行把右侧的连接状态徽章挤走
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                ConnectionStateIndicator(state.connectionState, state.isResuming)
            }
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

        // 断线重连横幅
        if (state.connectionState == ConnectionState.Disconnected) {
            Surface(
                color = MaterialTheme.colorScheme.errorContainer,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Row(
                    Modifier.padding(horizontal = 16.dp, vertical = 8.dp).fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("连接断开", style = MaterialTheme.typography.bodySmall)
                    TextButton(onClick = onResumeStream) { Text("重连") }
                }
            }
        }

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

            // 输入框区域
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(MaterialTheme.colorScheme.background)
                    .navigationBarsPadding()
                    .padding(horizontal = 12.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                // 排队消息 chips（对齐 Web 的 QueuedMessages，展示在输入框正上方）：
                // 流式中点发送进队，本轮跑完自动按序发出。点击 = 取回输入框编辑，× = 移除。
                // 拖拽排序 web 独有，手机上取回再发等效，暂不做。
                if (state.queuedMessages.isNotEmpty()) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(bottom = 4.dp)
                            .horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        state.queuedMessages.forEach { item ->
                            AssistChip(
                                onClick = { onQueueEdit(item.id) },
                                label = {
                                    Text(
                                        item.text.ifBlank { "🖼 图片" }.replace("\n", " ").take(16),
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                        style = MaterialTheme.typography.labelMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                },
                                trailingIcon = {
                                    Icon(
                                        Icons.Default.Close,
                                        contentDescription = "移除排队消息",
                                        modifier = Modifier
                                            .size(14.dp)
                                            .clickable { onQueueRemove(item.id) },
                                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                },
                            )
                        }
                    }
                }

                // 运行中「补充信息」（对齐 Web 的 InjectBox）：立即注入当前 run 的 inbox，
                // 下一轮调模型前读取。注意区别于发送键 —— 流式中发送是排队（等本轮跑完），
                // 想让 Agent 马上看到就走这里。
                if (state.isStreaming || state.isResuming) {
                    var injectOpen by remember { mutableStateOf(false) }
                    var injectText by remember { mutableStateOf("") }
                    var injectSubmitted by remember { mutableStateOf(false) }

                    Column(modifier = Modifier.fillMaxWidth().padding(bottom = 4.dp)) {
                        if (!injectOpen) {
                            Text(
                                "＋ 补充信息（立即注入）",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                                modifier = Modifier
                                    .clip(RoundedCornerShape(8.dp))
                                    .clickable { injectOpen = true }
                                    .padding(horizontal = 6.dp, vertical = 4.dp),
                            )
                        } else {
                            Surface(
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(12.dp),
                                border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                                color = MaterialTheme.colorScheme.surfaceContainerLowest,
                            ) {
                                Column {
                                    BasicTextField(
                                        value = injectText,
                                        onValueChange = { injectText = it },
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(horizontal = 10.dp, vertical = 8.dp),
                                        minLines = 2,
                                        maxLines = 4,
                                        textStyle = MaterialTheme.typography.bodyMedium.copy(
                                            color = MaterialTheme.colorScheme.onSurface,
                                        ),
                                        decorationBox = { innerTextField ->
                                            Box {
                                                if (injectText.isEmpty()) {
                                                    Text(
                                                        "补充一些信息给运行中的任务…（Enter 处提交）",
                                                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                                                        style = MaterialTheme.typography.bodyMedium,
                                                        maxLines = 1,
                                                        overflow = TextOverflow.Ellipsis,
                                                    )
                                                }
                                                innerTextField()
                                            }
                                        },
                                    )
                                    Row(
                                        modifier = Modifier.fillMaxWidth().padding(end = 6.dp, bottom = 4.dp),
                                        horizontalArrangement = Arrangement.End,
                                    ) {
                                        TextButton(onClick = {
                                            injectOpen = false
                                            injectText = ""
                                            injectSubmitted = false
                                        }) { Text("收起", style = MaterialTheme.typography.labelMedium) }
                                        TextButton(
                                            enabled = injectText.isNotBlank(),
                                            onClick = {
                                                onInject(injectText.trim())
                                                injectText = ""
                                                injectSubmitted = true
                                            },
                                        ) { Text("注入", style = MaterialTheme.typography.labelMedium) }
                                    }
                                }
                            }
                            // 提交成功的即时反馈（失败走全局错误横幅：injectMessage 会 set error）
                            LaunchedEffect(injectSubmitted) {
                                if (injectSubmitted) {
                                    kotlinx.coroutines.delay(2500)
                                    injectSubmitted = false
                                }
                            }
                            if (injectSubmitted) {
                                Text(
                                    "✓ 已注入，下一轮调用模型时读取",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.primary.copy(alpha = 0.8f),
                                    modifier = Modifier.padding(start = 6.dp, top = 2.dp),
                                )
                            }
                        }
                    }
                }

                // 待发送图片预览（对齐 Web：输入框上方缩略图 + 删除按钮）
                if (state.pendingImages.isNotEmpty()) {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(bottom = 4.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        state.pendingImages.forEachIndexed { index, img ->
                            Box(modifier = Modifier.size(56.dp)) {
                                Image(
                                    painter = rememberAsyncImagePainter(img.dataUrl),
                                    contentDescription = img.filename,
                                    modifier = Modifier
                                        .fillMaxSize()
                                        .clip(MaterialTheme.shapes.small),
                                    contentScale = ContentScale.Crop,
                                )
                                Surface(
                                    onClick = { onRemoveImage(index) },
                                    shape = CircleShape,
                                    color = MaterialTheme.colorScheme.surface.copy(alpha = 0.85f),
                                    modifier = Modifier
                                        .align(Alignment.TopEnd)
                                        .size(18.dp),
                                ) {
                                    Box(contentAlignment = Alignment.Center) {
                                        Icon(
                                            Icons.Default.Close,
                                            contentDescription = "移除图片",
                                            tint = MaterialTheme.colorScheme.onSurface,
                                            modifier = Modifier.size(12.dp),
                                        )
                                    }
                                }
                            }
                        }
                    }
                }

                state.quote?.let { quote ->
                    AssistChip(
                        onClick = {},
                        label = { Text("引用: ${quote.content.take(40)}…", maxLines = 1) },
                        trailingIcon = {
                            IconButton(onClick = { onQuote(null) }) {
                                Icon(Icons.Default.Close, contentDescription = "清除引用")
                            }
                        },
                        modifier = Modifier.padding(bottom = 4.dp),
                    )
                }

                // 旧会话/默认模型存的纯 id 命中多个同名模型：列出候选让用户一键指定 provider，
                // 选择前禁用发送（与 web/desktop chat-input 的候选按钮同做法）
                if (state.modelAmbiguous) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(bottom = 4.dp)
                            .background(MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.4f), RoundedCornerShape(12.dp))
                            .padding(horizontal = 10.dp, vertical = 6.dp),
                    ) {
                        Text(
                            "模型「${state.selectedModel}」在多个 provider 下重名，请选择要使用的：",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                        Row(
                            modifier = Modifier
                                .padding(top = 4.dp)
                                .horizontalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            state.ambiguousCandidates.forEach { model ->
                                AssistChip(
                                    onClick = { onModelSelected(model.fullId) },
                                    label = { Text(model.fullId, style = MaterialTheme.typography.bodySmall) },
                                )
                            }
                        }
                    }
                }

                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    color = MaterialTheme.colorScheme.surfaceContainerLowest,
                    shape = MaterialTheme.shapes.extraLarge,
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                ) {
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .padding(start = 6.dp, end = 4.dp, top = 4.dp, bottom = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        // + 号按钮：圆形
                        Surface(
                            onClick = { showPlusSheet = true },
                            shape = CircleShape,
                            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                            modifier = Modifier.size(32.dp),
                        ) {
                            Box(
                                modifier = Modifier.fillMaxSize(),
                                contentAlignment = Alignment.Center,
                            ) {
                                Icon(
                                    Icons.Default.Add,
                                    contentDescription = "更多选项",
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.size(18.dp),
                                )
                            }
                        }
                        // 超级权限开关。关闭→开启时必须过一道二次确认（见本 composable
                        // 末尾的 AlertDialog）：长时间运行时用户容易忘了自己开着自动批准，
                        // 导致普通 shell / 写文件操作一路放行。取消弹窗则保持关闭。
                        Surface(
                            onClick = {
                                if (state.autoConsent) onToggleAutoConsent() // 关：降权，直接生效
                                else showAutoConsentConfirm = true          // 开：先弹警示
                            },
                            shape = CircleShape,
                            color = if (state.autoConsent) MaterialTheme.colorScheme.tertiaryContainer
                                else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                            modifier = Modifier.size(32.dp).padding(start = 2.dp),
                        ) {
                            Box(
                                modifier = Modifier.fillMaxSize(),
                                contentAlignment = Alignment.Center,
                            ) {
                                Icon(
                                    if (state.autoConsent) Icons.Default.VerifiedUser else Icons.Default.Shield,
                                    contentDescription = if (state.autoConsent) "超级权限已开启" else "超级权限",
                                    tint = if (state.autoConsent) MaterialTheme.colorScheme.onTertiaryContainer
                                        else MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.size(16.dp),
                                )
                            }
                        }
                        // 输入框 + 发送按钮
                        Row(
                            modifier = Modifier.weight(1f).padding(start = 4.dp, end = 2.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            BasicTextField(
                                value = state.inputText,
                                onValueChange = onInputChange,
                                modifier = Modifier
                                    .weight(1f)
                                    .padding(horizontal = 8.dp, vertical = 6.dp),
                                maxLines = 5,
                                textStyle = MaterialTheme.typography.bodyMedium.copy(
                                    color = MaterialTheme.colorScheme.onSurface,
                                ),
                                decorationBox = { innerTextField ->
                                    Box {
                                        if (state.inputText.isEmpty()) {
                                            // 占位文案在「用户可能正在输入」这件事上会误导，
                                            // 留空又容易让人以为输入框坏了，所以保留；但内容
                                            // 必须短到不折行 —— 手机上输入框横向空间被一排按钮
                                            // 挤得很窄（+ / 超级权限 / 展开 / 发送），一折行就顶高
                                            // 整条输入栏（原来是「输入消息，支持 Markdown…」）。
                                            // maxLines = 1 只做兜底：文案短到不折行时它不生效，
                                            // 万一以后有人把文案改长，也只会被截断而不会撑高输入栏。
                                            //
                                            // 注意：不要在「输入框行」上做 centerVertically——
                                            // BasicTextField 会随输入长到 maxLines = 5，居中后输入区
                                            // 上下同时溢出，顶栏「+」被切一半、最后一行也贴着输入栏边。
                                            Text(
                                                if (state.isStreaming) CHAT_INPUT_PLACEHOLDER_QUEUED
                                                else CHAT_INPUT_PLACEHOLDER,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                                                style = MaterialTheme.typography.bodyMedium,
                                                maxLines = 1,
                                            )
                                        }
                                        innerTextField()
                                    }
                                },
                            )
                            // 展开为全屏编辑（对齐 Web 输入框右上角的展开按钮）：长文本时
                            // 5 行上限太憋屈，全屏写完再发。
                            IconButton(
                                onClick = { showFullEditor = true },
                                modifier = Modifier.size(28.dp),
                            ) {
                                Icon(
                                    Icons.Default.Fullscreen,
                                    contentDescription = "展开为全屏编辑",
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.size(18.dp),
                                )
                            }
                            Box(
                                modifier = Modifier.padding(end = 2.dp),
                                contentAlignment = Alignment.Center,
                            ) {
                                when {
                                    state.isStopping -> {
                                        CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
                                    }
                                    state.isStreaming || state.isResuming -> {
                                        // 生成中：停止 + 排队发送并排（对齐 web —— 流式里的发送
                                        // 是入队，本轮跑完自动发下一条；只有停止键的话队列功能没入口）
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            // 队列发送：有内容才亮
                                            val canQueue = state.inputText.isNotBlank() || state.pendingImages.isNotEmpty()
                                            Surface(
                                                shape = CircleShape,
                                                color = if (canQueue) MaterialTheme.colorScheme.primary
                                                    else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                                                modifier = Modifier.size(36.dp),
                                            ) {
                                                IconButton(
                                                    onClick = onSend,
                                                    enabled = canQueue && !state.modelAmbiguous,
                                                ) {
                                                    Icon(
                                                        Icons.AutoMirrored.Filled.Send,
                                                        contentDescription = "排队发送",
                                                        tint = if (canQueue) MaterialTheme.colorScheme.onPrimary
                                                            else MaterialTheme.colorScheme.onSurfaceVariant,
                                                        modifier = Modifier.size(18.dp).offset(x = 1.dp),
                                                    )
                                                }
                                            }
                                            Spacer(Modifier.width(6.dp))
                                            Surface(
                                                shape = CircleShape,
                                                color = MaterialTheme.colorScheme.errorContainer,
                                                modifier = Modifier.size(36.dp),
                                            ) {
                                                IconButton(onClick = onStop) {
                                                    Icon(
                                                        Icons.Default.Stop,
                                                        contentDescription = "停止",
                                                        tint = MaterialTheme.colorScheme.error,
                                                        modifier = Modifier.size(18.dp),
                                                    )
                                                }
                                            }
                                        }
                                    }
                                    else -> {
                                        // 有内容且模型不歧义才可发送（歧义时按钮同时变灰，避免"看起来能点"）
                                        val canSend = (state.inputText.isNotBlank() || state.pendingImages.isNotEmpty()) &&
                                            !state.modelAmbiguous
                                        Surface(
                                            shape = CircleShape,
                                            color = if (canSend) MaterialTheme.colorScheme.primary
                                                else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                                            modifier = Modifier.size(36.dp),
                                        ) {
                                            IconButton(
                                                onClick = onSend,
                                                // 模型歧义时禁用发送，强制用户先显式选一个 provider
                                                enabled = canSend,
                                            ) {
                                                Icon(
                                                    Icons.AutoMirrored.Filled.Send,
                                                    contentDescription = "发送",
                                                    tint = if (canSend) MaterialTheme.colorScheme.onPrimary
                                                        else MaterialTheme.colorScheme.onSurfaceVariant,
                                                    modifier = Modifier.size(18.dp).offset(x = 1.dp),
                                                )
                                            }
                                        }
                                    }
                                }
                            }
                        } // end inner Row (input + send)
                    } // end outer Row
                } // end Surface

                // 底部状态行：左侧放「当前模型 + 运行状态」，右侧固定一行免责声明。
                // 之前只有居中的「对话由 AI 生成」，既浪费了一整行高度，也没告诉
                // 用户正在用哪个模型、是否在生成中 —— 这两件事恰好在手机上最需要
                // 一眼看到（模型选错要立刻发现，生成中要能判断该不该等）。
                Row(
                    // 左侧留 8dp：这段文字原来紧贴屏幕边缘（外层只有 12dp 的
                    // horizontal padding，视觉上正好压在气泡的左对齐线上），
                    // 和上方气泡的起始位置对不齐，看着「太靠左」。
                    Modifier.fillMaxWidth().padding(start = 8.dp, top = 2.dp, bottom = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    // 显示**可读名**（alias/description）而不是 provider/id 原始值 ——
                    // 与模型选择器里的选中名、Web 的展示口径一致。落库/提交仍用 fullId。
                    state.selectedModel?.takeIf { it.isNotBlank() }?.let { raw ->
                        Text(
                            text = ModelSelection.findById(state.models, raw)
                                ?.let(ModelSelection::displayNameOf) ?: raw,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f, fill = false),
                        )
                    }
                    when {
                        state.isResuming -> FooterStatusDot("重连中", MaterialTheme.colorScheme.tertiary)
                        state.isStreaming -> FooterStatusDot("生成中", MaterialTheme.colorScheme.primary)
                        state.connectionState == ConnectionState.Disconnected ->
                            FooterStatusDot("已断开", MaterialTheme.colorScheme.error)
                    }
                    Spacer(Modifier.weight(1f))
                    Text(
                        text = "对话由 AI 生成",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                        maxLines = 1,
                        // 固定靠右：模型名过长时省略号吃掉的是左侧的空间，
                        // 免责声明始终贴住右边缘（用户明确要求靠右对齐）。
                        textAlign = TextAlign.End,
                        modifier = Modifier.wrapContentWidth(align = Alignment.End),
                    )
                }
            } // end input Column (bottom-aligned)
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
    // 全屏编辑模式：Dialog 占满全屏（usePlatformDefaultWidth=false），顶部 关闭/标题/发送，
    // 正文多行输入吃满剩余空间。返回键由 Dialog 自身的 onDismissRequest 处理（收起而非退出会话）。
    if (showFullEditor) {
        Dialog(
            onDismissRequest = { showFullEditor = false },
            properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.background)
                    .statusBarsPadding()
                    .navigationBarsPadding()
                    .imePadding()
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    IconButton(onClick = { showFullEditor = false }) {
                        Icon(Icons.Default.Close, contentDescription = "关闭全屏编辑")
                    }
                    Text(
                        "编辑消息",
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.weight(1f),
                    )
                    // 发送后关闭全屏；流式中发送会走排队路径（与主输入框同一 onSend）
                    val canSendFull = (state.inputText.isNotBlank() || state.pendingImages.isNotEmpty()) &&
                        !state.modelAmbiguous
                    IconButton(
                        onClick = {
                            showFullEditor = false
                            onSend()
                        },
                        enabled = canSendFull,
                    ) {
                        Icon(
                            Icons.AutoMirrored.Filled.Send,
                            contentDescription = "发送",
                            tint = if (canSendFull) MaterialTheme.colorScheme.primary
                                else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.4f),
                        )
                    }
                }
                HorizontalDivider(modifier = Modifier.padding(bottom = 8.dp))
                BasicTextField(
                    value = state.inputText,
                    onValueChange = onInputChange,
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    textStyle = MaterialTheme.typography.bodyLarge.copy(
                        color = MaterialTheme.colorScheme.onSurface,
                    ),
                    decorationBox = { innerTextField ->
                        Box {
                            if (state.inputText.isEmpty()) {
                                Text(
                                    CHAT_INPUT_PLACEHOLDER,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                                    style = MaterialTheme.typography.bodyLarge,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                            innerTextField()
                        }
                    },
                )
            }
        }
    }

    readingMessage?.let { msg ->
        ReadingModeScreen(message = msg, onClose = { readingMessage = null })
    }

    // 超级权限二次确认：只在关→开时弹一次。取消则不改状态（保持关闭）。
    // 与 Web/Desktop 的文案保持一致（三端同一份说明）。
    if (showAutoConsentConfirm) {
        AlertDialog(
            onDismissRequest = { showAutoConsentConfirm = false },
            icon = { Icon(Icons.Default.Shield, contentDescription = null) },
            title = { Text("开启超级权限？") },
            text = {
                Text(
                    "开启后，普通工具授权（读写文件、执行普通 shell 命令等）将不再弹窗，" +
                        "直接放行；高危命令（rm -rf 等）仍会确认。\n\n" +
                        "请确认你了解当前正在对话的 Agent 会做什么。",
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    showAutoConsentConfirm = false
                    onToggleAutoConsent()
                }) { Text("开启") }
            },
            dismissButton = {
                TextButton(onClick = { showAutoConsentConfirm = false }) { Text("取消") }
            },
        )
    }
}

/** 底部状态行的小圆点 + 文案（生成中 / 重连中 / 已断开）。 */
@Composable
private fun FooterStatusDot(label: String, color: androidx.compose.ui.graphics.Color) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Box(Modifier.size(5.dp).clip(CircleShape).background(color))
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = color,
            maxLines = 1,
        )
    }
}

@Composable
private fun ConnectionStateIndicator(state: ConnectionState, isResuming: Boolean) {
    val (color, label) = when {
        isResuming -> Pair(MaterialTheme.colorScheme.tertiary, "重连中…")
        state == ConnectionState.Streaming -> Pair(MaterialTheme.colorScheme.error, "生成中")
        state == ConnectionState.Disconnected -> Pair(MaterialTheme.colorScheme.error, "已断开")
        else -> return
    }
    EthanBadge(
        text = label,
        containerColor = color.copy(alpha = 0.15f),
        contentColor = color,
    )
}

/**
 * 把头像的相对路径（`assets/images/_profile/img_avatar.png`）拼成绝对 URL。
 *
 * 空串不拼（否则会拼出一个悬空 URL 再白白请求一次），已经是 http(s) 的原样返回。
 */
internal fun avatarAbsoluteUrl(path: String, serverUrl: String): String = when {
    path.isBlank() -> ""
    path.startsWith("http") -> path
    else -> "${serverUrl.trimEnd('/')}/$path"
}

/** 取名字首个码点并大写 —— 与共享包 avatarInitial 同语义（emoji 不能被切成半个代理对）。 */
internal fun userAvatarInitial(name: String): String {
    val trimmed = name.trim()
    if (trimmed.isEmpty()) return ""
    val first = trimmed.codePointAt(0)
    return String(Character.toChars(first)).uppercase()
}

/**
 * 头像本体：有图就显示图，图加载失败 / 没图但有名字显示首字，都没有显示人形图标。
 *
 * 图片和兜底在**同一个** `SubcomposeAsyncImage` 里切换，而不是在外面用 `painter.state`
 * 判断再换组合 —— 后者会让「图加载成功」和「兜底」成为两棵树，加载完成的一瞬间
 * 整个头像被替换掉，圆角/尺寸会闪一下。
 *
 * 刻意不设 contentDescription：头像纯装饰，气泡里已有正文，读屏再念一遍是噪声。
 */
@Composable
internal fun UserAvatarImage(
    url: String,
    name: String,
    size: Dp,
    modifier: Modifier = Modifier,
) {
    val shape = CircleShape
    val initial = remember(name) { userAvatarInitial(name) }
    val fallback: @Composable () -> Unit = {
        if (initial.isNotBlank()) {
            Box(
                modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.primary.copy(alpha = 0.15f)),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    initial,
                    color = MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.titleSmall,
                )
            }
        } else {
            Box(
                modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.surfaceVariant),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = Icons.Filled.Person,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(size * 0.55f),
                )
            }
        }
    }

    Box(modifier = modifier.size(size).clip(shape)) {
        if (url.isBlank()) {
            // 没设头像：直接兜底，连请求都不发（Coil 拿到空串会走一次无效加载）
            fallback()
        } else {
            SubcomposeAsyncImage(
                model = url,
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
                loading = { fallback() },
                error = { fallback() },
            )
        }
    }
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
private fun MessageBubble(message: UiMessage, serverUrl: String = "", sessionId: String? = null, signFile: (suspend (String) -> FileSignature?)? = null, userIdentity: UserIdentity = UserIdentity(), onLongPress: () -> Unit, onOpenReading: () -> Unit = {}) {
    val isUser = message.role == "user"
    // 对齐 Web（web/components/chat/message-bubble.tsx）：
    //   用户   bg-primary/10 text-foreground
    //   助手   bg-muted
    // 之前用户气泡是实心 primary + onPrimary 文字，在一片浅色里非常刺眼，也和 Web 对不上。
    val bubbleColor = if (isUser) {
        MaterialTheme.colorScheme.primary.copy(alpha = 0.10f)
    } else {
        MaterialTheme.colorScheme.surfaceVariant
    }
    val textColor = MaterialTheme.colorScheme.onSurface

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 4.dp, vertical = 2.dp),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.Top,
    ) {
        // Assistant avatar (left)
        if (!isUser) {
            Image(
                painter = painterResource(id = R.drawable.ethan_logo_avatar),
                contentDescription = "Assistant",
                modifier = Modifier
                    .size(30.dp)
                    .clip(CircleShape),
            )
            Spacer(Modifier.width(6.dp))
        }

        // Bubble content —— 宽度对齐 Web 的 max-w-[90%]，四角统一 rounded-2xl（18dp）。
        // 之前是固定 310dp + 不对称的一角切平，换机型/字号后容易显得局促。
        Column(
            modifier = Modifier.weight(1f, fill = false),
            horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
        ) {
            // 用户显示名：只在设置过时占一行。老用户没设名字，气泡不会凭空多一行。
            if (isUser && userIdentity.displayName.isNotBlank()) {
                Text(
                    userIdentity.displayName,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(bottom = 2.dp),
                )
            }
            Surface(
                modifier = Modifier.combinedClickable(
                    interactionSource = remember { MutableInteractionSource() },
                    indication = null,
                    onClick = {},
                    onLongClick = onLongPress,
                    onDoubleClick = onOpenReading,
                ),
                shape = MaterialTheme.shapes.extraLarge,
                color = bubbleColor,
                shadowElevation = 0.dp,
            ) {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    // 用户消息图片（在文本之前）
                    if (message.images.isNotEmpty()) {
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(bottom = if (message.content.isNotBlank() || message.toolSteps.isNotEmpty() || message.quote != null) 6.dp else 0.dp),
                            horizontalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            message.images.forEach { img ->
                                Image(
                                    painter = rememberAsyncImagePainter(img.displayUrl),
                                    contentDescription = null,
                                    modifier = Modifier
                                        .sizeIn(maxHeight = 160.dp, maxWidth = 160.dp)
                                        .clip(MaterialTheme.shapes.small),
                                    contentScale = ContentScale.FillWidth,
                                )
                            }
                        }
                    }
                    message.quote?.let {
                        Text(
                            "↩ ${it.content.take(60)}",
                            style = MaterialTheme.typography.labelSmall,
                            color = if (isUser) textColor.copy(alpha = 0.7f)
                                else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(4.dp))
                    }
                    // 工具调用在前（折叠式）
                    if (message.toolSteps.isNotEmpty()) {
                        CompositionLocalProvider(androidx.compose.material3.LocalContentColor provides textColor) {
                            ToolTimeline(message.toolSteps, isStreaming = message.isStreaming)
                        }
                        if (message.content.isNotBlank()) {
                            Spacer(Modifier.height(6.dp))
                        }
                    }
                    // 文本结论在后
                    if (message.content.isNotBlank()) {
                        // 长消息折叠：超过半屏高就截断，底部给「查看全部 / 收起」。
                        // 只在真实尺寸超过阈值时展开 UI，短消息完全不受影响（无额外高度、无多余按钮）。
                        val density = LocalDensity.current
                        val configuration = LocalConfiguration.current
                        val screenWidthDp = configuration.screenWidthDp.toFloat()
                        val screenHeightDp = configuration.screenHeightDp.toFloat()
                        // 用 remember 而不是 rememberSaveable：MessageCollapseState 是自定义类，
                        // SaveableStateRegistry 只接受能进 Bundle 的类型，直接塞会抛
                        // IllegalArgumentException 把 App 打崩（已踩过）。而「展开/收起」
                        // 本来就属于一次性 UI 状态，进程被回收后恢复成折叠态完全可以接受。
                        //
                        // key 用 isStreaming 而不是 content：流式期间 content 每帧都变，
                        // 拿它做 key 会让「生成中就点开查看全部」立刻被重置回折叠态。
                        val collapseState = remember(message.isStreaming) {
                            messageCollapseState(
                                text = message.content,
                                screenWidthDp = screenWidthDp,
                                screenHeightDp = screenHeightDp,
                                fontScale = density.fontScale,
                            )
                        }
                        // 流结束后正文才是最终值（最后一轮 tool 之后还有结论），
                        // 此时按最终长度重新判定一次；只更新「可折叠与否 / 高度上限」，
                        // 不动 expanded —— 用户已经手动展开的就别给他收回去。
                        LaunchedEffect(message.isStreaming, message.content) {
                            if (!message.isStreaming) {
                                collapseState.recompute(
                                    messageCollapseState(
                                        text = message.content,
                                        screenWidthDp = screenWidthDp,
                                        screenHeightDp = screenHeightDp,
                                        fontScale = density.fontScale,
                                    )
                                )
                            }
                        }
                        Column(
                            modifier = if (collapseState.collapsible) {
                                Modifier
                                    // animateContentSize 全程只跟约束走，不碰滚动位置，
                                    // 所以展开/收起不会把用户的阅读位置顶走。
                                    .animateContentSize()
                                    .clipToBounds()
                                    .then(
                                        if (collapseState.expanded) Modifier
                                        else Modifier.heightIn(max = collapseState.maxHeight)
                                    )
                            } else {
                                Modifier
                            },
                        ) {
                            SimpleMarkdown(
                                text = message.content,
                                textColor = textColor,
                            )

                            if (collapseState.collapsible) {
                                // 「收起」放在内容末尾（用户明确要求「内底部」也要有收起交互），
                                // 展开后在文末出现，不用回头往上滚。
                                if (collapseState.expanded) {
                                    Spacer(Modifier.height(8.dp))
                                    BubbleActionLink(
                                        label = "收起",
                                        onClick = { collapseState.expanded = false },
                                        color = textColor.copy(alpha = 0.65f),
                                    )
                                }
                            }
                        }
                        if (collapseState.collapsible && !collapseState.expanded) {
                            // 折叠态：按钮钉在气泡底部。外面包一层跟气泡同色的 Surface，
                            // 让被截断的文字行从按钮底下「透出来」之前先被遮住，
                            // 视觉上明确是「还有内容没显示」，而不是排版断了。
                            Surface(color = bubbleColor) {
                                BubbleActionLink(
                                    label = "查看全部",
                                    onClick = { collapseState.expanded = true },
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }
                    }
                    // 文件卡片
                    if (message.cards.isNotEmpty()) {
                        Spacer(Modifier.height(6.dp))
                        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            message.cards.forEach { card ->
                                com.ethan.agent.ui.components.FileCardView(
                                    card = card,
                                    serverUrl = serverUrl,
                                    sessionId = sessionId,
                                    signFile = signFile,
                                )
                            }
                        }
                    }
                    if (message.isStreaming && message.content.isEmpty() && message.toolSteps.isEmpty()) {
                        Text(
                            "思考中…",
                            style = MaterialTheme.typography.bodySmall,
                            color = textColor.copy(alpha = 0.7f),
                        )
                    }
                }
            }

            // Bottom info bar: timestamp + stats pills
            if (!message.isStreaming) {
                MessageStatsBar(message, isUser)
            }
        }

        // User avatar (right)：与左侧助手 logo 对称（同尺寸 30dp / 同 6dp 间距），
        // 顶对齐气泡（对齐 Web 的 mt-1）。
        if (isUser) {
            Spacer(Modifier.width(6.dp))
            UserAvatarImage(
                url = avatarAbsoluteUrl(userIdentity.avatarUrl, serverUrl),
                name = userIdentity.displayName,
                size = 30.dp,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

/**
 * 长消息折叠的状态：是否可折叠、当前是否展开、折叠高度上限。
 *
 * 不是 data class —— `expanded` 是可变状态，直接放在普通类里让 Compose 观察到；
 * 用 `rememberSaveable(message.content) { ... }` 重建（内容变了就重置回折叠态，
 * 流式追加期间也不会因为闭包捕获旧值而卡住）。
 */
private class MessageCollapseState(
    collapsible: Boolean,
    maxHeight: androidx.compose.ui.unit.Dp,
    expanded: Boolean,
) {
    var collapsible by mutableStateOf(collapsible)
        private set
    var maxHeight by mutableStateOf(maxHeight)
        private set
    var expanded by mutableStateOf(expanded)

    /**
     * 流结束、正文定型后按最终长度重判一次。
     * 只更新「要不要折叠 / 折叠高度」，**保留** expanded —— 用户手动展开的
     * 状态不能被自动重算收回去（否则刚点开就被关上，很像 bug）。
     * 另外：本来不可折叠的消息若在流结束后变长了，这里也会把它切成可折叠。
     */
    fun recompute(next: MessageCollapseState) {
        if (collapsible == next.collapsible && maxHeight == next.maxHeight) return
        collapsible = next.collapsible
        maxHeight = next.maxHeight
        if (!collapsible) expanded = false
    }
}

/** 折叠高度上限：半屏（用户明确要求「半屏高的最大高度」）。 */
private const val COLLAPSE_SCREEN_FRACTION = 0.5f

/**
 * 输入框占位文案。**必须短到在窄屏上不折行** —— 文案一折行会把整条输入栏顶高，
 * 因为左右两侧被一排按钮（+ / 超级权限 / 展开 / 发送）占掉了大部分宽度。
 *
 * 提到顶层常量是为了两处（收起态输入框、全屏编辑）引用同一份字符串，
 * 改文案时不会只改到一处。
 */
internal const val CHAT_INPUT_PLACEHOLDER = "输入消息"
internal const val CHAT_INPUT_PLACEHOLDER_QUEUED = "排队发送"

/**
 * 估算「半屏高」并判断是否值得折叠。
 *
 * 为什么要估算而不是用 BoxWithConstraints 实测：只有**先**知道是不是长消息，
 * 才谈得上决定要不要给约束。用 `heightIn(max=...)` 配合 `clipToBounds` 来做截断效果，
 * animateContentSize 负责展开/收起的过渡——全过程不触碰 LazyColumn 的滚动位置。
 *
 * 估算依据：bodyMedium 的字号（14sp）与默认行高（约 22sp 行距 ≈ 1.6×），
 * 再把字符宽度按 0.55×字号 粗算。只用来判断「要不要折叠」，允许有偏差；
 * 真的按估算折叠了但内容其实不长，用户点一下「查看全部」即可，不会丢内容。
 * 反过来（长内容被漏判）才是问题，所以这里刻意估得保守一点（宁可多折叠）。
 */
private fun messageCollapseState(
    text: String,
    screenWidthDp: Float,
    screenHeightDp: Float,
    fontScale: Float,
): MessageCollapseState {
    val fontSizeDp = 14f * fontScale          // bodyMedium 基准字号
    val lineHeightDp = fontSizeDp * 1.62f     // 默认行高约 1.6×
    val charWidthDp = fontSizeDp * 0.55f      // 中英混排的粗略平均字宽

    // 气泡内可用宽度：屏宽 - LazyColumn 横向 padding(12dp×2) - 头像(30dp+6dp)
    //                   - 气泡内 padding(16dp×2) - 外层 padding(4dp×2)
    val contentWidthDp = (screenWidthDp - 100f).coerceAtLeast(fontSizeDp * 8f)

    val charsPerLine = (contentWidthDp / charWidthDp).coerceAtLeast(8f)
    val lineCount = text.split('\n').sumOf { line ->
        // 空行也占一行；超长行按字符数折算（Markdown 标记、英文长词会让它偏小，
        // 所以下面乘了 1.15 的安全系数）
        kotlin.math.ceil(line.length / charsPerLine).toInt().coerceAtLeast(1)
    }
    val estimatedDp = lineCount * lineHeightDp * 1.15f + 24f   // +24dp：气泡上下 padding

    val maxHeightDp = screenHeightDp * COLLAPSE_SCREEN_FRACTION
    // 折叠能省下的高度不到 80dp 就不折腾用户了
    val collapsible = estimatedDp > maxHeightDp + 80f
    return MessageCollapseState(collapsible, maxHeightDp.dp, expanded = false)
}

/** 气泡底部的行内文字按钮（「查看全部」/「收起」）——轻量、不抢视觉重心。 */
@Composable
private fun BubbleActionLink(label: String, onClick: () -> Unit, color: Color) {
    Text(
        text = label,
        style = MaterialTheme.typography.labelLarge,
        color = color,
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 6.dp),
    )
}

@Composable
private fun MessageStatsBar(message: UiMessage, isUser: Boolean = false) {
    val hasStats = message.createdAt != null || message.usage != null || message.ttfbMs != null
    if (!hasStats) return

    Row(
        modifier = Modifier
            .padding(top = 3.dp, start = 4.dp, end = 4.dp)
            .horizontalScroll(rememberScrollState()),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = if (isUser) Arrangement.spacedBy(4.dp, Alignment.End) else Arrangement.spacedBy(4.dp),
    ) {
        // Timestamp
        message.createdAt?.let { ts ->
            val timeStr = remember(ts) {
                val sdf = SimpleDateFormat("HH:mm", Locale.getDefault())
                sdf.format(Date(ts * 1000))
            }
            Text(
                text = timeStr,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
            )
        }

        // Token usage pill —— 对齐 Web 的 `bg-green-500/8 text-green-600/50`
        message.usage?.let { u ->
            if (u.input > 0 || u.output > 0) {
                StatPill(
                    text = "↑${formatTokenCount(u.input)} ↓${formatTokenCount(u.output)}" +
                        if (u.cache > 0) " ⚡${formatTokenCount(u.cache)}" else "",
                    color = StatGreen,
                )
            }
        }

        // TTFB pill —— Web 用 amber-500
        message.ttfbMs?.let { ms ->
            StatPill(text = "TTFB ${formatDuration(ms)}", color = StatAmber)
        }

        // 总耗时 pill —— Web 用 purple-500
        message.totalDurationMs?.let { ms ->
            StatPill(text = "总 ${formatDuration(ms)}", color = StatPurple)
        }

        // 实际生成耗时 pill —— Web 用 green-500
        message.generationDurationMs?.let { ms ->
            StatPill(text = "生成 ${formatDuration(ms)}", color = StatGreen)
        }
    }
}

// Tailwind 500 号色阶——与 Web 的 message-bubble.tsx 中统计药丸一一对应。
// 取 600 号（Tailwind 的 text-<hue>-600）作为文字色，因为 Web 的文字是 600 号。
private val StatAmber = Color(0xFFF59E0B)   // amber-500
private val StatPurple = Color(0xFFA855F7)  // purple-500
private val StatGreen = Color(0xFF22C55E)   // green-500

/**
 * 统计小药丸（token / TTFB / 耗时）。
 *
 * 配色对齐 Web 的 `bg-<hue>-500/8 text-<hue>-600/50`：极淡的底色 + 半透明的同色文字。
 * 之前是用 Material 500 号原色（0xFF4CAF50 之类）+ 12% 底，饱和度太高，在一屏浅色里
 * 几个彩色小方块特别扎眼，也和 Web 的克制观感不一致。
 */
@Composable
private fun StatPill(text: String, color: Color) {
    EthanBadge(
        text = text,
        containerColor = color.copy(alpha = 0.08f),
        contentColor = color.copy(alpha = 0.55f),
        modifier = Modifier.padding(end = 4.dp),
    )
}

private fun formatTokenCount(count: Int): String = when {
    count >= 1000 -> "${count / 1000}k"
    else -> count.toString()
}

private fun formatDuration(ms: Long): String = when {
    ms >= 1000 -> "${String.format("%.1f", ms / 1000.0)}s"
    else -> "${ms}ms"
}

/** wait_for_user 倒计时展示：>=60s 显示「M分S秒」，否则「Ns」。 */
private fun formatRemainingSeconds(seconds: Int): String = when {
    seconds >= 60 -> "${seconds / 60}分${seconds % 60}秒"
    else -> "${seconds}秒"
}

@Composable
private fun EmptyChatState(
    modifier: Modifier = Modifier,
    onQuickAction: (String) -> Unit,
) {
    val quickActions = listOf(
        "☀️ 深圳的天气怎么样" to "深圳的天气怎么样",
        "📄 帮我找找最新的 Agent 论文" to "帮我找找最新的 Agent 论文",
    )
    // 键盘弹出后 imePadding() 把整个 Column 压缩，而这里内容固定约 330dp 高：
    // 居中布局会把溢出部分均匀切掉两头，第二个提示文字（副标题）刚好落在上边缘
    // 被切一半（用户反馈）。改为「可滚动 + 靠上（CenterVertically 改为 Top）」：
    //   - Top 对齐：空间够时内容整体上移，副标题不会顶到上边缘；
    //   - verticalScroll：空间不够时（横屏 / 键盘弹起）用户能自己滑，不会静默丢内容。
    val scrollState = rememberScrollState()
    Column(
        modifier = modifier
            .wrapContentHeight(Alignment.Top)
            .verticalScroll(scrollState)
            .padding(horizontal = 24.dp, vertical = 30.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // 头像 - 圆形 app logo
        Image(
            painter = painterResource(id = R.drawable.ethan_logo_avatar),
            contentDescription = "Ethan",
            modifier = Modifier.size(72.dp).clip(CircleShape),
        )
        Text(
            text = "嗨，我是 Ethan~",
            style = MaterialTheme.typography.titleLarge,
            color = MaterialTheme.colorScheme.onBackground,
            fontWeight = FontWeight.Bold,
        )
        Text(
            text = "你的私人 AI 小助手，随时待命",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.padding(top = 4.dp),
        ) {
            quickActions.forEach { (label, payload) ->
                Surface(
                    onClick = { onQuickAction(payload) },
                    shape = MaterialTheme.shapes.extraLarge,
                    color = MaterialTheme.colorScheme.surfaceContainerLow,
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                ) {
                    Text(
                        text = label,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }
    }
}

/**
 * 取分享进来 URI 的显示文件名。
 *
 * content:// URI 的 lastPathSegment 往往是 document id（如 "image:1234"），
 * 直接用会得到很怪的文件名，所以优先查 [OpenableColumns.DISPLAY_NAME]，
 * 查不到再退回 lastPathSegment，最后兜底 "shared_file"。
 */
/**
 * 把 URI 内容复制到 cacheDir 的唯一临时文件再上传。
 *
 * 用 [File.createTempFile] 而非「cacheDir/原文件名」：原文件名会让同名分享互相覆盖
 * （两次分享 photo.jpg 会踩同一个文件）。保留原扩展名方便后端识别类型；
 * 展示给用户的文件名仍用 [displayName]。临时文件在上传结束后由 ViewModel 删除。
 */
private fun copyToTempAndUpload(
    context: Context,
    uri: Uri,
    displayName: String,
    onUpload: (ByteArray, String) -> Unit,
) {
    runCatching {
        // onUpload 接 ByteArray，无需落地临时文件——直接从 InputStream 读 bytes，
        // 避免旧实现中 temp 文件在成功路径不删除导致 cacheDir 泄漏。
        context.contentResolver.openInputStream(uri)?.use { input ->
            onUpload(input.readBytes(), displayName)
        }
    }
}

/** 图片专用：读 bytes 转 base64 dataUrl，走 addImage 而非 uploadAttachment */
private fun copyAndAddImage(
    context: Context,
    uri: Uri,
    displayName: String,
    onAddImage: (dataUrl: String, base64Data: String, mediaType: String, filename: String) -> Unit,
) {
    runCatching {
        context.contentResolver.openInputStream(uri)?.use { input ->
            val bytes = input.readBytes()
            // 从 URI 推断 MIME type，默认 image/png
            val mediaType = context.contentResolver.getType(uri) ?: "image/png"
            val base64 = android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)
            val dataUrl = "data:$mediaType;base64,$base64"
            onAddImage(dataUrl, base64, mediaType, displayName)
        }
    }
}

/** 从 content Uri 里取显示文件名（聊天页附件与设置页头像共用）。 */
internal fun queryDisplayName(context: Context, uri: Uri): String {
    if (uri.scheme == "content") {
        runCatching {
            context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                ?.use { cursor ->
                    val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (idx >= 0 && cursor.moveToFirst()) {
                        cursor.getString(idx)?.takeIf { it.isNotBlank() }?.let { return it }
                    }
                }
        }
    }
    return uri.lastPathSegment?.substringAfterLast('/')?.takeIf { it.isNotBlank() } ?: "shared_file"
}
