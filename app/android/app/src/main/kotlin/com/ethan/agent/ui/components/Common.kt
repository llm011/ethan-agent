package com.ethan.agent.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width

import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.ExpandMore
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
import androidx.compose.material3.TextButton
import androidx.compose.foundation.layout.heightIn
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
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
 * 通用可横滑 Tab 栏（下划线指示器风格）：
 * - 单行不换行，文字超长省略
 * - 超出屏宽时可手势横向滚动
 * - 选中项有底部圆角指示条
 * - 支持可选副标题（双行模式）
 */
@Composable
fun <T> EthanScrollableTabBar(
    tabs: List<T>,
    selectedTab: T,
    onTabSelected: (T) -> Unit,
    labelOf: (T) -> String,
    modifier: Modifier = Modifier,
    subtitleOf: ((T) -> String)? = null,
    horizontalPadding: androidx.compose.ui.unit.Dp = 12.dp,
) {
    val scrollState = rememberScrollState()
    Row(
        modifier = modifier
            .fillMaxWidth()
            .horizontalScroll(scrollState)
            .padding(horizontal = horizontalPadding),
        horizontalArrangement = Arrangement.spacedBy(0.dp),
    ) {
        tabs.forEach { tab ->
            val selected = tab == selectedTab
            val hasSubtitle = subtitleOf != null
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier
                    .clickable(
                        indication = null,
                        interactionSource = remember { MutableInteractionSource() },
                    ) { onTabSelected(tab) }
                    .padding(
                        horizontal = if (hasSubtitle) 16.dp else 12.dp,
                        vertical = if (hasSubtitle) 10.dp else 8.dp,
                    ),
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
                if (hasSubtitle) {
                    Text(
                        text = subtitleOf!!(tab),
                        style = MaterialTheme.typography.labelSmall,
                        color = if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.8f)
                            else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Spacer(Modifier.height(6.dp))
                } else {
                    Spacer(Modifier.height(4.dp))
                }
                Surface(
                    modifier = Modifier.size(
                        width = if (hasSubtitle) 32.dp else 24.dp,
                        height = 3.dp,
                    ),
                    shape = RoundedCornerShape(2.dp),
                    color = if (selected) MaterialTheme.colorScheme.primary else Color.Transparent,
                ) {}
            }
        }
    }
}

@Composable
fun ToolTimeline(steps: List<ToolStep>, modifier: Modifier = Modifier) {
    if (steps.isEmpty()) return

    var expanded by remember { mutableStateOf(true) }
    val totalDuration = steps.mapNotNull { it.durationMs }.sum()
    val hasAnyError = steps.any { it.state == "error" }
    val allDone = steps.all { it.state == "done" || it.state == "completed" || it.state == "error" }

    // 整体带边框的日志卡片
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f)),
    ) {
        Column(modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp)) {
            // 顶部汇总标题栏（可折叠整个块）
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { expanded = !expanded },
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    if (expanded) "▼" else "▶",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    if (allDone) {
                        if (hasAnyError) "执行完成（有错误）" else "正在执行自动化操作"
                    } else {
                        "正在执行自动化操作"
                    },
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
                )
                Text(
                    "[${steps.size}步]",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (totalDuration > 0) {
                    Text(
                        "[耗时 ${"%.1f".format(totalDuration / 1000.0)}s]",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.weight(1f))
                if (!allDone) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(14.dp),
                        strokeWidth = 2.dp,
                    )
                }
            }

            if (expanded) {
                Spacer(Modifier.height(4.dp))
                Column(verticalArrangement = Arrangement.spacedBy(1.dp)) {
                    steps.forEach { step ->
                        ToolStepRow(step, indent = 0)
                    }
                }
            }
        }
    }
}

