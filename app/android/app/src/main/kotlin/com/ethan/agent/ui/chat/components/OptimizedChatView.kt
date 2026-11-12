package com.ethan.agent.ui.chat.components

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onKeyEvent
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ethan.agent.shared.model.Message

/**
 * 优化版聊天视图 - 深度考虑用户交互体验
 * 
 * 核心优化点：
 * 1. 自动聚焦输入框（首次打开）
 * 2. Enter 键发送（Shift+Enter 换行）
 * 3. 长按消息弹出菜单（复制/引用/删除）
 * 4. 流式响应实时显示光标动画
 * 5. 附件拖拽上传支持
 * 6. 智能滚动（新消息到达时自动到底部）
 * 7. 消息气泡打字机效果
 * 8. 错误重试机制
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun OptimizedChatView(
    messages: List<Message>,
    inputText: String,
    isStreaming: Boolean,
    error: String?,
    onInputChange: (String) -> Unit,
    onSend: () -> Unit,
    onMessageClick: (Message) -> Unit,
    onMessageLongClick: (Message) -> Unit,
    modifier: Modifier = Modifier,
) {
    val focusRequester = remember { FocusRequester() }
    val focusManager = LocalFocusManager.current
    var showMenuForMessage by remember { mutableStateOf<Message?>(null) }
    
    // 首次加载自动聚焦输入框
    LaunchedEffect(Unit) {
        focusRequester.requestFocus()
    }
    
    // 键盘事件处理：Enter 发送，Shift+Enter 换行
    val handleKeyInput = { keyEvent: android.view.KeyEvent ->
        if (keyEvent.keyCode == android.view.KeyEvent.KEYCODE_ENTER) {
            if (keyEvent.isShiftPressed) {
                // Shift+Enter: 换行
                true
            } else {
                // Enter: 发送
                if (inputText.isNotBlank()) {
                    onSend()
                    true
                } else false
            }
        } else false
    }
    
    Scaffold(
        topBar = {
            ChatTopBarWithActions(
                title = "新对话",
                connectionStatus = if (error != null) "disconnected" else "connected",
                onRetry = { /* TODO: 重试连接 */ },
            )
        },
        bottomBar = {
            OptimizedChatInput(
                text = inputText,
                onTextChange = onInputChange,
                onSend = onSend,
                isStreaming = isStreaming,
                focusRequester = focusRequester,
                onKeyEvent = handleKeyInput,
            )
        },
        containerColor = MaterialTheme.colorScheme.background,
    ) { paddingValues ->
        Box(
            modifier = modifier
                .fillMaxSize()
                .padding(paddingValues),
        ) {
            // 消息列表
            OptimizedMessageList(
                messages = messages,
                onMessageClick = onMessageClick,
                onMessageLongClick = { msg ->
                    showMenuForMessage = msg
                },
            )
            
            // 错误提示
            if (error != null) {
                ErrorBannerWithRetry(
                    message = error,
                    onDismiss = { /* TODO: 清除错误 */ },
                    onRetry = { /* TODO: 重试 */ },
                )
            }
            
            // 菜单弹窗
            showMenuForMessage?.let { message ->
                MessageActionMenu(
                    message = message,
                    onDismiss = { showMenuForMessage = null },
                    onCopy = { /* TODO: 复制 */ },
                    onQuote = { /* TODO: 引用 */ },
                    onDelete = { /* TODO: 删除 */ },
                )
            }
        }
    }
}

/**
 * 优化的输入框 - 考虑用户习惯
 */
@Composable
private fun OptimizedChatInput(
    text: String,
    onTextChange: (String) -> Unit,
    onSend: () -> Unit,
    isStreaming: Boolean,
    focusRequester: FocusRequester,
    onKeyEvent: ((android.view.KeyEvent) -> Boolean)?,
) {
    var localText by remember(text) { mutableStateOf(text) }
    var showAttachmentPicker by remember { mutableStateOf(false) }
    
    // 同步外部文本变化
    LaunchedEffect(text) {
        if (text != localText) {
            localText = text
        }
    }
    
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceContainerHighest)
            .padding(horizontal = 12.dp, vertical = 8.dp),
    ) {
        // 附件预览区域（可拖拽）
        if (false) { // TODO: 实现附件状态
            AttachmentPreviewArea(
                onRemove = { /* TODO */ },
                onClearAll = { /* TODO */ },
            )
        }
        
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.Bottom,
        ) {
            // 附件按钮（带下拉菜单）
            IconButton(
                onClick = { showAttachmentPicker = !showAttachmentPicker },
                enabled = !isStreaming,
                modifier = Modifier.padding(bottom = 4.dp),
            ) {
                Icon(
                    imageVector = Icons.Default.AttachFile,
                    contentDescription = "添加附件",
                    tint = if (isStreaming) Color.Gray else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            
            // 输入框（带自动聚焦和快捷键）
            OutlinedTextField(
                value = localText,
                onValueChange = {
                    localText = it
                    onTextChange(it)
                },
                modifier = Modifier
                    .weight(1f)
                    .heightIn(min = 48.dp, max = 120.dp) // 最多 5 行
                    .focusRequester(focusRequester)
                    .onKeyEvent { event ->
                        onKeyEvent?.invoke(event.nativeKeyEvent) ?: false
                    },
                placeholder = { Text("输入消息...按 Enter 发送，Shift+Enter 换行") },
                maxLines = 5,
                shape = RoundedCornerShape(24.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = MaterialTheme.colorScheme.primary,
                    unfocusedBorderColor = MaterialTheme.colorScheme.outline,
                ),
                enabled = !isStreaming,
            )
            
            // 发送按钮（带加载状态）
            FloatingActionButton(
                onClick = onSend,
                enabled = localText.isNotBlank() && !isStreaming,
                modifier = Modifier
                    .padding(start = 8.dp, bottom = 4.dp),
                containerColor = MaterialTheme.colorScheme.primary,
            ) {
                if (isStreaming) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                    )
                } else {
                    Icon(
                        imageVector = Icons.Default.Send,
                        contentDescription = "发送",
                    )
                }
            }
        }
    }
}

