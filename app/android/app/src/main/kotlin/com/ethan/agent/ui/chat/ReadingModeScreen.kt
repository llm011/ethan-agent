package com.ethan.agent.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ethan.agent.shared.UiMessage
import com.ethan.agent.ui.components.SimpleMarkdown

/**
 * 阅读模式（对齐 Web `web/components/chat/reading-mode.tsx` 的阅读形态）。
 *
 * 手机上把「阅读」这件事和「聊天气泡」分开：气泡里是消息流，字小、宽窄跟着气泡走、
 * 周围还有工具日志和统计条干扰；阅读模式则是全屏、居中定宽（对齐 Web 的 max-w-[720px]）、
 * 行高放宽、背景纯净，只留一个退出按钮。
 *
 * 与 Web 的差异（有意为之）：
 *   - 不做标注/划线/批注（Android 端的标注在独立的「标注」页管理，不在这里重复造一套选区体系）。
 *   - 不做正文编辑（移动端改 Markdown 正文体验差，且需要与后端 PATCH 对齐，超出本次范围）。
 */
@Composable
fun ReadingModeScreen(
    message: UiMessage,
    onClose: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxSize(),
        color = MaterialTheme.colorScheme.background,
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                // 阅读模式是覆盖在聊天页之上的全屏层，不经过 EthanScaffold，
                // 状态栏/导航栏 inset 得自己吃，否则正文会顶到刘海下面。
                .statusBarsPadding()
                .navigationBarsPadding(),
        ) {
            // 顶部条：只放退出 + 标题，尽量少占垂直空间（正文才是主角）
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 4.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onClose) {
                    Icon(
                        Icons.Default.Close,
                        contentDescription = "退出阅读模式",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.width(4.dp))
                Text(
                    text = "阅读模式",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Spacer(Modifier.weight(1f))
                message.createdAt?.let { ts ->
                    Text(
                        text = formatReadingTimestamp(ts),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(end = 12.dp),
                    )
                }
            }

            // 正文：居中、限宽 720dp（手机上是撑满再留 20dp 边距）、行距放宽
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 20.dp, vertical = 12.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Box(
                    // 对齐 Web reading-mode 的 max-w-[720px]：手机上 fillMaxWidth 生效，
                    // 平板/折叠屏上封顶 720dp，保证舒适行宽。
                    modifier = Modifier.fillMaxWidth().widthIn(max = 720.dp),
                ) {
                    SimpleMarkdown(
                        text = message.content,
                        textColor = MaterialTheme.colorScheme.onSurface,
                        relaxedLeading = true,
                    )
                }
                Spacer(Modifier.height(32.dp))
            }
        }
    }
}

/** 对齐 Web reading-mode 的时间格式：`yyyy-MM-dd HH:mm`（本地时区）。 */
private fun formatReadingTimestamp(epochSeconds: Long): String =
    java.text.SimpleDateFormat("yyyy-MM-dd HH:mm", java.util.Locale.getDefault())
        .format(java.util.Date(epochSeconds * 1000))
