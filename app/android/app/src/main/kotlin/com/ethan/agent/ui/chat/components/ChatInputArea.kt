package com.ethan.agent.ui.chat.components

import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp

/**
 * 聊天输入区域 - 包含文本输入和附件预览
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatInputArea(
    inputText: String,
    attachments: List<Uri>,
    isStreaming: Boolean,
    onInputChange: (String) -> Unit,
    onSend: () -> Unit,
    onUploadAttachment: () -> Unit,
    onRemoveAttachment: (Uri) -> Unit,
    modifier: Modifier = Modifier,
) {
    var text by remember(inputText) { mutableStateOf(inputText) }
    
    val canSend by remember(inputText, isStreaming) {
        derivedStateOf {
            text.isNotBlank() && !isStreaming
        }
    }
    
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceContainerHighest,
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 8.dp),
        ) {
            // 附件预览
            if (attachments.isNotEmpty()) {
                AttachmentPreviewRow(
                    attachments = attachments,
                    onRemove = onRemoveAttachment,
                )
            }
            
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.Bottom,
            ) {
                // 上传按钮
                IconButton(
                    onClick = onUploadAttachment,
                    enabled = !isStreaming,
                ) {
                    Icon(
                        imageVector = Icons.Default.AttachFile,
                        contentDescription = "上传附件",
                    )
                }
                
                // 输入框
                OutlinedTextField(
                    value = text,
                    onValueChange = {
                        text = it
                        onInputChange(it)
                    },
                    modifier = Modifier
                        .weight(1f)
                        .heightIn(min = 48.dp),
                    placeholder = { Text("输入消息...") },
                    maxLines = 5,
                    shape = RoundedCornerShape(24.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Color.Transparent,
                        unfocusedBorderColor = Color.Transparent,
                    ),
                    enabled = !isStreaming,
                )
                
                // 发送按钮
                FloatingActionButton(
                    onClick = onSend,
                    enabled = canSend,
                    modifier = Modifier.padding(start = 8.dp),
                    containerColor = MaterialTheme.colorScheme.primary,
                ) {
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
 * 附件预览行
 */
@Composable
private fun AttachmentPreviewRow(
    attachments: List<Uri>,
    onRemove: (Uri) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        attachments.forEach { uri ->
            AttachementChip(
                uri = uri,
                onRemove = { onRemove(uri) },
            )
        }
    }
}

/**
 * 附件芯片
 */
@Composable
private fun AttachementChip(
    uri: Uri,
    onRemove: () -> Unit,
) {
    Card(
        modifier = Modifier.size(60.dp),
        shape = RoundedCornerShape(8.dp),
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text(text = "附件")
            IconButton(
                onClick = onRemove,
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(4.dp),
            ) {
                Icon(
                    imageVector = Icons.Default.Close,
                    contentDescription = "移除",
                )
            }
        }
    }
}
