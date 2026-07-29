package com.ethan.agent.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size

import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.ToolStep

@Composable
fun LoadingBox(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
    }
}

@Composable
fun ErrorSnackbar(
    error: String?,
    onDismiss: () -> Unit,
    snackbarHostState: SnackbarHostState,
) {
    LaunchedEffect(error) {
        if (error != null) {
            snackbarHostState.showSnackbar(error)
            onDismiss()
        }
    }
}

@Composable
fun SnackbarContainer(snackbarHostState: SnackbarHostState) {
    SnackbarHost(hostState = snackbarHostState)
}

/**
 * 通用顶栏：标题居中，左侧返回按钮，右侧可选操作按钮。
 * 紧凑无多余空白，参考图 3 风格。
 */
@Composable
fun EthanTopBar(
    title: String,
    subtitle: String? = null,
    onBack: (() -> Unit)? = null,
    actions: @Composable RowScope.() -> Unit = {},
) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(48.dp)
            .padding(horizontal = 4.dp),
    ) {
            // 左侧返回
            if (onBack != null) {
                IconButton(
                    onClick = onBack,
                    modifier = Modifier.align(Alignment.CenterStart),
                ) {
                    Icon(
                        Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = "返回",
                        tint = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
            // 中间标题
            Column(
                modifier = Modifier.align(Alignment.Center),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.SemiBold),
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (subtitle != null) {
                    Text(
                        text = subtitle,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            // 右侧操作按钮
            Row(
                modifier = Modifier.align(Alignment.CenterEnd),
                content = actions,
            )
    }
}

/**
 * 通用可横滑 Tab 栏：
 * - 单行不换行，文字超长省略
 * - 超出屏宽时可手势横向滚动
 * - 选中项有底部指示条
 */
@Composable
fun <T> EthanScrollableTabBar(
    tabs: List<T>,
    selectedTab: T,
    onTabSelected: (T) -> Unit,
    labelOf: (T) -> String,
    modifier: Modifier = Modifier,
) {
    val scrollState = rememberScrollState()
    Row(
        modifier = modifier
            .fillMaxWidth()
            .horizontalScroll(scrollState)
            .padding(horizontal = 12.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        tabs.forEach { tab ->
            val selected = tab == selectedTab
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier
                    .clickable(
                        indication = null,
                        interactionSource = remember { MutableInteractionSource() },
                    ) { onTabSelected(tab) }
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Text(
                    text = labelOf(tab),
                    style = MaterialTheme.typography.bodyMedium.copy(
                        fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                    ),
                    color = if (selected) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (selected) {
                    Surface(
                        modifier = Modifier.padding(top = 4.dp).size(width = 24.dp, height = 3.dp),
                        shape = RoundedCornerShape(2.dp),
                        color = MaterialTheme.colorScheme.primary,
                    ) {}
                }
            }
        }
    }
}

@Composable
fun ToolTimeline(steps: List<ToolStep>, modifier: Modifier = Modifier) {
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(2.dp)) {
        steps.forEach { step ->
            CollapsibleToolItem(step)
        }
    }
}

@Composable
private fun CollapsibleToolItem(step: ToolStep) {
    var expanded by remember { mutableStateOf(false) }
    val hasDetail = !step.resultPreview.isNullOrBlank() || !step.resultDetail.isNullOrBlank()

    Surface(
        shape = RoundedCornerShape(8.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(horizontal = 8.dp, vertical = 6.dp)) {
            // 头部：工具名 + 状态 + 展开按钮
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable(enabled = hasDetail) { expanded = !expanded },
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Text("⚙", style = MaterialTheme.typography.labelSmall)
                    Text(
                        step.tool,
                        style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.SemiBold),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (step.durationMs != null) {
                        Text(
                            "${step.durationMs}ms",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                // 状态标识
                Text(
                    when (step.state) {
                        "done", "completed" -> "✓"
                        "running" -> "⟳"
                        "error" -> "✗"
                        else -> step.state
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = when (step.state) {
                        "done", "completed" -> MaterialTheme.colorScheme.primary
                        "error" -> MaterialTheme.colorScheme.error
                        else -> MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }
            // 参数摘要（始终可见，单行）
            if (step.args.isNotBlank()) {
                Text(
                    step.args.lines().firstOrNull()?.take(80) ?: "",
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
            // 折叠区域：执行结果（code block 风格，横向可滚动）
            if (expanded && hasDetail) {
                HorizontalDivider(
                    modifier = Modifier.padding(vertical = 4.dp),
                    color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f),
                )
                val detail = step.resultDetail ?: step.resultPreview ?: ""
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(
                            MaterialTheme.colorScheme.surface.copy(alpha = 0.6f),
                            RoundedCornerShape(4.dp),
                        )
                        .border(
                            width = 1.dp,
                            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f),
                            shape = RoundedCornerShape(4.dp),
                        )
                        .horizontalScroll(rememberScrollState())
                        .padding(8.dp),
                ) {
                    Text(
                        detail,
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        softWrap = false,
                    )
                }
            }
        }
    }
}

@Composable
fun SourceBadge(source: String?) {
    if (source.isNullOrBlank()) return
    val label = when (source) {
        "web" -> "Web"
        "lark" -> "飞书"
        "repl" -> "REPL"
        "heartbeat" -> "心跳"
        else -> source
    }
    Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
}
