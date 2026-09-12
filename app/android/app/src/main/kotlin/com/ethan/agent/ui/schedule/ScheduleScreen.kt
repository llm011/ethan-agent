package com.ethan.agent.ui.schedule

import com.ethan.agent.shared.viewmodel.ScheduleUiState
import com.ethan.agent.shared.viewmodel.ScheduleTab
import com.ethan.agent.shared.viewmodel.TimelineItem
import com.ethan.agent.shared.viewmodel.CreateScheduleForm
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.ChatBubbleOutline
import androidx.compose.material.icons.filled.PauseCircleOutline
import androidx.compose.material.icons.filled.PlayCircleOutline
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.automirrored.filled.ViewList
import androidx.compose.material.icons.filled.ViewTimeline
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.ScheduleFormat
import com.ethan.agent.core.model.ScheduleJob
import com.ethan.agent.ui.components.EthanCard
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.EthanScrollableTabBar
import com.ethan.agent.ui.components.EthanTopBar
import com.ethan.agent.ui.components.EthanScaffold
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer

/**
 * 任务视图布局：时间轴 / 列表 —— 对应 Web 的 `viewLayout`。
 *
 * 用图标而非文字：一是省横向空间（360dp 上文字版会与场景 Tab 撞车），
 * 二是和旁边的「今天/全部」文字切换拉开形状差异，不会连读成「四选一」。
 */
private enum class JobLayout(val label: String, val icon: ImageVector) {
    Timeline("时间轴视图", Icons.Default.ViewTimeline),
    List("列表视图", Icons.AutoMirrored.Filled.ViewList),
}

