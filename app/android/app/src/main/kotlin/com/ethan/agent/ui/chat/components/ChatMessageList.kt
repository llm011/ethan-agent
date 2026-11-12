package com.ethan.agent.ui.chat.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ethan.agent.shared.model.Message

/**
 * 高性能消息列表 - 深度优化的 LazyColumn
 * 
 * 优化点：
 * 1. 使用 key 提升渲染性能
 * 2. 自动滚动到底部
 * 3. 避免不必要的 recomposition
 */
@Composable
fun ChatMessageList(
    messages: List<Message>,
    onMessageClick: (Message) -> Unit,
    onMessageLongClick: (Message) -> Unit,
    modifier: Modifier = Modifier,
) {
    val listState = rememberLazyListState()
    
    // 自动滚动到最新消息
    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) {
            val lastIndex = messages.lastIndex
            if (lastIndex >= 0) {
                listState.animateScrollToItem(lastIndex)
            }
        }
    }
    
    LazyColumn(
        state = listState,
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        items(
            items = messages,
            key = { it.id }, // 关键优化：唯一 ID
        ) { message ->
            ChatMessageItem(
                message = message,
                onClick = { onMessageClick(message) },
                onLongClick = { onMessageLongClick(message) },
            )
        }
        
        // 底部间距
        item {
            Spacer(modifier = Modifier.height(80.dp))
        }
    }
}

/**
 * 单条消息项 - 专业级设计
 */
@Composable
private fun ChatMessageItem(
    message: Message,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
) {
    val isUser by remember(message.role) { derivedStateOf { message.role == "user" } }
    
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .longClickable(onLongClick = onLongClick)
            .padding(horizontal = 16.dp),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Column(
            modifier = Modifier.widthIn(max = 480.dp),
        ) {
            if (!isUser) {
                // Assistant 头像
                Surface(
                    modifier = Modifier
                        .size(32.dp)
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.primaryContainer),
                    shape = CircleShape,
                ) {
                    Icon(
                        imageVector = androidx.compose.material.icons.Icons.Default.Assistant,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onPrimaryContainer,
                        modifier = Modifier.padding(8.dp),
                    )
                }
                
                Spacer(modifier = Modifier.width(8.dp))
            }
            
            // 消息气泡
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
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    Text(
                        text = message.content,
                        style = MaterialTheme.typography.bodyMedium,
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
