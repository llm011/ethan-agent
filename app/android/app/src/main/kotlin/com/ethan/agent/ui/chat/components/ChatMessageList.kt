package com.ethan.agent.ui.chat.components

import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import com.ethan.agent.shared.model.Message

/**
 * 消息列表组件 - 负责渲染对话消息
 * 性能优化：使用 rememberLazyListState + LaunchedEffect 实现自动滚动到底部
 */
@Composable
fun ChatMessageList(
    messages: List<Message>,
    modifier: Modifier = Modifier,
    onMessageClick: (Message) -> Unit = {},
    onMessageLongClick: (Message) -> Unit = {},
) {
    val listState = rememberLazyListState()
    
    // 自动滚动到底部 - 当新消息到达时
    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) {
            val lastMessageIndex = messages.size - 1
            if (lastMessageIndex > 0) {
                listState.scrollToItem(lastMessageIndex)
            }
        }
    }
    
    LazyColumn(
        state = listState,
        modifier = modifier,
        reverseLayout = false,
    ) {
        items(
            items = messages,
            key = { it.id }, // 使用唯一 ID 提升性能
        ) { message ->
            ChatMessageItem(
                message = message,
                onClick = { onMessageClick(message) },
                onLongClick = { onMessageLongClick(message) },
            )
        }
        
        // 底部 padding，避免内容被输入框遮挡
        item {
            Spacer40dp()
        }
    }
}