@Composable
private fun ToolStepRow(step: ToolStep, indent: Int) {
    val isDone = step.state == "done" || step.state == "completed"
    val isError = step.state == "error"
    val isRunning = step.state == "running"
    val statusColor = when {
        isError -> Color(0xFFE53935)
        isDone -> Color(0xFF43A047)
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    val statusMark = when {
        isDone -> "✓"
        isError -> "✗"
        isRunning -> "⟳"
        else -> "○"
    }
    val hasSubSteps = !step.subSteps.isNullOrEmpty()
    var subExpanded by remember { mutableStateOf(true) }

    Column(modifier = Modifier.fillMaxWidth()) {
        // 步骤主行：[✓ tool_name] 耗时 ✓
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = (indent * 12).dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // 子步骤折叠标记（仅当有subSteps时显示）
            if (hasSubSteps) {
                Text(
                    if (subExpanded) "▼" else "▶",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .clickable { subExpanded = !subExpanded }
                        .padding(end = 2.dp),
                )
            }

            // [✓ tool_name] 状态标记 + 工具名
            Text(
                "[$statusMark ${step.tool}]",
                style = MaterialTheme.typography.bodySmall.copy(
                    fontFamily = FontFamily.Monospace,
                ),
                color = statusColor,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f, fill = false),
            )

            Spacer(Modifier.weight(1f))

            // 耗时
            if (step.durationMs != null) {
                Text(
                    "${step.durationMs}ms",
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                )
            }
            Spacer(Modifier.width(4.dp))
            // 右侧状态图标
            Text(
                statusMark,
                style = MaterialTheme.typography.bodySmall,
                color = statusColor,
                fontWeight = FontWeight.Bold,
            )
        }

        // 参数摘要（args第一行，缩进显示）
        val argsLine = step.args.lines().firstOrNull { it.isNotBlank() }
        if (!argsLine.isNullOrBlank()) {
            Text(
                argsLine,
                style = MaterialTheme.typography.bodySmall.copy(
                    fontFamily = FontFamily.Monospace,
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.75f),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = (indent * 12 + 16).dp),
            )
        }

        // intent 描述（如果有且不是和args重复）
        step.intent?.takeIf { it.isNotBlank() && it != step.args }?.let { intentText ->
            Text(
                intentText,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = (indent * 12 + 16).dp),
            )
        }

        // 子步骤（递归渲染，缩进+前缀>）
        if (hasSubSteps && subExpanded) {
            step.subSteps!!.forEach { sub ->
                SubToolStepRow(sub, indent = indent + 1)
            }
        }
    }
}

@Composable
private fun SubToolStepRow(sub: com.ethan.agent.core.model.SubToolStep, indent: Int) {
    val isDone = sub.state == "done" || sub.state == "completed"
    val isError = sub.state == "error"
    val statusColor = when {
        isError -> Color(0xFFE53935)
        isDone -> Color(0xFF43A047)
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    val statusMark = when {
        isDone -> "✓"
        isError -> "✗"
        else -> "○"
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = (indent * 12).dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // > 前缀表示子步骤
        Text(
            ">",
            style = MaterialTheme.typography.bodySmall,
            fontFamily = FontFamily.Monospace,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
        )
        Spacer(Modifier.width(4.dp))
        Text(
            sub.tool,
            style = MaterialTheme.typography.bodySmall.copy(
                fontFamily = FontFamily.Monospace,
            ),
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.85f),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f, fill = false),
        )
        if (sub.durationMs != null) {
            Spacer(Modifier.width(8.dp))
            Text(
                "${sub.durationMs}ms",
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
            )
        }
        Spacer(Modifier.weight(1f))
        Text(
            statusMark,
            style = MaterialTheme.typography.bodySmall,
            color = statusColor,
            fontWeight = FontWeight.Bold,
        )
    }

    // 子步骤参数
    val subArgsLine = sub.args.lines().firstOrNull { it.isNotBlank() }
    if (!subArgsLine.isNullOrBlank()) {
        Text(
            "action=$subArgsLine".takeIf { subArgsLine.startsWith("action=") } ?: subArgsLine,
            style = MaterialTheme.typography.bodySmall.copy(
                fontFamily = FontFamily.Monospace,
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.65f),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = (indent * 12 + 16).dp),
        )
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

@Composable
fun EthanPrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Surface(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = 40.dp),
        shape = RoundedCornerShape(24.dp),
        color = MaterialTheme.colorScheme.primary,
        contentColor = MaterialTheme.colorScheme.onPrimary,
    ) {
        Box(
            modifier = Modifier.padding(horizontal = 20.dp, vertical = 10.dp),
            contentAlignment = androidx.compose.ui.Alignment.Center,
        ) {
            Text(
                text = text,
                style = MaterialTheme.typography.labelLarge.copy(fontWeight = FontWeight.Medium),
            )
        }
    }
}

@Composable
fun EthanSecondaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Surface(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = 40.dp),
        shape = RoundedCornerShape(24.dp),
        color = Color.Transparent,
        contentColor = MaterialTheme.colorScheme.primary,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.primary.copy(alpha = 0.6f)),
    ) {
        Box(
            modifier = Modifier.padding(horizontal = 20.dp, vertical = 10.dp),
            contentAlignment = androidx.compose.ui.Alignment.Center,
        ) {
            Text(
                text = text,
                style = MaterialTheme.typography.labelLarge.copy(fontWeight = FontWeight.Medium),
            )
        }
    }
}
