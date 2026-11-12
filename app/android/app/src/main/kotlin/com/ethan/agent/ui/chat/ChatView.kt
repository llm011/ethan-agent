package com.ethan.agent.ui.chat

import androidx.compose.foundation.layout.*
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ethan.agent.shared.viewmodel.ChatViewModel
import com.ethan.agent.shared.viewmodel.ChatUiState
import com.ethan.agent.ui.chat.components.*

/**
 * 聊天主视图 - 经过深度优化的现代化聊天界面
 * 
 * 架构设计：
 * - 单一职责：只负责布局编排
 * - 性能优化：按需加载子组件
 * - 可维护性：每个组件独立测试
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ChatView(
    viewModel: ChatViewModel,
    modifier: Modifier = Modifier,
) {
    val state by viewModel.state.collectAsState()
    
    Scaffold(
        topBar = {
            ChatTopBar(
                title = state.sessionTitle ?: "新对话",
                onBackClick = viewModel::onBack,
                onOpenDrawer = viewModel::onOpenDrawer,
                connectionStatus = state.connectionState,
            )
        },
        bottomBar = {
            ChatInputArea(
                inputText = state.inputText,
                attachments = state.attachments,
                isStreaming = state.isStreaming,
                onInputChange = viewModel::onInputChange,
                onSend = viewModel::sendMessage,
                onUploadAttachment = viewModel::uploadAttachment,
                onRemoveAttachment = viewModel::removeAttachment,
            )
        },
        containerColor = MaterialTheme.colorScheme.background,
    ) { paddingValues ->
        Box(
            modifier = modifier
                .fillMaxSize()
                .padding(paddingValues)
                .imePadding(),
        ) {
            // 消息列表 - 使用高性能 LazyColumn
            ChatMessageList(
                messages = state.messages,
                onMessageClick = viewModel::onMessageClick,
                onMessageLongClick = viewModel::onMessageLongClick,
            )
            
            // Loading 覆盖层
            if (state.isLoading) {
                LoadingOverlay()
            }
            
            // 错误提示
            state.error?.let { error ->
                ErrorBanner(
                    message = error,
                    onDismiss = viewModel::clearError,
                )
            }
        }
    }
}
