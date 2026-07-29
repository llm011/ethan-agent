package com.ethan.agent.ui.components

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
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
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
    onBack: (() -> Unit)? = null,
    actions: @Composable RowScope.() -> Unit = {},
) {
    Surface(
        modifier = Modifier.fillMaxWidth().statusBarsPadding(),
        color = MaterialTheme.colorScheme.surface,
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp)
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
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.SemiBold),
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.align(Alignment.Center),
            )
            // 右侧操作按钮
            Row(
                modifier = Modifier.align(Alignment.CenterEnd),
                content = actions,
            )
        }
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
    Column(modifier = modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        steps.forEach { step ->
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                ),
            ) {
                Column(Modifier.padding(8.dp)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(step.tool, style = MaterialTheme.typography.labelLarge)
                        Text(step.state, style = MaterialTheme.typography.labelSmall)
                    }
                    if (step.args.isNotBlank()) {
                        Text(
                            step.args,
                            style = MaterialTheme.typography.bodySmall,
                            fontFamily = FontFamily.Monospace,
                            modifier = Modifier.padding(top = 4.dp),
                        )
                    }
                    step.resultPreview?.let {
                        Text(it, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp))
                    }
                    step.durationMs?.let {
                        Text("${it}ms", style = MaterialTheme.typography.labelSmall)
                    }
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
