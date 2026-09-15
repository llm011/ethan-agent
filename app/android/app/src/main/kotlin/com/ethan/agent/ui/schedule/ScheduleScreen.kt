package com.ethan.agent.ui.schedule

import com.ethan.agent.core.model.SessionInfo
import com.ethan.agent.shared.viewmodel.ScheduleUiState
import com.ethan.agent.shared.viewmodel.ScheduleTab
import com.ethan.agent.shared.viewmodel.TimelineItem
import com.ethan.agent.shared.viewmodel.CreateScheduleForm
import androidx.compose.animation.AnimatedVisibility
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
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
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
    Timeline("时间轴视图（同「时间线」tab）", Icons.Default.ViewTimeline),
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
                    scheduledSessions = state.scheduledSessions,
                    heartbeatSessions = state.heartbeatSessions,
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
                    jobs = state.jobs,
                    timelines = state.timelines,
                    isSyncing = state.isSyncingTimelines,
                    onSync = onSyncTimelines,
                    onAction = onTimelineAction,
                    triggeringIds = state.triggeringIds,
                    onTrigger = onTrigger,
                    onToggle = onToggle,
                    onDelete = { id -> pendingDelete = state.jobs.firstOrNull { it.id == id } },
                    onOpenSession = onOpenSession,
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
    scheduledSessions: List<SessionInfo>,
    heartbeatSessions: List<SessionInfo>,
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
        // 任务页的对话列表（对齐 web schedule-view 右栏）：定时/心跳会话各一组，
        // 默认都折叠，展开后点击条目跳到对应会话。
        ScheduleSessionsSection(
            scheduledSessions = scheduledSessions,
            heartbeatSessions = heartbeatSessions,
            onOpenSession = onOpenSession,
        )

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

/**
 * 任务页的对话列表（对齐 web schedule-view 右侧栏的两个折叠组）：
 * 「定时任务对话 (N)」/「心跳对话 (N)」，默认都折叠，点条目进会话。
 * 展开态放组件本地（web 也是组件内 state），不进 ViewModel。
 */
@Composable
private fun ScheduleSessionsSection(
    scheduledSessions: List<SessionInfo>,
    heartbeatSessions: List<SessionInfo>,
    onOpenSession: (String) -> Unit,
) {
    if (scheduledSessions.isEmpty() && heartbeatSessions.isEmpty()) return

    Column(Modifier.fillMaxWidth()) {
        ScheduleSessionGroup(
            title = "定时任务对话",
            sessions = scheduledSessions,
            onOpenSession = onOpenSession,
        )
        ScheduleSessionGroup(
            title = "心跳对话",
            sessions = heartbeatSessions,
            onOpenSession = onOpenSession,
        )
    }
}

