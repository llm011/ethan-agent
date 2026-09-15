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
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width

import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.animation.animateContentSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
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
 *
 * 采用 Gmail 的 edge-to-edge 做法（见 PRD 1.2 C）：
 * - 背景色**铺到状态栏底下**（顶栏是一条通栏色带，不是浮在内容上方的小条）
 * - 内容靠 `statusBarsPadding()` 下移到状态栏之下 —— 注意这让开的是**内容**，
 *   不是顶栏本身；顶栏容器仍然覆盖状态栏区域，所以不会出现「独立色带」。
 * - 行高 52dp（比 M3 默认 64dp 紧凑，但仍 ≥48dp 触控标准）
 *
 * 底色用 `surface`（与页面内容同色，切主题时自动跟随），
 * 不额外加分隔线 —— 靠色阶与留白区分，避免满屏发丝线。
 */
@Composable
fun EthanTopBar(
    title: String,
    subtitle: String? = null,
    onBack: (() -> Unit)? = null,
    actions: @Composable RowScope.() -> Unit = {},
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .statusBarsPadding()
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
}

/**
 * 通用可横滑 Tab 栏（下划线指示器风格）：
 * - 单行不换行，文字超长省略
 * - 超出屏宽时可手势横向滚动
 * - 选中项有底部圆角指示条
 * - 支持可选副标题（双行模式）
 * - 可选「双击 tab」回调（见 [onTabDoubleTap]）
 *
 * @param onTabDoubleTap 双击某个 tab 时触发（记忆页用它回到列表顶部）。
 *   为 null 时**完全走原来的 clickable** —— 不会引入双击等待的 ~300ms 延迟，
 *   所以 Schedule/Settings 这些不传的调用方行为零变化。
 *   传入后单击切换要等双击窗口过去才生效（与 Web 端的 300ms 口径一致）。
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
    /** 右侧常驻操作（如「事实」tab 收起搜索框后露出的放大镜）。tab 多时会被挤出去滚走。 */
    action: (@Composable () -> Unit)? = null,
    onTabDoubleTap: ((T) -> Unit)? = null,
) {
    val scrollState = rememberScrollState()
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(
            modifier = Modifier
                .weight(1f)
                .horizontalScroll(scrollState)
                .padding(horizontal = horizontalPadding),
            horizontalArrangement = Arrangement.spacedBy(0.dp),
        ) {
            tabs.forEach { tab ->
                val selected = tab == selectedTab
                val hasSubtitle = subtitleOf != null
                // 只有需要双击语义时才走 detectTapGestures：它会为了等第二次点击
                // 把单击推迟 ~300ms，不能强加给不需要的页面（Schedule/Settings）。
                val tapModifier = if (onTabDoubleTap != null) {
                    Modifier.pointerInput(tab) {
                        detectTapGestures(
                            onTap = { onTabSelected(tab) },
                            // 双击：先切过去再回顶，避免「单击切换 + 双击切换两次」
                            onDoubleTap = {
                                onTabSelected(tab)
                                onTabDoubleTap(tab)
                            },
                        )
                    }
                } else {
                    Modifier.clickable(
                        indication = null,
                        interactionSource = remember { MutableInteractionSource() },
                    ) { onTabSelected(tab) }
                }
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    modifier = tapModifier
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
        action?.invoke()
    }
}

@Composable
fun ToolTimeline(steps: List<ToolStep>, modifier: Modifier = Modifier, isStreaming: Boolean = false) {
    if (steps.isEmpty()) return

    // 防御：非 streaming 消息中残留的 running/start 步骤视为 cancelled
    // （中止/断流时后端已尽量标记，这里兜底避免 spinner 永久残留）
    val effectiveSteps = if (isStreaming) {
        steps
    } else {
        remember(steps) { steps.map { it.asTerminal() } }
    }

    val totalDuration = effectiveSteps.mapNotNull { it.durationMs }.sum()
    val hasAnyError = effectiveSteps.any { it.state == "error" }
    val hasAnyCancelled = effectiveSteps.any { it.state == "cancelled" }
    val allDone = effectiveSteps.all { it.state != "running" && it.state != "start" }

    // 默认展开，**执行过程中不再自动折叠**。
    //
    // 早前是 `expanded = userToggled ?: !allDone`：多轮工具执行时 allDone 会随
    // 「call1 done → 模型生成 → call2 start」反复翻转（true→false→true…），
    // 用户没手动点过时整张卡片就跟着折叠/展开来回跳，整个屏幕都在闪。
    // 现在只有用户点击摘要行才会改变 expanded —— 状态不再被流式事件驱动。
    var expanded by remember { mutableStateOf(true) }

    // 整体带边框的日志卡片
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.small,
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
                        when {
                            hasAnyError -> "执行完成（有错误）"
                            hasAnyCancelled -> "已中止（部分步骤取消）"
                            else -> "执行完成"
                        }
                    } else {
                        "正在执行自动化操作"
                    },
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
                )
                Text(
                    "[${effectiveSteps.size}步]",
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

            // animateContentSize：折叠/展开只跟约束走，不碰 LazyColumn 的滚动位置
            // （与 ChatScreen 的长消息折叠同一做法）。折叠是用户手动触发的偶发操作，
            // 不需要动画期间的高度突变感。
            Column(modifier = Modifier.animateContentSize()) {
                if (expanded) {
                    Spacer(Modifier.height(4.dp))
                    Column(verticalArrangement = Arrangement.spacedBy(1.dp)) {
                        // key 用 tool_call_id（唯一）：每个 SSE 事件都会用 .toList() 重建
                        // 一个新 List，没有 key 时 slot 身份漂移会让 ToolStepRow 里
                        // remember 的 subExpanded 被重置，展开中的子步骤会被弹回去。
                        effectiveSteps.forEachIndexed { index, step ->
                            key(step.id ?: "step-$index") {
                                ToolStepRow(step, indent = 0)
                            }
                        }
                    }
                }
            }
        }
    }
}

