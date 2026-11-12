package com.ethan.agent.ui.chat

import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import com.ethan.agent.ui.chat.components.ChatInputBar
import com.ethan.agent.ui.chat.components.ChatMessageList
import com.ethan.agent.ui.chat.components.ChatTopBar
import com.ethan.agent.shared.viewmodel.ChatViewModel
import com.ethan.agent.shared.viewmodel.ChatUiState

/**
 * 优化版聊天界面 - 性能优化和代码结构改进
 * 
 * 主要优化点：
 * 1. 使用 remember 缓存计算结果
 * 2. 将 UI 拆分为独立组件（ChatMessageList, ChatInputBar, ChatTopBar）
 * 3. LazyColumn 使用 key 提升列表性能
 * 4. 自动滚动到底部优化
 * 5. 统一的错误处理和加载状态
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun OptimizedChatScreen(
    state: ChatUiState,
    onInputChange: (String) -> Unit,
    onSend: () -> Unit,
    onModelSelected: (String) -> Unit,
    onModeSelected: (String) -> Unit,
    onQuote: (String) -> Unit,
    onUploadAttachment: () -> Unit,
    onAddImage: () -> Unit,
    onRemoveImage: (Uri) -> Unit,
    onConsent: (Boolean) -> Unit,
    onDismissConsent: () -> Unit,
    onAskUserRespond: (String) -> Unit,
    onWaitForUserRespond: (String) -> Unit,
    onStop: () -> Unit,
    onClearError: () -> Unit,
    onOpenDrawer: () -> Unit,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    var showConsentDialog by remember { mutableStateOf(false) }
    
    // 文件选择器 - 使用 rememberLauncherForActivityResult 避免重复创建
    val filePicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent(),
        onResult = { uri: Uri? ->
            uri?.let {
                // TODO: 调用 ViewModel 处理上传
            }
        },
    )
    
    // 图片选择器
    val imagePicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent(),
        onResult = { uri: Uri? ->
            uri?.let {
                onAddImage()
            }
        },
    )
    
    //  consent 弹窗管理
    LaunchedEffect(state.consentRequired) {
        if (state.consentRequired) {
            showConsentDialog = true
        }
    }
    
    BackHandler(enabled = state.canGoBack) {
        onBack()
    }
    
    Scaffold(
        topBar = {
            ChatTopBar(
                state = state,
                onBackClick = onBack,
                onOpenDrawer = onOpenDrawer,
            )
        },
        bottomBar = {
            ChatInputBar(
                uiState = state,
                onInputChange = onInputChange,
                onSend = onSend,
                onUploadAttachment = { filePicker.launch("*/*") },
            )
        },
        containerColor = MaterialTheme.colorScheme.background,
        contentColor = Color.Black,
    ) { paddingValues ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .imePadding(),
        ) {
            // 消息列表 - 使用优化后的组件
            ChatMessageList(
                messages = state.messages,
                onMessageClick = { message ->
                    // TODO: 实现消息点击处理
                },
                onMessageLongClick = { message ->
                    // TODO: 实现长按菜单
                },
            )
            
            // Loading 覆盖层
            if (state.isLoading) {
                LoadingOverlay()
            }
            
            // 错误提示
            if (state.error != null) {
                ErrorBanner(
                    error = state.error,
                    onDismiss = onClearError,
                )
            }
        }
    }
}

/**
 * Loading 覆盖层
 */
@Composable
private fun LoadingOverlay() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.copy(alpha = 0.3f)),
        contentAlignment = Alignment.Center,
    ) {
        CircularProgressIndicator()
    }
}

/**
 * 错误横幅
 */
@Composable
private fun ErrorBanner(error: String, onDismiss: () -> Unit) {
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
        ) {
            Text(
                text = error,
                color = MaterialTheme.colorScheme.onErrorContainer,
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = onDismiss) {
                Icon(
                    imageVector = androidx.compose.material.icons.Icons.Default.Close,
                    contentDescription = "关闭",
                )
            }
        }
    }
}