@Composable
private fun ScheduleSessionGroup(
    title: String,
    sessions: List<SessionInfo>,
    onOpenSession: (String) -> Unit,
) {
    if (sessions.isEmpty()) return
    var expanded by remember { mutableStateOf(false) }

    Column {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(
                    indication = null,
                    interactionSource = remember { MutableInteractionSource() },
                ) { expanded = !expanded }
                .padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = "$title (${sessions.size})",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f),
            )
            Icon(
                imageVector = if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                contentDescription = if (expanded) "收起" else "展开",
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(20.dp),
            )
        }
        AnimatedVisibility(visible = expanded) {
            Column {
                sessions.forEach { session ->
                    Text(
                        text = session.title.removePrefix("[定时]").removePrefix("[心跳]").ifBlank { "未命名对话" },
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onOpenSession(session.id) }
                            .padding(horizontal = 28.dp, vertical = 8.dp),
                    )
                }
            }
        }
    }
}

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
    /** 按任务名索引的阶段流信息（timelines.yaml）；时间线 tab 下才传。 */
    phaseByJobId: Map<String, TimelineItem> = emptyMap(),
    onTimelineAction: (String, String) -> Unit = { _, _ -> },
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
                // 日期标题**在轴线右侧**、贴着轴线起排。
                //
                // 关键：行间的竖直间距（`DATE_ROW_TOP_GAP`）做在**轴列内部**，
                // 不能放在 Row 的 padding 上 —— 放在 Row 外层的话那段高度没有
                // 轴线覆盖，两组之间就会看到明显的断口（用户反馈的正是这个）。
                Row(
                    Modifier.fillMaxWidth().height(IntrinsicSize.Min),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    // 轴列：与任务行同一列，保证线在同一条竖线上；通长填满整行
                    Box(Modifier.width(AXIS_COLUMN).fillMaxHeight()) {
                        Column(Modifier.fillMaxHeight(), horizontalAlignment = Alignment.CenterHorizontally) {
                            Spacer(
                                Modifier.height(if (groupIndex == 0) 2.dp else DATE_ROW_TOP_GAP),
                            )
                            Box(
                                Modifier
                                    .width(1.dp)
                                    .weight(1f)
                                    .background(MaterialTheme.colorScheme.outlineVariant),
                            )
                        }
                    }
                    Spacer(Modifier.width(AXIS_TO_CONTENT))
                    val label = if (dateKey.isNotBlank()) {
                        val parts = dateKey.split("-")
                        val month = parts.getOrNull(1)?.toIntOrNull() ?: 0
                        val day = parts.getOrNull(2)?.toIntOrNull() ?: 0
                        "${month}月${day}日"
                    } else {
                        "待定"
                    }
                    Text(
                        text = label,
                        style = MaterialTheme.typography.titleSmall,
                        color = if (dateKey == todayKey) MaterialTheme.colorScheme.onSurface
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        modifier = Modifier.padding(vertical = 6.dp),
                    )
                    // 「今天」徽章会让人误以为是可切换的胶囊按钮（旁边正好有
                    // 「今天/全部」切换），改成中性灰文字，纯标注、不可点。
                    if (dateKey == todayKey) {
                        Text(
                            text = "今天",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.padding(start = 6.dp),
                        )
                    }
                }
            }
            itemsIndexed(groupJobs, key = { _, it -> "job_${it.id}" }) { index, job ->
                TimelineRow(
                    job = job,
                    triggering = job.id in triggeringIds,
                    // 轴线的「断头」判断要按**整个列表**算，不能按组内的 first/last ——
                    // 否则每组第一行都不画上半段、最后一行都不画下半段，多个日期组
                    // 排在一起时轴线被切成一根根短线，不成一条时间线。
                    // 日期标题那一行也不画线，所以它的高度天然留出了组间空隙，不必再断线。
                    isFirst = groupIndex == 0 && index == 0,
                    isLast = groupIndex == groups.lastIndex && index == groupJobs.lastIndex,
                    onTrigger = { onTrigger(job) },
                    onToggle = { onToggle(job) },
                    onDelete = { onDelete(job.id) },
                    onOpenSession = { onOpenSession(job.sessionId) },
                    phase = phaseByJobId[job.name]?.currentPhase
                        ?.let { "阶段：$it" },
                )
            }
        }
    }
}

/** 圆点直径。 */
private val DOT_SIZE = 8.dp

/**
 * 轴列宽度 = 圆点直径 + 左右各 2dp 余量；轴线画在它正中。
 *
 * 轴线**贴在最左边**（不再给日期/时间留一条 68dp 的左侧标签列）。
 * 之前做成「标签列 | 轴线 | 卡片」三段式，轴线被推到屏幕中间偏右，
 * 左侧空出一大片 —— 手机上横向空间本来就紧张，这样排是纯浪费。
 */
private val AXIS_COLUMN = DOT_SIZE + 4.dp

/** 轴线与右侧内容（日期标题 / 卡片）之间的间隙。 */
private val AXIS_TO_CONTENT = 14.dp

/** 圆点中心距行顶的距离 —— 对齐卡片首行标题（titleSmall ≈ 20sp）的视觉中心。 */
private val DOT_CENTER_Y = 26.dp