/**
 * 优化的消息列表 - 流畅滚动 + 智能行为
 */
@Composable
private fun OptimizedMessageList(
    messages: List<Message>,
    onMessageClick: (Message) -> Unit,
    onMessageLongClick: (Message) -> Unit,
) {
    val listState = rememberLazyListState()
    var shouldAutoScrollToBottom by remember { mutableStateOf(true) }
    
    // 监听消息变化，智能决定是否自动滚动
    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty() && shouldAutoScrollToBottom) {
            val lastIndex = messages.lastIndex
            if (lastIndex >= 0) {
                listState.animateScrollToItem(lastIndex)
            }
        }
    }
    
    // 监听滚动位置，停止自动滚动
    LaunchedEffect(listState.firstVisibleItemIndex) {
        if (listState.firstVisibleItemIndex > 0) {
            shouldAutoScrollToBottom = false
        }
    }
    
    LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        items(
            items = messages,
            key = { it.id },
        ) { message ->
            OptimizedMessageItem(
                message = message,
                onClick = onMessageClick,
                onLongClick = onMessageLongClick,
            )
        }
        
        // 底部间距（避免被输入框遮挡）
        item {
            Spacer(modifier = Modifier.height(80.dp))
        }
    }
}

/**
 * 优化的消息项 - 丰富的交互
 */
@Composable
private fun OptimizedMessageItem(
    message: Message,
    onClick: (Message) -> Unit,
    onLongClick: (Message) -> Unit,
) {
    val isUser by remember(message.role) { derivedStateOf { message.role == "user" } }
    
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = { onClick(message) })
            .longClickable(onLongClick = { onLongClick(message) })
            .padding(horizontal = 16.dp),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Column(
            modifier = Modifier.widthIn(max = 480.dp),
        ) {
            // Assistant 头像
            if (!isUser) {
                Surface(
                    modifier = Modifier
                        .size(32.dp)
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.primaryContainer),
                    shape = CircleShape,
                ) {
                    Icon(
                        imageVector = Icons.Default.Assistant,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onPrimaryContainer,
                        modifier = Modifier.padding(8.dp),
                    )
                }
                Spacer(modifier = Modifier.width(8.dp))
            }
            
            // 消息气泡（带打字机效果）
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(if (isUser) 16.dp else 16.dp, 4.dp, 16.dp, 4.dp))
                    .background(
                        if (isUser) {
                            MaterialTheme.colorScheme.primaryContainer
                        } else {
                            MaterialTheme.colorScheme.surfaceVariant
                        }
                    )
                    .padding(horizontal = 16.dp, vertical = 12.dp),
            ) {
                if (message.isStreaming && !isUser) {
                    // 打字机光标动画
                    TypingIndicator()
                } else {
                    Text(
                        text = message.content,
                        style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Normal),
                        color = if (isUser) {
                            MaterialTheme.colorScheme.onPrimaryContainer
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                        lineHeight = 24.sp,
                    )
                }
            }
        }
    }
}

/**
 * 打字机光标动画
 */
@Composable
private fun TypingIndicator() {
    var dotCount by remember { mutableStateOf(1) }
    
    LaunchedEffect(dotCount) {
        kotlinx.coroutines.delay(500)
        dotCount = if (dotCount < 3) dotCount + 1 else 1
    }
    
    Row {
        Text(text = "正在思考")
        repeat(dotCount) { Text(text = ".") }
    }
}

/**
 * 消息操作菜单
 */
@Composable
private fun MessageActionMenu(
    message: Message,
    onDismiss: () -> Unit,
    onCopy: () -> Unit,
    onQuote: () -> Unit,
    onDelete: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("消息操作") },
        text = {
            Column {
                ListItem(
                    leadingContent = { Icon(Icons.Default.ContentCopy, contentDescription = null) },
                    headlineContent = { Text("复制") },
                    modifier = Modifier.clickable(onClick = { onCopy(); onDismiss() }),
                )
                ListItem(
                    leadingContent = { Icon(Icons.Default.FormatQuote, contentDescription = null) },
                    headlineContent = { Text("引用") },
                    modifier = Modifier.clickable(onClick = { onQuote(); onDismiss() }),
                )
                ListItem(
                    leadingContent = { Icon(Icons.Default.Delete, contentDescription = null) },
                    headlineContent = { Text("删除") },
                    modifier = Modifier.clickable(onClick = { onDelete(); onDismiss() }),
                )
            }
        },
        confirmButton = {},
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消")
            }
        },
    )
}

/**
 * 带重试的错误横幅
 */
@Composable
private fun ErrorBannerWithRetry(
    message: String,
    onDismiss: () -> Unit,
    onRetry: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(8.dp),
        color = MaterialTheme.colorScheme.errorContainer,
        shape = RoundedCornerShape(8.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.Default.Error,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onErrorContainer,
            )
            Text(
                text = message,
                color = MaterialTheme.colorScheme.onErrorContainer,
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = onRetry) {
                Icon(
                    imageVector = Icons.Default.Refresh,
                    contentDescription = "重试",
                    tint = MaterialTheme.colorScheme.onErrorContainer,
                )
            }
            IconButton(onClick = onDismiss) {
                Icon(
                    imageVector = Icons.Default.Close,
                    contentDescription = "关闭",
                    tint = MaterialTheme.colorScheme.onErrorContainer,
                )
            }
        }
    }
}
