package com.ethan.agent.ui.chat

import com.ethan.agent.shared.viewmodel.ChatUiState
import com.ethan.agent.shared.viewmodel.ConnectionState

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
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
import androidx.compose.foundation.layout.wrapContentHeight
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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import com.ethan.agent.R
import com.ethan.agent.core.model.Quote
import com.ethan.agent.shared.UiMessage
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer
import com.ethan.agent.ui.components.ToolTimeline
import com.ethan.agent.ui.components.SimpleMarkdown
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import coil.compose.rememberAsyncImagePainter
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch

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
    onStop: () -> Unit,
    onOnboardingChange: (String, String) -> Unit,
    onCompleteOnboarding: () -> Unit,
    onDismissOnboarding: () -> Unit,
    onClearError: () -> Unit,
    onScrollToBottom: () -> Unit = {},
    onResumeStream: () -> Unit = {},
    onOpenDrawer: () -> Unit = {},
) {
    val snackbar = remember { SnackbarHostState() }
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var showPlusSheet by remember { mutableStateOf(false) }
    // 动态测量输入框区域高度，让消息列表 bottom padding 自适应（避免被输入框遮挡）
    val density = LocalDensity.current
    var inputBarHeightPx by remember { mutableStateOf(0) }
    val inputBarHeightDp = with(density) { inputBarHeightPx.toDp() }

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
                    shape = RoundedCornerShape(12.dp),
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

                // Model selector
                Text("模型", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                var modelExpanded by remember { mutableStateOf(false) }
                ExposedDropdownMenuBox(expanded = modelExpanded, onExpandedChange = { modelExpanded = it }) {
                    AssistChip(
                        onClick = { modelExpanded = true },
                        label = { Text(state.selectedModel ?: "选择模型", maxLines = 1) },
                        modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
                    )
                    ExposedDropdownMenu(expanded = modelExpanded, onDismissRequest = { modelExpanded = false }) {
                        state.models.forEach { model ->
                            DropdownMenuItem(
                                text = { Text(model.id) },
                                onClick = {
                                    onModelSelected(model.id)
                                    modelExpanded = false
                                },
                            )
                        }
                    }
                }

                // Mode chips
                if (state.modes.isNotEmpty()) {
                    Text("模式", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        state.modes.forEach { mode ->
                            FilterChip(
                                selected = state.selectedMode == mode.key,
                                onClick = { onModeSelected(if (state.selectedMode == mode.key) "" else mode.key) },
                                label = { Text(mode.label) },
                            )
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

    Scaffold(
        topBar = {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
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

        Box(
            Modifier
                .fillMaxSize()
                .padding(top = padding.calculateTopPadding())
                .imePadding(),
        ) {
            // 消息列表（底部留出输入框的空间）
            LazyColumn(
                state = listState,
                modifier = Modifier.fillMaxSize().padding(horizontal = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                contentPadding = PaddingValues(bottom = inputBarHeightDp + 8.dp),
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
                    itemsIndexed(visibleMessages) { _, msg ->
                        MessageBubble(msg, onLongPress = {
                            onQuote(Quote(role = msg.role, content = msg.content))
                        })
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

            // 输入框区域 — 绝对定位在底部
            Column(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .background(MaterialTheme.colorScheme.background)
                    .navigationBarsPadding()
                    .padding(horizontal = 12.dp)
                    .onGloballyPositioned { inputBarHeightPx = it.size.height },
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
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
                                        .clip(RoundedCornerShape(8.dp)),
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

                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    color = MaterialTheme.colorScheme.surface,
                    shadowElevation = 6.dp,
                    shape = RoundedCornerShape(28.dp),
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
                                            Text(
                                                if (state.isStreaming) "补充信息给 Agent…" else "输入消息，支持 Markdown…",
                                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                                                style = MaterialTheme.typography.bodyMedium,
                                            )
                                        }
                                        innerTextField()
                                    }
                                },
                            )
                            Box(
                                modifier = Modifier.padding(end = 2.dp),
                                contentAlignment = Alignment.Center,
                            ) {
                                when {
                                    state.isStopping -> {
                                        CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
                                    }
                                    state.isStreaming || state.isResuming -> {
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
                                    else -> {
                                        Surface(
                                            shape = CircleShape,
                                            color = if (state.inputText.isNotBlank() || state.pendingImages.isNotEmpty()) MaterialTheme.colorScheme.primary
                                                else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                                            modifier = Modifier.size(36.dp),
                                        ) {
                                            IconButton(
                                                onClick = onSend,
                                                enabled = state.inputText.isNotBlank() || state.pendingImages.isNotEmpty(),
                                            ) {
                                                Icon(
                                                    Icons.AutoMirrored.Filled.Send,
                                                    contentDescription = "发送",
                                                    tint = if (state.inputText.isNotBlank() || state.pendingImages.isNotEmpty()) MaterialTheme.colorScheme.onPrimary
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

                Text(
                    text = "对话由 AI 生成",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                    modifier = Modifier.padding(top = 2.dp, bottom = 4.dp),
                )
            } // end input Column (bottom-aligned)
        }
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
    Surface(
        shape = RoundedCornerShape(50),
        color = color.copy(alpha = 0.15f),
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = color,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
        )
    }
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
private fun MessageBubble(message: UiMessage, onLongPress: () -> Unit) {
    val isUser = message.role == "user"
    val bubbleColor = if (isUser) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.7f)
    }
    val textColor = if (isUser) {
        MaterialTheme.colorScheme.onPrimary
    } else {
        MaterialTheme.colorScheme.onSurface
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 4.dp, vertical = 2.dp),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.Bottom,
    ) {
        // Assistant avatar (left)
        if (!isUser) {
            Image(
                painter = painterResource(id = R.mipmap.ic_launcher_round),
                contentDescription = "Assistant",
                modifier = Modifier
                    .size(30.dp)
                    .clip(CircleShape),
            )
            Spacer(Modifier.width(6.dp))
        }

        // Bubble content
        Column(
            modifier = Modifier.widthIn(max = 310.dp),
            horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
        ) {
            Surface(
                modifier = Modifier.combinedClickable(
                    interactionSource = remember { MutableInteractionSource() },
                    indication = null,
                    onClick = {},
                    onLongClick = onLongPress,
                ),
                shape = RoundedCornerShape(
                    topStart = 18.dp,
                    topEnd = 18.dp,
                    bottomStart = if (isUser) 18.dp else 4.dp,
                    bottomEnd = if (isUser) 4.dp else 18.dp,
                ),
                color = bubbleColor,
                shadowElevation = 0.dp,
            ) {
                Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
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
                                        .clip(RoundedCornerShape(8.dp)),
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
                            ToolTimeline(message.toolSteps)
                        }
                        if (message.content.isNotBlank()) {
                            Spacer(Modifier.height(6.dp))
                        }
                    }
                    // 文本结论在后
                    if (message.content.isNotBlank()) {
                        SimpleMarkdown(
                            text = message.content,
                            textColor = textColor,
                        )
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
    }
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
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.spacedBy(4.dp),
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

        // Token usage pill
        message.usage?.let { u ->
            if (u.input > 0 || u.output > 0) {
                StatPill(
                    text = "↑${formatTokenCount(u.input)} ↓${formatTokenCount(u.output)}" +
                        if (u.cache > 0) " ⚡${formatTokenCount(u.cache)}" else "",
                    color = Color(0xFF4CAF50),
                )
            }
        }

        // TTFB pill
        message.ttfbMs?.let { ms ->
            StatPill(text = "TTFB ${formatDuration(ms)}", color = Color(0xFFFF9800))
        }

        // Total duration pill
        message.totalDurationMs?.let { ms ->
            StatPill(text = "总 ${formatDuration(ms)}", color = Color(0xFF9C27B0))
        }

        // Generation duration pill
        message.generationDurationMs?.let { ms ->
            StatPill(text = "生成 ${formatDuration(ms)}", color = Color(0xFF009688))
        }
    }
}

@Composable
private fun StatPill(text: String, color: Color) {
    Surface(
        shape = RoundedCornerShape(10.dp),
        color = color.copy(alpha = 0.12f),
        modifier = Modifier.padding(end = 4.dp),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            color = color,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
        )
    }
}

private fun formatTokenCount(count: Int): String = when {
    count >= 1000 -> "${count / 1000}k"
    else -> count.toString()
}

private fun formatDuration(ms: Long): String = when {
    ms >= 1000 -> "${String.format("%.1f", ms / 1000.0)}s"
    else -> "${ms}ms"
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
    Column(
        modifier = modifier
            .wrapContentHeight(Alignment.CenterVertically)
            .padding(horizontal = 24.dp, vertical = 30.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // 头像 - 圆形 app logo
        Image(
            painter = painterResource(id = R.mipmap.ic_launcher_round),
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
                    shape = RoundedCornerShape(20.dp),
                    color = MaterialTheme.colorScheme.surface,
                    border = BorderStroke(
                        1.5.dp,
                        MaterialTheme.colorScheme.outlineVariant,
                    ),
                ) {
                    Text(
                        text = label,
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onBackground,
                        fontWeight = FontWeight.Medium,
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

private fun queryDisplayName(context: Context, uri: Uri): String {
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