/**
 * 日期标题行上方留出的空隙（第二组起）。
 *
 * **必须做在轴列内部**：日期行的高度里如果没有轴线覆盖，两组任务之间就会
 * 出现一个肉眼可见的断口（用户反馈的正是这个）。放在 Row 的 padding 上
 * 等于把空隙推到轴线外面去，所以这里改成「垫一段 Spacer，再把线 weight(1f)
 * 撑满剩余高度」。第一组不留（贴着列表顶部）。
 */
private val DATE_ROW_TOP_GAP = 16.dp

/**
 * 每张卡片下方的空隙。
 *
 * 同理做在**轴列内部**：卡片自带 padding 的话那段高度在轴列外面，
 * 线就断了。这里由轴列在最底下垫一段等高的 Spacer 制造间距，
 * 上半段线照旧贯通 —— 于是「卡片底 → 下一张卡片顶」之间也是连线。
 */
private val ROW_BOTTOM_GAP = 10.dp

/**
 * 时间轴一行：轴线 + 卡片（时间在卡片内首行）。
 *
 * 布局要点：
 *   - 轴线贴左列，卡片紧跟其后；**时间标签移到卡片内部首行**，
 *     不再单独占一列，横向空间全部让给卡片正文。
 *   - 轴线在行内是通长竖线（圆点叠在线上），只有整个列表的第一行不画上段、
 *     最后一行不画下段，相邻行之间线头自然接续成一条连续时间线。
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
    phase: String? = null,
) {
    val active = job.status == "active"

    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
        // 轴列：整行一条竖线，圆点压在线中间。
        // Box 用 fillMaxHeight 撑满整行，下半段的线才能一直延伸到行底 ——
        // 而「行底」是含卡片下方那 [ROW_BOTTOM_GAP] 的（那个 padding 做在
        // 轴列内部，不是做在 Row 上），所以两行之间的空隙也有线穿过，不断口。
        Box(Modifier.width(AXIS_COLUMN).fillMaxHeight()) {
            val dotTop = DOT_CENTER_Y - DOT_SIZE / 2
            // 上半段：第一行不画（时间轴上端不悬空）
            if (!isFirst) {
                Box(
                    Modifier
                        .align(Alignment.TopCenter)
                        .width(1.dp)
                        .height(dotTop)
                        .background(MaterialTheme.colorScheme.outlineVariant),
                )
            }
            Box(
                Modifier
                    .align(Alignment.TopCenter)
                    .padding(top = dotTop)
                    .size(DOT_SIZE)
                    .clip(CircleShape)
                    .background(
                        if (active) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.outlineVariant
                    ),
            )
            // 下半段：最后一行不画（时间轴下端不拖尾）。
            // 下面塞一个 Spacer 把线顶到行底再留出 ROW_BOTTOM_GAP，
            // 这样「卡片底 → 下一行卡片顶」整段都有线。
            Column(Modifier.fillMaxHeight(), horizontalAlignment = Alignment.CenterHorizontally) {
                Spacer(Modifier.height(dotTop + DOT_SIZE))
                Box(
                    Modifier
                        .width(1.dp)
                        .weight(1f)
                        .background(
                            if (isLast) Color.Transparent
                            else MaterialTheme.colorScheme.outlineVariant,
                        ),
                )
                Spacer(Modifier.height(ROW_BOTTOM_GAP))
            }
        }

        Spacer(Modifier.width(AXIS_TO_CONTENT))

        JobRowCard(
            job = job,
            triggering = triggering,
            onTrigger = onTrigger,
            onToggle = onToggle,
            onDelete = onDelete,
            onOpenSession = onOpenSession,
            modifier = Modifier.weight(1f),
            phase = phase,
            // 时间轴视图里，时间放在卡片首行（替代列表视图那行「8小时后(09:00)」）
            timeBadge = ScheduleFormat.timeLabelOf(job.nextRunTime),
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
    phase: String? = null,
    /** 时间轴视图用：把「09:00」放在首行最左，代替列表视图里的「N 小时后」那行。 */
    timeBadge: String? = null,
) {
    val active = job.status == "active"

    EthanCard(modifier = modifier) {
        Column(Modifier.padding(start = 14.dp, end = 4.dp, top = 12.dp, bottom = 2.dp)) {
            // 名称 + 状态徽章（时间轴视图下，时间在最前面当行首）
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.padding(end = 10.dp),
            ) {
                if (timeBadge != null) {
                    Text(
                        text = timeBadge,
                        style = MaterialTheme.typography.labelMedium,
                        color = if (active) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                    )
                }
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
            // 时间轴视图已经在行首放了时刻，这行「N 小时后」就不必再占一行。
            if (active && timeBadge == null) {
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

            // 阶段流（来自 timelines.yaml）：只挂一条当前阶段的文字，不占独立一行高度，
            // 因为它对多数任务都为空。
            if (!phase.isNullOrBlank()) {
                Spacer(Modifier.height(3.dp))
                Text(
                    text = phase,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(end = 10.dp).fillMaxWidth(),
                )
            }

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

/**
 * ── 时间线 Tab ─────────────────────────────────────────────────────
 *
 * 「时间线」这个名字指的是**时间轴**那一张视图（一条竖线把任务按时间串起来），
 * 不是 timelines.yaml 那套「阶段流」数据 —— 之前两者都叫「时间线」，tab 下的
 * 内容却是卡片列表，而「任务」tab 才是时间轴，正好弄反了。
 *
 * 现在这里对齐 Web 的 `viewLayout === "timeline"` 分支：一条连续的竖轴，
 * 左侧是日期/时间标签列，右侧是紧凑卡片；顶部只留一个「同步阶段流」按钮，
 * 用来刷新 timelines.yaml（阶段流数据在卡片下方单独展开，不占主轴）。
 */
@Composable
private fun TimelinesContent(
    jobs: List<ScheduleJob>,
    timelines: List<TimelineItem>,
    isSyncing: Boolean,
    onSync: () -> Unit,
    onAction: (String, String) -> Unit,
    triggeringIds: Set<String>,
    onTrigger: (ScheduleJob) -> Unit,
    onToggle: (ScheduleJob) -> Unit,
    onDelete: (String) -> Unit,
    onOpenSession: (String) -> Unit,
) {
    var range by remember { mutableStateOf(JobRange.Today) }

    // 「今天」= 今天和明天；无 next_run_time 的（待定）始终保留（与「任务」tab 同口径）
    val visibleJobs = remember(jobs, range) {
        if (range == JobRange.All) jobs
        else jobs.filter { job ->
            val key = ScheduleFormat.dateKeyOf(job.nextRunTime)
            key == null || key <= todayPlusDays(1)
        }
    }

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(start = 12.dp, end = 12.dp, top = 4.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            SegmentedToggle(
                options = JobRange.entries.map { it.label },
                selectedIndex = range.ordinal,
                onSelect = { range = JobRange.entries[it] },
            )
            Spacer(Modifier.weight(1f))
            // 阶段流同步：数据源是 timelines.yaml，与上面的任务列表无关，
            // 放在这里是为了保留入口（原来整个 tab 就是它的界面）。
            TextButton(onClick = onSync, enabled = !isSyncing) {
                if (isSyncing) {
                    CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp)
                } else {
                    Icon(Icons.Default.Sync, contentDescription = null, modifier = Modifier.size(16.dp))
                }
                Spacer(Modifier.width(6.dp))
                Text("同步阶段流")
            }
        }

        if (visibleJobs.isEmpty()) {
            EmptyScheduleText(if (range == JobRange.Today) "今天和明天暂无定时任务" else "暂无定时任务")
            return@Column
        }

        TimelineLayout(
            jobs = visibleJobs,
            triggeringIds = triggeringIds,
            onTrigger = onTrigger,
            onToggle = onToggle,
            onDelete = onDelete,
            onOpenSession = onOpenSession,
            // 阶段流：只有在时间线 tab 下才把 timelines.yaml 的阶段信息附在卡片上
            phaseByJobId = remember(timelines) { timelines.associateBy { it.name } },
            onTimelineAction = onAction,
        )
    }
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
