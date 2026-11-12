package com.ethan.agent.ui.chat.components

import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.ethan.agent.shared.viewmodel.ChatUiState

/**
 * 输入栏组件 - 负责用户输入和发送
 * 优化：将附件预览分离，减少重绘范围
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatInputBar(
    uiState: ChatUiState,
    onInputChange: (String) -> Unit,
    onSend: () -> Unit,
    onUploadAttachment: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var inputText by remember { mutableStateOf(uiState.inputText) }
    val shouldEnableSend by remember(uiState.inputText) {
        derivedStateOf {
            uiState.inputText.isNotBlank() && !uiState.isStreaming
        }
    }
    
    Column(modifier = modifier) {
        // 附件预览区域（独立渲染）
        if (uiState.attachments.isNotEmpty()) {
            AttachmentPreviewRow(
                attachments = uiState.attachments,
                onRemoveAttachment = { uri ->
                    // TODO: 调用 ViewModel 移除附件
                },
            )
        }
        
        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = MaterialTheme.colorScheme.surfaceContainerHighest,
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 8.dp),
                verticalAlignment = Alignment.Bottom,
            ) {
                // 附件按钮
                IconButton(
                    onClick = onUploadAttachment,
                    enabled = !uiState.isStreaming,
                ) {
                    Icon(
                        imageVector = Icons.Default.AttachFile,
                        contentDescription = "上传附件",
                    )
                }
                
                // 文本输入框
                OutlinedTextField(
                    value = inputText,
                    onValueChange = {
                        inputText = it
                        onInputChange(it)
                    },
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxHeight(),
                    placeholder = { Text("输入消息...") },
                    maxLines = 5,
                    shape = RoundedCornerShape(24.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Color.Transparent,
                        unfocusedBorderColor = Color.Transparent,
                    ),
                    enabled = !uiState.isStreaming,
                )
                
                // 发送按钮
                FloatingActionButton(
                    onClick = onSend,
                    enabled = shouldEnableSend,
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
    onRemoveAttachment: (Uri) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 8.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        attachments.forEach { uri ->
            AttachementChip(
                uri = uri,
                onRemove = { onRemoveAttachment(uri) },
            )
        }
    }
}

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

@Composable
private fun Spacer40dp() {
    Spacer(modifier = Modifier.height(40.dp))
}
