package com.ethan.agent.ui.chat.components

import androidx.compose.foundation.layout.RowScope
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.ethan.agent.shared.viewmodel.ChatUiState

/**
 * 聊天顶部工具栏 - 统一导航和菜单操作
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatTopBar(
    state: ChatUiState,
    onBackClick: () -> Unit,
    onOpenDrawer: () -> Unit,
    actions: @Composable RowScope.() -> Unit = {},
    modifier: Modifier = Modifier,
) {
    TopAppBar(
        title = {
            Text(
                text = if (state.sessionTitle.isNullOrBlank()) "新对话" else state.sessionTitle,
                maxLines = 1,
            )
        },
        navigationIcon = {
            IconButton(onClick = onBackClick) {
                Icon(
                    imageVector = Icons.Default.ArrowBack,
                    contentDescription = "返回",
                )
            }
        },
        actions = {
            // 连接状态指示器
            ConnectionStatusIndicator(state.connectionState)
            
            // 自定义操作按钮
            actions()
            
            // 更多菜单
            MoreMenuButton(onClick = onOpenDrawer)
        },
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = MaterialTheme.colorScheme.surface,
            titleContentColor = MaterialTheme.colorScheme.onSurface,
            navigationIconContentColor = MaterialTheme.colorScheme.onSurface,
            actionIconContentColor = MaterialTheme.colorScheme.onSurfaceVariant,
        ),
        modifier = modifier.statusBarsPadding(),
    )
}

/**
 * 连接状态指示器
 */
@Composable
private fun ConnectionStatusIndicator(connectionState: String) {
    when (connectionState) {
        "connected" -> {} // 正常状态不显示
        "connecting" -> {
            CircularProgressIndicator(
                modifier = Modifier.size(20.dp),
                strokeWidth = 2.dp,
            )
        }
        "disconnected" -> {
            Surface(
                modifier = Modifier
                    .size(20.dp)
                    .clip(androidx.compose.foundation.shape.CircleShape)
                    .background(Color.Red),
            ) {}
        }
        else -> {}
    }
}

/**
 * 更多菜单按钮
 */
@Composable
private fun MoreMenuButton(onClick: () -> Unit) {
    IconButton(onClick = onClick) {
        Icon(
            imageVector = Icons.Default.MoreVert,
            contentDescription = "更多选项",
        )
    }
}