/** 时间范围：今天（含明天）/ 全部 —— 对应 Web 的 `viewMode`。 */
private enum class JobRange(val label: String) {
    Today("今天"),
    All("全部"),
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScheduleScreen(
    state: ScheduleUiState,
    onBack: () -> Unit = {},
    onToggle: (ScheduleJob) -> Unit,
    onDelete: (String) -> Unit,
    onTrigger: (ScheduleJob) -> Unit,
    onOpenSession: (String) -> Unit,
    onTabChange: (ScheduleTab) -> Unit,
    onSyncTimelines: () -> Unit,
    onTimelineAction: (String, String) -> Unit,
    onShowCreateSheet: () -> Unit,
    onDismissCreateSheet: () -> Unit,
    onUpdateForm: (CreateScheduleForm) -> Unit,
    onSubmitCreate: () -> Unit,
    onClearError: () -> Unit,
    onClearTriggerSuccess: () -> Unit,
    onRefresh: () -> Unit = {},
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    // 布局/范围/场景筛选是纯展示态，放本地即可（与 Web 一致：不进后端）
    var layout by remember { mutableStateOf(JobLayout.Timeline) }
    var range by remember { mutableStateOf(JobRange.Today) }
    var activeScene by remember { mutableStateOf<String?>(null) }
    // 删除是破坏性操作且图标与其它按钮紧邻，极易误触 —— 统一在此拦截确认
    var pendingDelete by remember { mutableStateOf<ScheduleJob?>(null) }

    val triggerSuccess = state.triggerSuccess
    LaunchedEffect(triggerSuccess) {
        if (triggerSuccess == null) return@LaunchedEffect
        val result = snackbar.showSnackbar(
            message = "已触发，跳转到关联会话查看",
            actionLabel = if (triggerSuccess.sessionId.isNotBlank()) "查看" else null,
        )
        if (result == SnackbarResult.ActionPerformed && triggerSuccess.sessionId.isNotBlank()) {
            onOpenSession(triggerSuccess.sessionId)
        }
        onClearTriggerSuccess()
    }

    EthanScaffold(
        topBar = {
            // 顶栏只留「返回 + 标题 + 刷新」——两组切换放到下方筛选行，
            // 否则在 360dp 宽的手机上与居中标题重叠（实测标题被压住）。
            EthanTopBar(title = "定时任务", onBack = onBack) {
                IconButton(onClick = onRefresh, enabled = !state.isLoading) {
                    Icon(Icons.Default.Refresh, contentDescription = "刷新")
                }
            }
        },
        snackbarHost = { SnackbarContainer(snackbar) },
        floatingActionButton = {
            if (state.tab == ScheduleTab.Jobs) {
                FloatingActionButton(onClick = onShowCreateSheet) {
                    Icon(Icons.Default.Add, contentDescription = "创建任务")
                }
            }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            EthanScrollableTabBar(
                tabs = ScheduleTab.entries.toList(),
                selectedTab = state.tab,
                onTabSelected = onTabChange,
                labelOf = { it.title },
            )

            if (state.isLoading) {
                LoadingBox()
                return@Column
            }

            when (state.tab) {
                ScheduleTab.Jobs -> JobsContent(
                    jobs = state.jobs,
                    layout = layout,
                    range = range,
                    onLayoutSelect = { layout = it },
                    onRangeSelect = { range = it },
                    activeScene = activeScene,
                    onSceneSelected = { activeScene = it },
                    triggeringIds = state.triggeringIds,
                    onTrigger = onTrigger,
                    onToggle = onToggle,
                    onDelete = { id -> pendingDelete = state.jobs.firstOrNull { it.id == id } },
                    onOpenSession = onOpenSession,
                )
                ScheduleTab.Timelines -> TimelinesContent(
                    timelines = state.timelines,
                    isSyncing = state.isSyncingTimelines,
                    onSync = onSyncTimelines,
                    onAction = onTimelineAction,
                )
            }
        }

        pendingDelete?.let { job ->
            AlertDialog(
                onDismissRequest = { pendingDelete = null },
                title = { Text("删除定时任务") },
                text = {
                    Text("确定要删除「${job.name}」吗？此操作无法撤销。")
                },
                confirmButton = {
                    TextButton(onClick = {
                        onDelete(job.id)
                        pendingDelete = null
                    }) {
                        Text("删除", color = MaterialTheme.colorScheme.error)
                    }
                },
                dismissButton = {
                    TextButton(onClick = { pendingDelete = null }) { Text("取消") }
                },
            )
        }

        if (state.showCreateSheet) {
            CreateScheduleSheet(
                form = state.createForm,
                isCreating = state.isCreating,
                onDismiss = onDismissCreateSheet,
                onUpdate = onUpdateForm,
                onSubmit = onSubmitCreate,
            )
        }
    }
}

/**
 * 紧凑分段切换 —— 对齐 Web 的 `rounded-md border overflow-hidden` 双按钮组。
 *
 * 选中态用 `primaryContainer` 而不是实心 `primary`：整页只有一个实心主色块时
 * 视觉重心才不会跑到筛选器上（列表里的任务才是主角）。
 */
@Composable
private fun SegmentedToggle(
    options: List<String>,
    selectedIndex: Int,
    onSelect: (Int) -> Unit,
) {
    Row(
        Modifier
            .clip(MaterialTheme.shapes.small)
            .background(MaterialTheme.colorScheme.surfaceVariant),
    ) {
        options.forEachIndexed { index, label ->
            val selected = index == selectedIndex
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = if (selected) MaterialTheme.colorScheme.onPrimaryContainer
                else MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier
                    .clip(MaterialTheme.shapes.small)
                    .background(
                        if (selected) MaterialTheme.colorScheme.primaryContainer
                        else Color.Transparent
                    )
                    .clickableNoRipple { onSelect(index) }
                    .padding(horizontal = 10.dp, vertical = 5.dp),
            )
        }
    }
}

/**
 * 图标分段切换（视图布局用）。
 * 每个按钮 36dp 见方 —— 视觉紧凑，但整组是单一控件，不会误点到相邻项。
 */