/** 非终态（running/start）视为 cancelled：用于非 streaming 消息的防御性渲染。 */
private fun ToolStep.asTerminal(): ToolStep {
    val newState = if (state == "running" || state == "start") "cancelled" else state
    val newSubs = subSteps?.map { sub ->
        if (sub.state == "running" || sub.state == "start") sub.copy(state = "cancelled") else sub
    }
    return if (newState != state || newSubs !== subSteps) copy(state = newState, subSteps = newSubs) else this
}

/** 对齐 web formatDuration：<1000ms 显示 "Nms"，否则显示一位小数秒（如 1.2s）。 */
private fun formatMs(ms: Long): String =
    if (ms < 1000) "${ms}ms" else String.format("%.1fs", ms / 1000.0)

@Composable
private fun ToolStepRow(step: ToolStep, indent: Int) {
    val isDone = step.state == "done" || step.state == "completed"
    val isError = step.state == "error"
    val isCancelled = step.state == "cancelled"
    val isRunning = step.state == "running"
    val statusColor = when {
        isError -> StatusError
        isDone -> StatusSuccess
        isCancelled -> MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f)
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    val statusMark = when {
        isDone -> "✓"
        isError -> "✗"
        isRunning -> "⟳"
        isCancelled -> "⊘"
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

            // 双耗时：✨模型生成耗时（start 即有，running 态也显示）+ 🕐工具执行耗时（done 后显示）
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
                val genMs = step.genMs
                if (genMs != null) {
                    Text(
                        "✨${formatMs(genMs)}",
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                    )
                }
                val durationMs = step.durationMs
                if (durationMs != null) {
                    Text(
                        "🕐${formatMs(durationMs)}",
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                    )
                }
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

        // 结果预览（对齐 Web tool-timeline.tsx 与 iOS _ToolTimeline 的 result_preview）。
        // 只在步骤跑完后显示：运行中后端给的就是空串（stream_collector 在 start 时
        // 把 result_preview 置为 ""），此时硬渲染也没内容。补上这一行后，
        // 「运行中一行 / 跑完突然一堆」的信息落差就没了——每一步结束即出结果。
        // 与 Web 一致：只有 running 态不显示（`start` 是 Android 侧的前置态，等同 running）
        step.resultPreview?.takeIf { it.isNotBlank() && !isRunning && step.state != "start" }?.let { preview ->
            Text(
                preview,
                style = MaterialTheme.typography.bodySmall.copy(
                    fontFamily = FontFamily.Monospace,
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                softWrap = true,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = (indent * 12 + 16).dp),
            )
        }

        // 子步骤（递归渲染，缩进+前缀>）
        if (hasSubSteps && subExpanded) {
            step.subSteps!!.forEachIndexed { subIndex, sub ->
                // SubToolStep 没有 id 字段，用 tool + 序号做 key
                key("${sub.tool}-$subIndex") {
                    SubToolStepRow(sub, indent = indent + 1)
                }
            }
        }
    }
}

@Composable
private fun SubToolStepRow(sub: com.ethan.agent.core.model.SubToolStep, indent: Int) {
    val isDone = sub.state == "done" || sub.state == "completed"
    val isError = sub.state == "error"
    val isCancelled = sub.state == "cancelled"
    val statusColor = when {
        isError -> StatusError
        isDone -> StatusSuccess
        isCancelled -> MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f)
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    val statusMark = when {
        isDone -> "✓"
        isError -> "✗"
        isCancelled -> "⊘"
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
            subArgsLine,
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

    // 子步骤结果预览（与主步骤同一口径，对齐 Web tool-timeline.tsx:581-585）
    val subRunning = sub.state == "running" || sub.state == "start"
    sub.resultPreview?.takeIf { it.isNotBlank() && !subRunning }?.let { preview ->
        Text(
            preview,
            style = MaterialTheme.typography.bodySmall.copy(
                fontFamily = FontFamily.Monospace,
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.55f),
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            softWrap = true,
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

/**
 * 主按钮。
 *
 * 用真正的 M3 [Button]（而不是 Surface + Box 手搓）—— 这样才有涟漪、state layer、
 * disabled 语义和正确的无障碍角色。只覆盖尺寸与圆角。
 */
@Composable
fun EthanPrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Button(
        onClick = onClick,
        modifier = modifier.heightIn(min = 40.dp),
        enabled = enabled,
        shape = MaterialTheme.shapes.large,
    ) {
        Text(text, style = MaterialTheme.typography.labelLarge)
    }
}

/** 次按钮：M3 [OutlinedButton]，描边用 outline（而非主色淡化），避免满屏彩色线条。 */
@Composable
fun EthanSecondaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    OutlinedButton(
        onClick = onClick,
        modifier = modifier.heightIn(min = 40.dp),
        enabled = enabled,
        shape = MaterialTheme.shapes.large,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
    ) {
        Text(text, style = MaterialTheme.typography.labelLarge)
    }
}
