package com.ethan.agent.ui.chat

import androidx.compose.foundation.layout.statusBarsPadding
import com.ethan.agent.shared.viewmodel.ChatUiState
import com.ethan.agent.shared.viewmodel.ConnectionState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.ServerUrlUtils
import com.ethan.agent.ui.components.EthanBadge
import kotlinx.coroutines.launch

/** Session actions, connection state, and external-kernel session identity. */
@Composable
internal fun ChatHeader(
    state: ChatUiState,
    onOpenDrawer: () -> Unit,
    onReloadSession: () -> Unit,
    onShare: (Int) -> Unit,
    snackbar: SnackbarHostState,
) {
    val clipboard = LocalClipboardManager.current
    val scope = rememberCoroutineScope()
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .statusBarsPadding(),
    ) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 4.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        IconButton(onClick = onOpenDrawer) {
            Icon(
                Icons.Default.Menu,
                contentDescription = "菜单",
                tint = MaterialTheme.colorScheme.onSurface,
            )
        }
        Text(
            text = state.title,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.primary,
            // 单行 + 省略号：标题过长时不能换行把右侧的连接状态徽章挤走
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f, fill = false),
        )
        // 右上角动作区：重新拉取 + 复制会话链接（对齐桌面端 chat-header 的两个图标）。
        //
        // 排布上放在连接状态徽章**之前**：徽章是环境态（只在离线/重连中/生成中
        // 才出现），按钮是常驻操作。按钮放在标题旁边，徽章出现在最右端时不会把
        // 已形成的肌肉记忆位置推走。
        //
        // 新会话（sessionId == null）两件都没有对象（无线可重拉、无链可复制），
        // 直接不渲染 —— 显一个点不动的死按钮比不显示更容易让人以为坏了。
        val sessionLink = state.sessionId?.let {
            ServerUrlUtils.toSessionWebUrl(state.serverUrl, it)
        }
        if (state.sessionId != null) {
            // 生成中禁用（不是隐藏）：按钮留在原位、置灰，用户能看出「现在不能刷」。
            // 生成中不给刷的理由见 ChatViewModel.reloadSession —— 本地是按索引覆写
            // 消息列表的，刷新会把正在生成的那条写到别的消息上。
            val reloadBusy = state.isReloading
            IconButton(
                onClick = onReloadSession,
                enabled = !reloadBusy && !state.isStreaming && !state.isResuming,
            ) {
                if (reloadBusy) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        strokeWidth = 2.dp,
                    )
                } else {
                    Icon(
                        Icons.Default.Refresh,
                        contentDescription = "重新拉取会话最新内容",
                        tint = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }
        if (sessionLink != null) {
            IconButton(onClick = {
                // 剪贴板写入本身不会失败（没有权限/异步确认），拿到链接就一定能置入；
                // 仍然给一次轻提示，否则用户无法确认到底复制没复制。
                clipboard.setText(AnnotatedString(sessionLink))
                scope.launch { snackbar.showSnackbar("已复制会话链接") }
            }) {
                Icon(
                    Icons.Default.Link,
                    contentDescription = "复制会话链接",
                    tint = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
        if (state.messages.any { !it.isStreaming && (it.content.isNotBlank() || it.cards.isNotEmpty()) }) {
            IconButton(onClick = {
                val lastIdx = state.messages.indexOfLast {
                    !it.isStreaming && (it.content.isNotBlank() || it.cards.isNotEmpty())
                }
                if (lastIdx >= 0) onShare(lastIdx)
            }) {
                Icon(
                    Icons.Default.Share,
                    contentDescription = "分享对话",
                    tint = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
        ConnectionStateIndicator(state.connectionState, state.isResuming)
    }

    // 外部内核的 session id：用户拿它去命令行定位这条对话
    // （如 `dsh --session-id <id>` / `claude --resume <uuid>`）。
    // 只在用外部内核时出现——原生内核用 Ethan 自己的会话 id，无需展示。
    if (state.kernelSessionId.isNotEmpty()) {
        KernelSessionBadge(
            sessionId = state.kernelSessionId,
            kernelKind = state.kernelKind,
            onCopy = { id ->
                clipboard.setText(AnnotatedString(id))
                scope.launch { snackbar.showSnackbar("已复制 ${'$'}id 内核对会话 ID") }
            },
        )
    }
    }
}

@Composable
private fun ConnectionStateIndicator(state: ConnectionState, isResuming: Boolean) {
    val (color, label) = when {
        isResuming -> Pair(MaterialTheme.colorScheme.tertiary, "重连中…")
        state == ConnectionState.Streaming -> Pair(MaterialTheme.colorScheme.error, "生成中")
        // 离线（服务端不可达）与断线（run 断了）都给「离线」这一类文案即可 ——
        // 顶部横幅已经区分了两者，这个 badge 位置窄，再分两行会挤。
        state == ConnectionState.Offline -> Pair(MaterialTheme.colorScheme.error, "离线")
        state == ConnectionState.Disconnected -> Pair(MaterialTheme.colorScheme.error, "已断开")
        else -> return
    }
    EthanBadge(
        text = label,
        containerColor = color.copy(alpha = 0.15f),
        contentColor = color,
    )
}

/**
 * 外部内核会话 ID 徽章。
 *
 * 为什么需要它：用 DSH / Claude Code 内核时，真正在跑的是它们的 CLI，
 * 会话也是它们那边建的。用户想在命令行接着聊（`dsh --session-id <id>`、
 * `claude --resume <uuid>`）就必须能拿到这个 id。
 *
 * 设计取舍：
 *  · 只显示前 12 位 + 省略号 —— 完整 UUID 36 个字符会把顶栏挤爆
 *  · 点一下复制完整值，用 snackbar 确认（移动端没有 hover 反馈）
 *  · 原生内核下不渲染：那时用 Ethan 自己的会话 id，多显示一行纯噪声
 */
@Composable
private fun KernelSessionBadge(
    sessionId: String,
    kernelKind: String,
    onCopy: (String) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 52.dp, end = 12.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val label = kernelKind.ifBlank { "kernel" }
        Surface(
            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
            shape = RoundedCornerShape(10.dp),
        ) {
            Row(
                modifier = Modifier.padding(start = 8.dp, end = 2.dp, top = 1.dp, bottom = 1.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "$label:",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                )
                Spacer(Modifier.width(3.dp))
                Text(
                    text = if (sessionId.length > 12) "${sessionId.take(12)}…" else sessionId,
                    style = MaterialTheme.typography.labelSmall,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                IconButton(
                    onClick = { onCopy(sessionId) },
                    modifier = Modifier.size(22.dp),
                ) {
                    Icon(
                        Icons.Default.ContentCopy,
                        contentDescription = "复制完整 session id",
                        modifier = Modifier.size(12.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

/** Offline retries automatically; a disconnected live run can be manually resumed. */
@Composable
internal fun ChatConnectionBanner(state: ConnectionState, onResumeStream: () -> Unit) {
    // 断线横幅。两种断线给**不同的文案和动作**，因为用户的下一步操作不同：
    //   - Offline（服务端不可达）：重连按钮没用（网络就没通），所以不提供按钮，
    //     只说明正在自动重试 —— 恢复后横幅会自己消失，不需要用户做任何事。
    //   - Disconnected（生成流断了但服务端还活着）：手动「重连」有意义，
    //     因为服务端那边 run 可能还在跑，接回去就能继续看输出。
    when (state) {
        ConnectionState.Offline -> {
            Surface(
                color = MaterialTheme.colorScheme.errorContainer,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Row(
                    Modifier.padding(horizontal = 16.dp, vertical = 8.dp).fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("网络已断开，正在自动重连…", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        ConnectionState.Disconnected -> {
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
        else -> Unit
    }
}