@Composable
private fun IconSegmentedToggle(
    options: List<Pair<String, ImageVector>>,
    selectedIndex: Int,
    onSelect: (Int) -> Unit,
) {
    Row(
        Modifier
            .clip(MaterialTheme.shapes.small)
            .background(MaterialTheme.colorScheme.surfaceVariant),
    ) {
        options.forEachIndexed { index, (label, icon) ->
            val selected = index == selectedIndex
            Box(
                Modifier
                    .size(32.dp)
                    .clip(MaterialTheme.shapes.small)
                    .background(
                        if (selected) MaterialTheme.colorScheme.primaryContainer
                        else Color.Transparent
                    )
                    .clickableNoRipple { onSelect(index) },
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    icon,
                    contentDescription = label,
                    modifier = Modifier.size(17.dp),
                    tint = if (selected) MaterialTheme.colorScheme.onPrimaryContainer
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/** 点击但无水波纹（分段切换是紧凑控件，涟漪会溢出圆角）。 */
@Composable
private fun Modifier.clickableNoRipple(onClick: () -> Unit): Modifier = this.clickable(
    interactionSource = remember { MutableInteractionSource() },
    indication = null,
    onClick = onClick,
)

@Composable
private fun JobsContent(
    jobs: List<ScheduleJob>,
    layout: JobLayout,
    range: JobRange,
    onLayoutSelect: (JobLayout) -> Unit,
    onRangeSelect: (JobRange) -> Unit,
    activeScene: String?,
    onSceneSelected: (String?) -> Unit,
    triggeringIds: Set<String>,
    onTrigger: (ScheduleJob) -> Unit,
    onToggle: (ScheduleJob) -> Unit,
    onDelete: (String) -> Unit,
    onOpenSession: (String) -> Unit,
) {
    // 场景列表：来自数据本身（与 Web 一致，不硬编码），保持稳定顺序
    val scenes = remember(jobs) {
        jobs.map { it.scene.ifBlank { "work" } }.distinct().sorted()
    }
    val currentScene = activeScene ?: scenes.firstOrNull() ?: "work"

    val sceneJobs = remember(jobs, currentScene) {
        jobs.filter { it.scene.ifBlank { "work" } == currentScene }
    }

    // 「今天」= 今天和明天；无 next_run_time 的（待定）始终保留
    val visibleJobs = remember(sceneJobs, range) {
        if (range == JobRange.All) sceneJobs
        else sceneJobs.filter { job ->
            val key = ScheduleFormat.dateKeyOf(job.nextRunTime)
            key == null || key <= todayPlusDays(1)
        }
    }

    Column(Modifier.fillMaxSize()) {
        // 筛选区分两行（与 Web 一致：场景 Tab 一行，今天/全部 + 视图切换一行）：
        //
        // 之前尝试三项挤一行，在 360dp 上「工作 17」和「今天|全部」之间只剩几 dp，
        // 两组控件几乎贴在一起，读起来像一坨。分两行后每组各占一整行、左右两端
        // 对齐，虽然多占 32dp，但分组清晰、互不挤压。
        if (scenes.isNotEmpty()) {
            Row(
                Modifier.fillMaxWidth().padding(start = 6.dp, end = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                scenes.forEach { scene ->
                    val count = sceneJobs.count { it.scene.ifBlank { "work" } == scene }
                    SceneTab(
                        label = ScheduleFormat.sceneLabel(scene),
                        count = count,
                        selected = scene == currentScene,
                        onClick = { onSceneSelected(scene) },
                    )
                }
                Spacer(Modifier.weight(1f))
                // 场景只有一组时右半边会空出来 —— 顺手把「可见/总数」放这儿，避免死白。
                // 「全部」范围下两者相等，只显示一个数。
                Text(
                    text = if (visibleJobs.size == sceneJobs.size) "共 ${sceneJobs.size} 个"
                    else "今天 ${visibleJobs.size} / 共 ${sceneJobs.size}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                )
            }
        }

        Row(
            Modifier.fillMaxWidth().padding(start = 12.dp, end = 12.dp, top = 4.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            SegmentedToggle(
                options = JobRange.entries.map { it.label },
                selectedIndex = range.ordinal,
                onSelect = { onRangeSelect(JobRange.entries[it]) },
            )
            Spacer(Modifier.weight(1f))
            IconSegmentedToggle(
                options = JobLayout.entries.map { it.label to it.icon },
                selectedIndex = layout.ordinal,
                onSelect = { onLayoutSelect(JobLayout.entries[it]) },
            )
        }

        when {
            visibleJobs.isEmpty() -> EmptyScheduleText(
                if (range == JobRange.Today) "今天和明天暂无定时任务" else "暂无定时任务",
            )
            layout == JobLayout.Timeline -> TimelineLayout(
                jobs = visibleJobs,
                triggeringIds = triggeringIds,
                onTrigger = onTrigger,
                onToggle = onToggle,
                onDelete = onDelete,
                onOpenSession = onOpenSession,
            )
            else -> ListLayout(
                jobs = visibleJobs,
                triggeringIds = triggeringIds,
                onTrigger = onTrigger,
                onToggle = onToggle,
                onDelete = onDelete,
                onOpenSession = onOpenSession,
            )
        }
    }
}

/** `今天/明天` 的上界日期键；用于「今天」范围过滤。 */
private fun todayPlusDays(days: Long): String = ScheduleFormat.todayPlusDaysKey(days)

@Composable
private fun SceneTab(
    label: String,
    count: Int,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        modifier = Modifier
            .clip(MaterialTheme.shapes.small)
            .clickableNoRipple(onClick)
            .padding(horizontal = 10.dp, vertical = 8.dp),
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelLarge,
            color = if (selected) MaterialTheme.colorScheme.primary
            else MaterialTheme.colorScheme.onSurfaceVariant,
        )
        // 选中态用 primary 实心胶囊，未选中用中性 surfaceVariant（对齐 Web 的 Tab badge）
        val bg = if (selected) MaterialTheme.colorScheme.primary
        else MaterialTheme.colorScheme.surfaceVariant
        val fg = if (selected) MaterialTheme.colorScheme.onPrimary
        else MaterialTheme.colorScheme.onSurfaceVariant
        Text(
            text = count.toString(),
            style = MaterialTheme.typography.labelSmall,
            color = fg,
            modifier = Modifier
                .clip(CircleShape)
                .background(bg)
                .padding(horizontal = 6.dp, vertical = 1.dp),
        )
    }
}

@Composable
private fun EmptyScheduleText(text: String) {
    Box(Modifier.fillMaxSize().padding(top = 48.dp), contentAlignment = Alignment.TopCenter) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
    }
}

/** ── 时间轴布局：真实轴线 + 日期分组 + 时间标签 + 紧凑卡片 ────────── */
@Composable
private fun TimelineLayout(
    jobs: List<ScheduleJob>,
    triggeringIds: Set<String>,
    onTrigger: (ScheduleJob) -> Unit,
    onToggle: (ScheduleJob) -> Unit,
    onDelete: (String) -> Unit,
    onOpenSession: (String) -> Unit,
) {
    // 按日期分组（与 Web 的 groupJobsByDate 一致：无时间的归入「待定」）
    val groups = remember(jobs) {
        val withDate = jobs.filter { ScheduleFormat.dateKeyOf(it.nextRunTime) != null }
            .groupBy { ScheduleFormat.dateKeyOf(it.nextRunTime)!! }
            .toSortedMap()
            .map { (key, list) ->
                key to list.sortedBy { it.nextRunTime ?: "" }
            }
        val noDate = jobs.filter { ScheduleFormat.dateKeyOf(it.nextRunTime) == null }
        if (noDate.isEmpty()) withDate else withDate + ("" to noDate)
    }

    val todayKey = remember { ScheduleFormat.todayPlusDaysKey(0) }

    LazyColumn(
        Modifier.fillMaxSize(),
        // 底部同样留 96dp 给 FAB 让位（时间轴最后一行的时间点不要被 FAB 压住）
        contentPadding = PaddingValues(start = 12.dp, end = 12.dp, bottom = 96.dp),
    ) {
        item(key = "head") { Spacer(Modifier.height(10.dp)) }

        groups.forEachIndexed { groupIndex, (dateKey, groupJobs) ->
            item(key = "date_$dateKey") {
                // 日期标题左缩进 = 轴线位置（GUTTER - 61dp），这样标题、轴线、时间标签
                // 三者的左缘落在同一列上，形成一条干净的竖向基线。
                // 之前标题顶到屏幕最左（x≈12dp）而卡片在 x≈70dp，左边参差。
                Row(
                    Modifier.padding(
                        start = TIMELINE_GUTTER,
                        top = if (groupIndex == 0) 2.dp else 18.dp,
                        bottom = 6.dp,
                    ),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    if (dateKey.isNotBlank()) {
                        val parts = dateKey.split("-")
                        val month = parts.getOrNull(1)?.toIntOrNull() ?: 0
                        val day = parts.getOrNull(2)?.toIntOrNull() ?: 0
                        Text(
                            text = "${month}月${day}日",
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        // 「今天」徽章会让人误以为是可切换的胶囊按钮（旁边正好有
                        // 「今天/全部」切换），改成中性灰文字，纯标注、不可点。
                        if (dateKey == todayKey) {
                            Text(
                                text = "· 今天",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    } else {
                        Text(
                            text = "待定",
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            itemsIndexed(groupJobs, key = { _, it -> "job_${it.id}" }) { index, job ->
                TimelineRow(
                    job = job,
                    triggering = job.id in triggeringIds,
                    isFirst = index == 0,
                    isLast = index == groupJobs.lastIndex,
                    onTrigger = { onTrigger(job) },
                    onToggle = { onToggle(job) },
                    onDelete = { onDelete(job.id) },
                    onOpenSession = { onOpenSession(job.sessionId) },
                )
            }
        }
    }
}

/**
 * 时间轴左侧栏宽度 = 轴线列(16dp) + 时间标签(46dp) + 间距(8dp)。
 * 日期标题、轴线、卡片三者的左缘都从这里推导，保证全页一条竖线对齐。
 *
 * 注意：轴线画在**第 8dp** 处，所以日期标题也要用同样的左缩进，
 * 否则标题会顶到屏幕最左边（x≈12dp），与卡片（x≈70dp）参差，整页看着没对齐。
 */
private val TIMELINE_GUTTER = 70.dp

/**
 * 时间轴一行：轴线 + 圆点 + 时间标签 + 卡片。
 *
 * 轴线**用两条**（上/下）拼出「不过头、不断尾」的效果：第一行不画上半段、
 * 最后一行不画下半段，中间行上下贯通。之前是整列画满，结果轴线从屏幕顶
 * 一直垂到屏幕底，下方没有任务时看着像根断掉的电线。
 */
@Composable
private fun TimelineRow(
    job: ScheduleJob,
    triggering: Boolean,
    isFirst: Boolean,
    isLast: Boolean,
    onTrigger: () -> Unit,
    onToggle: () -> Unit,
    onDelete: () -> Unit,
    onOpenSession: () -> Unit,
) {
    val active = job.status == "active"
    // 圆点的垂直位置：卡片首行标题（titleSmall，行高约 20sp）的视觉中心。
    // 用固定值而非测量，是为了让轴线、圆点、时间标签三者共用同一条水平带。
    val dotCenterY = 26.dp
    val dotSize = 8.dp
    // 轴线画在 16dp 轴列的中心（8dp），圆点同轴心
    val axisX = 8.dp

    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
        Box(Modifier.width(TIMELINE_GUTTER)) {
            // 从行顶到圆点之前的短竖线：第一行不画（时间轴上端不悬空）。
            if (!isFirst) {
                Box(
                    Modifier
                        .padding(start = axisX - 0.5.dp)
                        .width(1.dp)
                        .height(dotCenterY - dotSize / 2)
                        .background(MaterialTheme.colorScheme.outlineVariant),
                )
            }
            // 圆点：压在两段轴线之间，形成「节点」而不是「线上一个色块」
            Box(
                Modifier
                    .padding(start = axisX - dotSize / 2, top = dotCenterY - dotSize / 2)
                    .size(dotSize)
                    .clip(CircleShape)
                    .background(
                        if (active) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.outlineVariant
                    ),
            )
            // 圆点之后到行底：最后一行不画（时间轴下端不拖尾）
            if (!isLast) {
                Box(
                    Modifier
                        .padding(start = axisX - 0.5.dp, top = dotCenterY + dotSize / 2)
                        .width(1.dp)
                        .fillMaxHeight()
                        .background(MaterialTheme.colorScheme.outlineVariant),
                )
            }
        }

        // 时间标签：与卡片首行同一水平带
        Text(
            text = ScheduleFormat.timeLabelOf(job.nextRunTime),
            style = MaterialTheme.typography.labelMedium,
            color = if (active) MaterialTheme.colorScheme.onSurface
            else MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            modifier = Modifier
                .width(46.dp)
                .padding(top = 20.dp),
        )

        Spacer(Modifier.width(8.dp))

        JobRowCard(
            job = job,
            triggering = triggering,
            onTrigger = onTrigger,
            onToggle = onToggle,
            onDelete = onDelete,
            onOpenSession = onOpenSession,
            modifier = Modifier.weight(1f).padding(bottom = 8.dp),
        )
    }
}

/** ── 列表布局：一列宽卡片，信息比时间轴更完整 ─────────────────────── */
@Composable
private fun ListLayout(
    jobs: List<ScheduleJob>,
    triggeringIds: Set<String>,
    onTrigger: (ScheduleJob) -> Unit,
    onToggle: (ScheduleJob) -> Unit,
    onDelete: (String) -> Unit,
    onOpenSession: (String) -> Unit,
) {
    LazyColumn(
        Modifier.fillMaxSize(),
        // bottom = 96dp：FAB 默认贴在右下角（距底 16dp、直径 56dp），卡片右侧的
        // 删除按钮正好在同一竖线上 —— 只留 88dp 时最后一张卡片的删除键会被 FAB
        // 压住（实测截图里叠在一起）。96dp 让列表滚到底时最后一行能整个抬到 FAB 之上。
        contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 8.dp, bottom = 96.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(jobs, key = { it.id }) { job ->
            JobRowCard(
                job = job,
                triggering = job.id in triggeringIds,
                onTrigger = { onTrigger(job) },
                onToggle = { onToggle(job) },
                onDelete = { onDelete(job.id) },
                onOpenSession = { onOpenSession(job.sessionId) },
                showPrompt = true,
            )
        }
    }
}

/**
 * 单个任务卡片 —— 信息分层对齐 Web：
 * 第一行 名称 + 状态徽章；第二行 下次执行；第三行 触发规则；第四行 提示词；底部 操作图标。
 */
@Composable
private fun JobRowCard(
    job: ScheduleJob,
    triggering: Boolean,
    onTrigger: () -> Unit,
    onToggle: () -> Unit,
    onDelete: () -> Unit,
    onOpenSession: () -> Unit,
    modifier: Modifier = Modifier,
    showPrompt: Boolean = false,
) {
    val active = job.status == "active"

    EthanCard(modifier = modifier) {
        Column(Modifier.padding(start = 14.dp, end = 4.dp, top = 12.dp, bottom = 2.dp)) {
            // 名称 + 状态徽章
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.padding(end = 10.dp),
            ) {
                Text(
                    text = job.name,
                    style = MaterialTheme.typography.titleSmall,
                    color = if (active) MaterialTheme.colorScheme.onSurface
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                // 徽章始终显示（含「运行中」）：状态要能一眼扫出来，不能靠「没有徽章」
                // 反推。时间线 Tab 的卡片也是这么做的，两处保持一致。
                StatusBadge(active = active)
            }

            Spacer(Modifier.height(4.dp))

            // 元信息分两行，而不是挤成一行：
            //   「9 小时 45 分钟后（09:00）」+「每天 09:00、21:00」拼在一起在 360dp 上
            //   必然截断（实测截成「每天 09:00、2…」），而这两个信息都不能省。
            // 分两行后每段各自独占一行，完整可读，总共也只多 16dp。
            // 暂停的任务没有 next_run_time，`formatNextRun` 会返回「已暂停」，
            // 与状态徽章语义重复 —— 那种情况只显示触发规则。
            if (active) {
                Text(
                    text = ScheduleFormat.formatNextRun(job.nextRunTime, ScheduleFormat.nowEpochSeconds()),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(end = 10.dp).fillMaxWidth(),
                )
                Spacer(Modifier.height(2.dp))
            }
            Text(
                text = ScheduleFormat.formatTrigger(job.trigger),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.85f),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(end = 10.dp).fillMaxWidth(),
            )

            if (showPrompt && job.prompt.isNotBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(
                    text = job.prompt,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.8f),
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(end = 10.dp).fillMaxWidth(),
                )
            }

            // 操作行：图标常驻（Android 无 hover，不能照搬 Web 的 group-hover）。
            // 常规操作靠左、删除用竖线隔开放在最右 —— 手指横扫时不会误触删除。
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (job.sessionId.isNotBlank()) {
                    RowAction(Icons.Default.ChatBubbleOutline, "查看对话", onOpenSession)
                }
                RowAction(
                    icon = Icons.Default.Bolt,
                    label = "立即触发",
                    onClick = onTrigger,
                    enabled = !triggering,
                    busy = triggering,
                )
                RowAction(
                    icon = if (active) Icons.Default.PauseCircleOutline else Icons.Default.PlayCircleOutline,
                    label = if (active) "暂停" else "恢复",
                    onClick = onToggle,
                )
                Spacer(Modifier.weight(1f))
                Box(
                    Modifier
                        .padding(vertical = 10.dp)
                        .width(1.dp)
                        .height(18.dp)
                        .background(MaterialTheme.colorScheme.outlineVariant),
                )
                RowAction(
                    icon = Icons.Outlined.DeleteOutline,
                    label = "删除",
                    onClick = onDelete,
                    tint = MaterialTheme.colorScheme.error,
                )
            }
        }
    }
}

/**
 * 卡片底部的图标操作。
 *
 * 点击区 40×40，图标 18dp —— 手机上横向密排三个也不会互相吃到手指，
 * 又比 `IconButton` 默认的 48dp 省下 24dp 横向空间（够多放一个操作）。
 */
@Composable
private fun RowAction(
    icon: ImageVector,
    label: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    busy: Boolean = false,
    tint: Color = MaterialTheme.colorScheme.onSurfaceVariant,
) {
    Box(
        Modifier
            .size(40.dp)
            .clip(CircleShape)
            .clickableNoRipple { if (enabled) onClick() },
        contentAlignment = Alignment.Center,
    ) {
        if (busy) {
            CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
        } else {
            Icon(
                icon,
                contentDescription = label,
                modifier = Modifier.size(18.dp),
                tint = if (enabled) tint else tint.copy(alpha = 0.35f),
            )
        }
    }
}

@Composable
private fun StatusBadge(active: Boolean) {
    val bg = if (active) MaterialTheme.colorScheme.primaryContainer
    else MaterialTheme.colorScheme.surfaceVariant
    val fg = if (active) MaterialTheme.colorScheme.onPrimaryContainer
    else MaterialTheme.colorScheme.onSurfaceVariant
    Text(
        text = if (active) "运行中" else "已暂停",
        style = MaterialTheme.typography.labelSmall,
        color = fg,
        modifier = Modifier
            .clip(CircleShape)
            .background(bg)
            .padding(horizontal = 8.dp, vertical = 2.dp),
    )
}

/** ── 时间线 Tab ─────────────────────────────────────────────────── */
@Composable
private fun TimelinesContent(
    timelines: List<TimelineItem>,
    isSyncing: Boolean,
    onSync: () -> Unit,
    onAction: (String, String) -> Unit,
) {
    Column(Modifier.fillMaxSize()) {
        // 同步按钮：右对齐的紧凑文字按钮，不再占满一整行
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.End,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = onSync, enabled = !isSyncing) {
                if (isSyncing) {
                    CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp)
                } else {
                    Icon(Icons.Default.Sync, contentDescription = null, modifier = Modifier.size(16.dp))
                }
                Spacer(Modifier.width(6.dp))
                Text("同步")
            }
        }

        if (timelines.isEmpty()) {
            EmptyScheduleText("暂无时间线")
            return@Column
        }

        val grouped = timelines.groupBy { it.scene }
        LazyColumn(
            Modifier.fillMaxSize(),
            // 底部 96dp：与其它两个列表一致，给 FAB 让位，最后一张卡片不被压住
            contentPadding = PaddingValues(start = 12.dp, end = 12.dp, bottom = 96.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            grouped.forEach { (scene, items) ->
                item(key = "header_$scene") {
                    Text(
                        text = ScheduleFormat.sceneLabel(scene.ifBlank { "work" }),
                        style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(top = 8.dp, bottom = 2.dp),
                    )
                }
                items(items, key = { it.id }) { timeline ->
                    TimelineCard(timeline = timeline, onAction = { action -> onAction(timeline.id, action) })
                }
            }
        }
    }
}

@Composable
private fun TimelineCard(timeline: TimelineItem, onAction: (String) -> Unit) {
    val active = timeline.status == "active"

    EthanCard {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    text = timeline.name,
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                StatusBadge(active = active)
            }

            // 阶段流：当前 → 下一阶段，用箭头串起来，比两行文字更像「时间线」
            if (timeline.currentPhase != null || timeline.nextPhase != null) {
                Spacer(Modifier.height(8.dp))
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    timeline.currentPhase?.let { PhaseChip(text = it, emphasized = true) }
                    if (timeline.currentPhase != null && timeline.nextPhase != null) {
                        Text(
                            text = "→",
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    timeline.nextPhase?.let { PhaseChip(text = it, emphasized = false) }
                }
            }

            if (timeline.nextAnchor.isNotBlank()) {
                Spacer(Modifier.height(6.dp))
                Text(
                    text = "锚点：${timeline.nextAnchor}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            Spacer(Modifier.height(6.dp))

            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = { onAction("skip_phase") }) { Text("跳过") }
                TextButton(onClick = { onAction("advance_phase") }) { Text("进入下阶段") }
                if (active) {
                    TextButton(onClick = { onAction("pause") }) { Text("暂停") }
                } else {
                    TextButton(onClick = { onAction("resume") }) { Text("恢复") }
                }
                TextButton(onClick = { onAction("cleanup") }) { Text("清理") }
            }
        }
    }
}

@Composable
private fun PhaseChip(text: String, emphasized: Boolean) {
    val bg = if (emphasized) MaterialTheme.colorScheme.primaryContainer
    else MaterialTheme.colorScheme.surfaceVariant
    val fg = if (emphasized) MaterialTheme.colorScheme.onPrimaryContainer
    else MaterialTheme.colorScheme.onSurfaceVariant
    Text(
        text = text,
        style = MaterialTheme.typography.labelMedium,
        color = fg,
        modifier = Modifier
            .clip(MaterialTheme.shapes.small)
            .background(bg)
            .padding(horizontal = 8.dp, vertical = 3.dp),
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CreateScheduleSheet(
    form: CreateScheduleForm,
    isCreating: Boolean,
    onDismiss: () -> Unit,
    onUpdate: (CreateScheduleForm) -> Unit,
    onSubmit: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .padding(bottom = 32.dp)
                .imePadding(),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("创建定时任务", style = MaterialTheme.typography.titleLarge)

            OutlinedTextField(
                value = form.name,
                onValueChange = { onUpdate(form.copy(name = it)) },
                label = { Text("任务名称") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )

            OutlinedTextField(
                value = form.prompt,
                onValueChange = { onUpdate(form.copy(prompt = it)) },
                label = { Text("提示词") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 3,
                maxLines = 6,
            )

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(
                    selected = form.triggerType == "cron",
                    onClick = { onUpdate(form.copy(triggerType = "cron")) },
                    label = { Text("Cron") },
                )
                FilterChip(
                    selected = form.triggerType == "interval",
                    onClick = { onUpdate(form.copy(triggerType = "interval")) },
                    label = { Text("间隔") },
                )
            }

            if (form.triggerType == "cron") {
                OutlinedTextField(
                    value = form.cron,
                    onValueChange = { onUpdate(form.copy(cron = it)) },
                    label = { Text("Cron 表达式") },
                    placeholder = { Text("0 9 * * 1-5") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )
            } else {
                OutlinedTextField(
                    value = form.intervalMinutes,
                    onValueChange = { onUpdate(form.copy(intervalMinutes = it)) },
                    label = { Text("间隔（分钟）") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                )
            }

            OutlinedTextField(
                value = form.sessionId,
                onValueChange = { onUpdate(form.copy(sessionId = it)) },
                label = { Text("关联会话 ID（可选）") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )

            OutlinedTextField(
                value = form.category,
                onValueChange = { onUpdate(form.copy(category = it)) },
                label = { Text("分类（可选）") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )

            OutlinedTextField(
                value = form.scene,
                onValueChange = { onUpdate(form.copy(scene = it)) },
                label = { Text("场景（可选，默认 work）") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )

            Spacer(Modifier.height(4.dp))

            Button(
                onClick = onSubmit,
                enabled = !isCreating,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (isCreating) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                }
                Text("创建")
            }
        }
    }
}
