package com.ethan.agent.ui.chat

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import com.ethan.agent.core.model.Quote
import com.ethan.agent.data.UiMessage
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer
import com.ethan.agent.ui.components.ToolTimeline
import com.ethan.agent.ui.components.SimpleMarkdown
import java.io.File
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
    onUpload: (File, String) -> Unit,
    onConsent: (Boolean) -> Unit,
    onDismissConsent: () -> Unit,
    onStop: () -> Unit,
    onOnboardingChange: (String, String) -> Unit,
    onCompleteOnboarding: () -> Unit,
    onDismissOnboarding: () -> Unit,
    onClearError: () -> Unit,
    onScrollToBottom: () -> Unit = {},
    onResumeStream: () -> Unit = {},
) {
    val snackbar = remember { SnackbarHostState() }
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var showPlusSheet by remember { mutableStateOf(false) }

    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        uri ?: return@rememberLauncherForActivityResult
        val name = uri.lastPathSegment ?: "file"
        context.contentResolver.openInputStream(uri)?.use { input ->
            val temp = File(context.cacheDir, name)
            temp.outputStream().use { output -> input.copyTo(output) }
            onUpload(temp, name)
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
        if (state.messages.isNotEmpty()) {
            if (isAtBottom) {
                listState.animateScrollToItem(state.messages.lastIndex)
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
                        modifier = Modifier.menuAnchor().fillMaxWidth(),
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
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.surface,
                shadowElevation = 2.dp,
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        text = state.title,
                        style = MaterialTheme.typography.titleLarge,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    ConnectionStateIndicator(state.connectionState, state.isResuming)
                }
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

        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .imePadding(),
        ) {
            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).padding(horizontal = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (state.messages.isEmpty()) {
                    item {
                        EmptyChatState(onQuickAction = { text ->
                            onInputChange(text)
                            onSend()
                        })
                    }
                } else {
                    itemsIndexed(state.messages) { _, msg ->
                        MessageBubble(msg, onLongPress = {
                            onQuote(Quote(role = msg.role, content = msg.content))
                        })
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
                    modifier = Modifier.padding(horizontal = 12.dp),
                )
            }

            // + 按钮 + 输入框 (send button inside)
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.surface,
                shadowElevation = 4.dp,
                shape = RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp),
            ) {
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.Bottom,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    // + button
                    Surface(
                        shape = RoundedCornerShape(50),
                        color = MaterialTheme.colorScheme.primary.copy(alpha = 0.12f),
                        modifier = Modifier.size(40.dp),
                    ) {
                        IconButton(onClick = { showPlusSheet = true }) {
                            Icon(
                                Icons.Default.Add,
                                contentDescription = "更多选项",
                                tint = MaterialTheme.colorScheme.primary,
                            )
                        }
                    }
                    // Input field with send button inside
                    Surface(
                        modifier = Modifier.weight(1f),
                        shape = RoundedCornerShape(24.dp),
                        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                    ) {
                        Row(
                            modifier = Modifier.padding(end = 4.dp),
                            verticalAlignment = Alignment.Bottom,
                        ) {
                            OutlinedTextField(
                                value = state.inputText,
                                onValueChange = onInputChange,
                                modifier = Modifier.weight(1f),
                                placeholder = {
                                    Text(
                                        if (state.isStreaming) "补充信息给 Agent…" else "输入消息…",
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                },
                                maxLines = 5,
                                shape = RoundedCornerShape(24.dp),
                                colors = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
                                    focusedBorderColor = androidx.compose.ui.graphics.Color.Transparent,
                                    unfocusedBorderColor = androidx.compose.ui.graphics.Color.Transparent,
                                ),
                            )
                            Box(
                                modifier = Modifier.padding(bottom = 8.dp, end = 4.dp),
                                contentAlignment = Alignment.Center,
                            ) {
                                when {
                                    state.isStopping -> {
                                        CircularProgressIndicator(Modifier.size(20.dp))
                                    }
                                    state.isStreaming || state.isResuming -> {
                                        Surface(
                                            shape = RoundedCornerShape(50),
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
                                            shape = RoundedCornerShape(50),
                                            color = if (state.inputText.isNotBlank()) MaterialTheme.colorScheme.primary
                                                else MaterialTheme.colorScheme.surfaceVariant,
                                            modifier = Modifier.size(36.dp),
                                        ) {
                                            IconButton(
                                                onClick = onSend,
                                                enabled = state.inputText.isNotBlank(),
                                            ) {
                                                Icon(
                                                    Icons.AutoMirrored.Filled.Send,
                                                    contentDescription = "发送",
                                                    tint = if (state.inputText.isNotBlank()) MaterialTheme.colorScheme.onPrimary
                                                        else MaterialTheme.colorScheme.onSurfaceVariant,
                                                    modifier = Modifier.size(20.dp),
                                                )
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
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

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MessageBubble(message: UiMessage, onLongPress: () -> Unit) {
    val isUser = message.role == "user"
    val alignment = if (isUser) Alignment.CenterEnd else Alignment.CenterStart
    val bg = if (isUser) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant

    Box(Modifier.fillMaxWidth(), contentAlignment = alignment) {
        Card(
            modifier = Modifier
                .widthIn(max = 320.dp)
                .combinedClickable(onClick = {}, onLongClick = onLongPress),
            shape = RoundedCornerShape(16.dp),
        ) {
            Column(
                Modifier.background(bg).padding(12.dp),
            ) {
                message.quote?.let {
                    Text(
                        "↩ ${it.content.take(60)}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.padding(2.dp))
                }
                if (message.content.isNotBlank()) {
                    SimpleMarkdown(text = message.content)
                }
                if (message.isStreaming && message.content.isEmpty()) {
                    Text("思考中…", style = MaterialTheme.typography.bodySmall)
                }
                if (message.toolSteps.isNotEmpty()) {
                    ToolTimeline(message.toolSteps)
                }
                message.usage?.let {
                    Text(
                        "tokens: ${it.input}+${it.output}",
                        style = MaterialTheme.typography.labelSmall,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun EmptyChatState(onQuickAction: (String) -> Unit) {
    val quickActions = listOf(
        "☀️ 深圳的天气怎么样" to "深圳的天气怎么样",
        "📄 帮我找找最新的 Agent 论文" to "帮我找找最新的 Agent 论文",
    )
    Column(
        modifier = Modifier
            .fillMaxSize()
            .wrapContentHeight(Alignment.CenterVertically)
            .padding(horizontal = 24.dp, vertical = 30.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // 头像
        Surface(
            shape = RoundedCornerShape(24.dp),
            color = MaterialTheme.colorScheme.primaryContainer,
            modifier = Modifier.size(80.dp),
        ) {
            Box(contentAlignment = Alignment.Center) {
                Text(
                    "🤖",
                    style = MaterialTheme.typography.displaySmall,
                )
            }
        }
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
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.padding(top = 4.dp),
        ) {
            quickActions.forEach { (label, payload) ->
                Surface(
                    shape = RoundedCornerShape(20.dp),
                    color = MaterialTheme.colorScheme.surface,
                    border = BorderStroke(
                        1.5.dp,
                        MaterialTheme.colorScheme.outlineVariant,
                    ),
                    modifier = Modifier.clickable { onQuickAction(payload) },
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
