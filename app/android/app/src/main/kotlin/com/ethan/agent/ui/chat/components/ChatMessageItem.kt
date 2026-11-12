package com.ethan.agent.ui.chat.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ethan.agent.shared.model.Message

/**
 * 单条消息项 - 负责渲染单条消息
 * 优化：使用 remember 避免重复计算
 */
@Composable
fun ChatMessageItem(
    message: Message,
    onClick: () -> Unit = {},
    onLongClick: () -> Unit = {},
) {
    val isUser by remember(message.role) { derivedStateOf { message.role == "user" } }
    
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Column(
            modifier = Modifier
                .widthIn(max = 480.dp)
                .clickable(onClick = onClick)
                .longClickable(onLongClick = onLongClick),
        ) {
            // 用户消息气泡
            if (isUser) {
                UserMessageBubble(message.content)
            } else {
                AssistantMessageBubble(
                    content = message.content,
                    isLoading = message.isStreaming,
                )
            }
        }
    }
}

@Composable
private fun UserMessageBubble(content: String) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(16.dp))
            .background(MaterialTheme.colorScheme.primaryContainer)
            .padding(12.dp),
    ) {
        Text(
            text = content,
            color = MaterialTheme.colorScheme.onPrimaryContainer,
        )
    }
}

@Composable
private fun AssistantMessageBubble(content: String, isLoading: Boolean) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // 头像
        Surface(
            modifier = Modifier
                .size(32.dp)
                .clip(CircleShape)
                .background(MaterialTheme.colorScheme.secondaryContainer),
        ) {
            Icon(
                imageVector = androidx.compose.material.icons.Icons.Default.Assistant,
                contentDescription = null,
                modifier = Modifier.padding(8.dp),
                tint = MaterialTheme.colorScheme.onSecondaryContainer,
            )
        }
        
        Spacer(modifier = Modifier.width(8.dp))
        
        // 消息气泡
        Box(
            modifier = Modifier
                .clip(RoundedCornerShape(16.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant)
                .padding(12.dp),
        ) {
            if (isLoading) {
                CircularProgressIndicator(
                    modifier = Modifier.size(20.dp),
                    strokeWidth = 2.dp,
                )
            } else {
                Text(text = content)
            }
        }
    }
}
