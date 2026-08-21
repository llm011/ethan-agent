package com.ethan.agent.ui.agenda

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChatBubble
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Event
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.NotificationsNone
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ethan.agent.core.model.AgendaEvent
import com.ethan.agent.shared.viewmodel.AgendaEventForm
import com.ethan.agent.shared.viewmodel.AgendaUiState
import com.ethan.agent.shared.viewmodel.dateKeyOf
import com.ethan.agent.shared.viewmodel.daysInMonth
import com.ethan.agent.shared.viewmodel.eventDateKey
import com.ethan.agent.shared.viewmodel.eventTimeText
import com.ethan.agent.shared.viewmodel.firstDayOfMonthIso
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.EthanTopBar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer
import kotlinx.coroutines.delay
import java.time.Instant
import java.time.LocalDate as JavaLocalDate
import java.time.LocalTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

private val WEEKDAY_LABELS = listOf("一", "二", "三", "四", "五", "六", "日")
private const val NOW_RED = 0xFFEF4444

private val STATUS_LABEL = mapOf(
    "pending" to "待提醒",
    "fired" to "已提醒",
    "missed" to "已错过",
    "done" to "已完成",
)

private fun dateKeyToLabel(dateKey: String): String {
    val d = runCatching { JavaLocalDate.parse(dateKey) }.getOrNull() ?: return dateKey
    val week = WEEKDAY_LABELS[d.dayOfWeek.value - 1]
    return "${d.monthValue}月${d.dayOfMonth}日 周$week"
}

private fun repeatLabel(ev: AgendaEvent): String = when (ev.repeat) {
    "daily" -> "每天"
    "weekly" -> {
        val days = ev.weekdays.sorted().mapNotNull { WEEKDAY_LABELS.getOrNull(it - 1) }.joinToString("、")
        if (days.isBlank()) "每周" else "周$days"
    }
    else -> ""
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgendaScreen(
    state: AgendaUiState,
    onBack: () -> Unit = {},
    onRefresh: () -> Unit,
    onToggleEnabled: () -> Unit,
    onSelectDate: (String) -> Unit,
    onPrevMonth: () -> Unit,
    onNextMonth: () -> Unit,
    onToggleCalendar: () -> Unit,
    onGoToday: () -> Unit,
    onShowCreate: () -> Unit,
    onEditEvent: (AgendaEvent) -> Unit,
    onDismissSheet: () -> Unit,
    onUpdateForm: (AgendaEventForm) -> Unit,
    onSubmit: () -> Unit,
    onSetCompletion: (AgendaEvent, String) -> Unit,
    onCancelAbandon: () -> Unit,
    onAbandonTextChange: (String) -> Unit,
    onConfirmAbandon: () -> Unit,
    onBreakdown: (AgendaEvent) -> Unit,
    onRequestDelete: (String) -> Unit,
    onCancelDelete: () -> Unit,
    onConfirmDelete: () -> Unit,
    onClearError: () -> Unit,
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    // 秒级刷新 today（字符串结构相等，仅跨午夜时触发重组），与 Web 端每秒重算行为一致
    var today by remember { mutableStateOf(java.time.LocalDate.now().toString()) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(1000)
            today = java.time.LocalDate.now().toString()
        }
    }
    val eventDates = remember(state.events) { state.events.mapNotNull { eventDateKey(it) }.toSet() }
    val dayEvents = remember(state.events, state.selectedDateKey) {
        state.events.mapNotNull { ev ->
            val dk = eventDateKey(ev)
            if (dk == state.selectedDateKey) Triple(ev, dk, eventTimeText(ev)) else null
        }.sortedBy { it.third }
    }

    Scaffold(
        topBar = {
            EthanTopBar(
                title = "日程",
                onBack = onBack,
                actions = {
                    IconButton(onClick = onToggleEnabled, enabled = !state.togglingEnabled) {
                        if (state.togglingEnabled) {
                            CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                        } else {
                            Icon(
                                if (state.enabled) Icons.Default.Notifications else Icons.Default.NotificationsNone,
                                contentDescription = "Agent 日程工具开关",
                                tint = if (state.enabled) MaterialTheme.colorScheme.primary
                                    else MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    IconButton(onClick = onRefresh, enabled = !state.isLoading) {
                        Icon(Icons.Default.Refresh, contentDescription = "刷新")
                    }
                },
            )
        },
        snackbarHost = { SnackbarContainer(snackbar) },
        floatingActionButton = {
            FloatingActionButton(onClick = onShowCreate) {
                Icon(Icons.Default.Event, contentDescription = "添加日程")
            }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            CalendarPanel(
                state = state,
                today = today,
                eventDates = eventDates,
                onToggleCalendar = onToggleCalendar,
                onPrevMonth = onPrevMonth,
                onNextMonth = onNextMonth,
                onGoToday = onGoToday,
                onSelectDate = onSelectDate,
            )

            // 选中日期标题行
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    dateKeyToLabel(state.selectedDateKey),
                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.SemiBold),
                )
                if (state.selectedDateKey == today) {
                    Spacer(Modifier.width(6.dp))
                    Text(
                        "今天",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
                Spacer(Modifier.weight(1f))
                Text(
                    "${dayEvents.size} 项",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            when {
                state.isLoading && state.events.isEmpty() -> LoadingBox()
                dayEvents.isEmpty() -> EmptyDayHint(selectedIsToday = state.selectedDateKey == today)
                else -> DayEventList(
                    dayEvents = dayEvents,
                    isToday = state.selectedDateKey == today,
                    completingIds = state.completingIds,
                    onSetCompletion = onSetCompletion,
                    onEdit = onEditEvent,
                    onBreakdown = onBreakdown,
                    onDelete = onRequestDelete,
                )
            }
        }

        if (state.showEditSheet) {
            EventEditSheet(
                form = state.form,
                isSaving = state.isSaving,
                isEditing = state.editingId != null,
                onDismiss = onDismissSheet,
                onUpdate = onUpdateForm,
                onSubmit = onSubmit,
            )
        }

        state.pendingDeleteId?.let {
            AlertDialog(
                onDismissRequest = onCancelDelete,
                title = { Text("删除日程") },
                text = { Text("确定要删除这个日程吗？此操作无法撤销。") },
                confirmButton = { TextButton(onClick = onConfirmDelete) { Text("删除", color = MaterialTheme.colorScheme.error) } },
                dismissButton = { TextButton(onClick = onCancelDelete) { Text("取消") } },
            )
        }

        // 废弃弹窗：输入这个时间段实际做了什么（将覆盖原日程标题）
        state.pendingAbandonEvent?.let { ev ->
            AlertDialog(
                onDismissRequest = onCancelAbandon,
                title = { Text("废弃日程") },
                text = {
                    Column {
                        Text(
                            "这个时间段实际做了什么？将覆盖原日程标题。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(8.dp))
                        OutlinedTextField(
                            value = state.abandonText,
                            onValueChange = onAbandonTextChange,
                            placeholder = { Text(ev.title.ifBlank { "实际做了什么..." }) },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                },
                confirmButton = {
                    TextButton(onClick = onConfirmAbandon) { Text("确认废弃", color = MaterialTheme.colorScheme.error) }
                },
                dismissButton = { TextButton(onClick = onCancelAbandon) { Text("取消") } },
            )
        }
    }
}

// ── 日历面板：可收起，点某天切过去 ─────────────────────────────────────────

@Composable
private fun CalendarPanel(
    state: AgendaUiState,
    today: String,
    eventDates: Set<String>,
    onToggleCalendar: () -> Unit,
    onPrevMonth: () -> Unit,
    onNextMonth: () -> Unit,
    onGoToday: () -> Unit,
    onSelectDate: (String) -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        // 收起态：一行日期标签，点击展开
        AnimatedVisibility(visible = !state.calendarExpanded, enter = expandVertically(), exit = shrinkVertically()) {
            Surface(
                onClick = onToggleCalendar,
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f),
            ) {
                Row(
                    Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        Icons.Default.Event,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(16.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        dateKeyToLabel(state.selectedDateKey) + if (state.selectedDateKey == today) " · 今天" else "",
                        style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
                    )
                    Spacer(Modifier.weight(1f))
                    Icon(
                        Icons.Default.ExpandMore,
                        contentDescription = "展开日历",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(20.dp),
                    )
                }
            }
        }

        // 展开态：月份导航 + 星期行 + 日期网格
        AnimatedVisibility(visible = state.calendarExpanded, enter = expandVertically(), exit = shrinkVertically()) {
            Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp)) {
                Row(
                    Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    IconButton(onClick = onPrevMonth, modifier = Modifier.size(32.dp)) {
                        Icon(Icons.Default.ChevronLeft, contentDescription = "上个月", modifier = Modifier.size(18.dp))
                    }
                    Text(
                        "${state.displayYear}年${state.displayMonth}月",
                        style = MaterialTheme.typography.titleSmall.copy(fontWeight = FontWeight.SemiBold),
                        modifier = Modifier.weight(1f),
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                    )
                    IconButton(onClick = onNextMonth, modifier = Modifier.size(32.dp)) {
                        Icon(Icons.Default.ChevronRight, contentDescription = "下个月", modifier = Modifier.size(18.dp))
                    }
                    TextButton(onClick = onGoToday) { Text("今天", style = MaterialTheme.typography.labelMedium) }
                    IconButton(onClick = onToggleCalendar, modifier = Modifier.size(32.dp)) {
                        Icon(Icons.Default.ExpandLess, contentDescription = "收起日历", modifier = Modifier.size(18.dp))
                    }
                }

                // 星期标题行
                Row(Modifier.fillMaxWidth()) {
                    WEEKDAY_LABELS.forEach { w ->
                        Text(
                            w,
                            modifier = Modifier.weight(1f),
                            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Spacer(Modifier.height(2.dp))

                // 日期网格（周一开头）
                val cells: List<String?> = remember(state.displayYear, state.displayMonth) {
                    val pad = firstDayOfMonthIso(state.displayYear, state.displayMonth) - 1
                    val total = daysInMonth(state.displayYear, state.displayMonth)
                    List(pad) { null } + (1..total).map { dateKeyOf(state.displayYear, state.displayMonth, it) }
                }
                cells.chunked(7).forEach { week ->
                    Row(Modifier.fillMaxWidth()) {
                        week.forEach { key ->
                            if (key == null) {
                                Spacer(Modifier.weight(1f).height(36.dp))
                            } else {
                                val dayNum = key.substring(8, 10).toIntOrNull() ?: 0
                                val isSelected = key == state.selectedDateKey
                                val isToday = key == today
                                val hasEvent = key in eventDates
                                Box(
                                    modifier = Modifier.weight(1f).height(36.dp),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Surface(
                                        onClick = { onSelectDate(key) },
                                        shape = CircleShape,
                                        color = when {
                                            isSelected -> MaterialTheme.colorScheme.primary
                                            isToday -> MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)
                                            else -> Color.Transparent
                                        },
                                        modifier = Modifier.size(32.dp),
                                    ) {
                                        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                                Text(
                                                    dayNum.toString(),
                                                    style = MaterialTheme.typography.bodySmall.copy(
                                                        fontWeight = if (isSelected || isToday) FontWeight.Bold else FontWeight.Normal
                                                    ),
                                                    color = when {
                                                        isSelected -> MaterialTheme.colorScheme.onPrimary
                                                        isToday -> MaterialTheme.colorScheme.primary
                                                        else -> MaterialTheme.colorScheme.onSurface
                                                    },
                                                )
                                            }
                                        }
                                    }
                                    if (hasEvent) {
                                        Box(
                                            Modifier
                                                .align(Alignment.BottomCenter)
                                                .padding(bottom = 2.dp)
                                                .size(4.dp)
                                                .clip(CircleShape)
                                                .background(
                                                    if (isSelected) MaterialTheme.colorScheme.onPrimary
                                                    else MaterialTheme.colorScheme.primary
                                                ),
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

// ── 某天的事件列表（含"现在"指示器） ─────────────────────────────────────

@Composable
private fun DayEventList(
    dayEvents: List<Triple<AgendaEvent, String, String>>,
    isToday: Boolean,
    completingIds: Set<String>,
    onSetCompletion: (AgendaEvent, String) -> Unit,
    onEdit: (AgendaEvent) -> Unit,
    onBreakdown: (AgendaEvent) -> Unit,
    onDelete: (String) -> Unit,
) {
    // 每秒刷新的"现在"指示器（红点 + 横线 + HH:mm:ss），与 Web 端一致
    val timeFormatter = remember { DateTimeFormatter.ofPattern("HH:mm:ss") }
    var nowText by remember { mutableStateOf(LocalTime.now().format(timeFormatter)) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(1000)
            nowText = LocalTime.now().format(timeFormatter)
        }
    }
    val nowHm = nowText.substring(0, 5)

    LazyColumn(
        Modifier.fillMaxSize().padding(horizontal = 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        val nowIndex = if (isToday) dayEvents.indexOfFirst { it.third > nowHm }.let { if (it < 0) dayEvents.size else it } else -2
        dayEvents.forEachIndexed { idx, (ev, _, timeText) ->
            if (nowIndex == idx) {
                item(key = "__now__") { NowIndicator(nowText) }
            }
            item(key = ev.id) {
                EventCard(
                    ev = ev,
                    timeText = timeText,
                    completing = ev.id in completingIds,
                    onSetCompletion = { completion -> onSetCompletion(ev, completion) },
                    onEdit = { onEdit(ev) },
                    onBreakdown = { onBreakdown(ev) },
                    onDelete = { onDelete(ev.id) },
                )
            }
        }
        if (nowIndex == dayEvents.size) {
            item(key = "__now_end__") { NowIndicator(nowText) }
        }
        item { Spacer(Modifier.height(80.dp)) }
    }
}

@Composable
private fun NowIndicator(nowText: String) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(7.dp).clip(CircleShape).background(Color(NOW_RED))
        )
        Box(
            Modifier.weight(1f).height(1.dp).background(Color(NOW_RED).copy(alpha = 0.7f))
        )
        Spacer(Modifier.width(6.dp))
        Text(
            nowText,
            style = MaterialTheme.typography.labelSmall.copy(fontFamily = FontFamily.Monospace),
            color = Color(NOW_RED),
        )
    }
}

// ── 完成度 4 态切换（与 Web 端 CompletionToggle 一致） ─────────────────────

private val COMPLETION_OPTIONS = listOf(
    Triple("not_started", "○", "未开始"),
    Triple("partial", "◐", "完成部分"),
    Triple("done", "●", "已完成"),
    Triple("abandoned", "✕", "废弃"),
)

@Composable
private fun completionColor(value: String): Color = when (value) {
    "partial" -> Color(0xFFF59E0B)     // amber-500
    "done" -> Color(0xFF22C55E)        // green-500
    "abandoned" -> Color(0xFFF87171)   // red-400
    else -> MaterialTheme.colorScheme.onSurfaceVariant
}

@Composable
private fun CompletionToggle(
    ev: AgendaEvent,
    completing: Boolean,
    onChange: (String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    val current = COMPLETION_OPTIONS.firstOrNull { it.first == ev.completion } ?: COMPLETION_OPTIONS[0]
    Box {
        IconButton(
            onClick = { expanded = true },
            enabled = !completing,
            modifier = Modifier.size(30.dp),
        ) {
            if (completing) {
                CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp)
            } else {
                Text(
                    current.second,
                    style = MaterialTheme.typography.bodyLarge,
                    color = completionColor(current.first),
                )
            }
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            COMPLETION_OPTIONS.forEach { (value, symbol, label) ->
                DropdownMenuItem(
                    text = {
                        Text(
                            "$symbol  $label" + if (value == current.first) "（当前）" else "",
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = if (value == current.first) FontWeight.Medium else FontWeight.Normal,
                        )
                    },
                    onClick = {
                        expanded = false
                        if (value != current.first) onChange(value)
                    },
                )
            }
        }
    }
}

@Composable
private fun EventCard(
    ev: AgendaEvent,
    timeText: String,
    completing: Boolean,
    onSetCompletion: (String) -> Unit,
    onEdit: () -> Unit,
    onBreakdown: () -> Unit,
    onDelete: () -> Unit,
) {
    val completion = ev.completion.ifBlank { "not_started" }
    val isDone = completion == "done"
    val isAbandoned = completion == "abandoned"
    val dimmed = isDone || isAbandoned
    val dotColor = when (ev.status) {
        "pending" -> MaterialTheme.colorScheme.primary
        "missed" -> MaterialTheme.colorScheme.error
        else -> MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.4f)
    }
    Card(
        Modifier.fillMaxWidth().alpha(if (dimmed) 0.6f else 1f),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(7.dp).clip(CircleShape).background(dotColor))
                Spacer(Modifier.width(6.dp))
                Text(
                    timeText,
                    style = MaterialTheme.typography.labelMedium.copy(fontFamily = FontFamily.Monospace),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                CompletionToggle(ev = ev, completing = completing, onChange = onSetCompletion)
                Text(
                    ev.title,
                    style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.Medium),
                    textDecoration = if (dimmed) TextDecoration.LineThrough else null,
                    color = if (isAbandoned) MaterialTheme.colorScheme.error.copy(alpha = 0.7f)
                    else MaterialTheme.colorScheme.onSurface,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                Spacer(Modifier.weight(1f))
                Text(
                    STATUS_LABEL[ev.status] ?: ev.status,
                    style = MaterialTheme.typography.labelSmall,
                    color = when (ev.status) {
                        "pending" -> MaterialTheme.colorScheme.primary
                        "missed" -> MaterialTheme.colorScheme.error
                        else -> MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }
            val rep = repeatLabel(ev)
            if (rep.isNotBlank()) {
                Spacer(Modifier.height(2.dp))
                Text(
                    rep,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (ev.note.isNotBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(
                    ev.note,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onBreakdown, modifier = Modifier.size(32.dp)) {
                    Icon(
                        Icons.Default.ChatBubble,
                        contentDescription = "拆解该安排",
                        modifier = Modifier.size(16.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                IconButton(onClick = onEdit, modifier = Modifier.size(32.dp)) {
                    Icon(
                        Icons.Default.Edit,
                        contentDescription = "编辑",
                        modifier = Modifier.size(16.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                IconButton(onClick = onDelete, modifier = Modifier.size(32.dp)) {
                    Icon(
                        Icons.Default.Delete,
                        contentDescription = "删除",
                        modifier = Modifier.size(16.dp),
                        tint = MaterialTheme.colorScheme.error.copy(alpha = 0.8f),
                    )
                }
            }
        }
    }
}

@Composable
private fun EmptyDayHint(selectedIsToday: Boolean) {
    Column(
        Modifier.fillMaxSize().padding(top = 48.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(
            Icons.Default.Event,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
            modifier = Modifier.size(40.dp),
        )
        Spacer(Modifier.height(8.dp))
        Text(
            "这一天暂无日程",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            if (selectedIsToday) "点击右下角 + 添加日程" else "点击日期可切换查看",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
        )
    }
}

// ── 添加 / 编辑日程底部表单 ───────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun EventEditSheet(
    form: AgendaEventForm,
    isSaving: Boolean,
    isEditing: Boolean,
    onDismiss: () -> Unit,
    onUpdate: (AgendaEventForm) -> Unit,
    onSubmit: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var showDatePicker by remember { mutableStateOf(false) }
    var showTimePicker by remember { mutableStateOf(false) }

    val valid = form.title.isNotBlank() && form.dateKey.isNotBlank() &&
        (form.repeat != "weekly" || form.weekdays.isNotEmpty())

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp).padding(bottom = 32.dp).imePadding(),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                if (isEditing) "编辑日程" else "添加日程",
                style = MaterialTheme.typography.titleLarge,
            )
            Text(
                "时间到了 Agent 会提醒你${if (isEditing) "；修改后立即生效" else ""}。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            OutlinedTextField(
                value = form.title,
                onValueChange = { onUpdate(form.copy(title = it)) },
                label = { Text("要做什么") },
                placeholder = { Text("如：下午 3 点开周会") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { showDatePicker = true }, modifier = Modifier.weight(1f)) {
                    Text("日期 ${form.dateKey}")
                }
                OutlinedButton(onClick = { showTimePicker = true }, modifier = Modifier.weight(1f)) {
                    Text("时间 ${form.timeText}")
                }
            }

            // 重复
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("none" to "单次", "daily" to "每天", "weekly" to "每周").forEach { (k, label) ->
                    androidx.compose.material3.FilterChip(
                        selected = form.repeat == k,
                        onClick = { onUpdate(form.copy(repeat = k)) },
                        label = { Text(label) },
                    )
                }
            }

            if (form.repeat == "weekly") {
                // FlowRow：7 个 chip（各 48dp 最小交互宽）在窄屏单行放不下，自动换行
                FlowRow(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    WEEKDAY_LABELS.forEachIndexed { i, label ->
                        val iso = i + 1
                        val active = iso in form.weekdays
                        androidx.compose.material3.FilterChip(
                            selected = active,
                            onClick = {
                                onUpdate(form.copy(weekdays = if (active) form.weekdays - iso else form.weekdays + iso))
                            },
                            label = { Text(label) },
                        )
                    }
                }
            }

            OutlinedTextField(
                value = form.note,
                onValueChange = { onUpdate(form.copy(note = it)) },
                label = { Text("备注（可选）") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 2,
                maxLines = 4,
            )

            androidx.compose.material3.Button(
                onClick = onSubmit,
                enabled = valid && !isSaving,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (isSaving) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                }
                Text(if (isEditing) "保存" else "添加")
            }
        }
    }

    if (showDatePicker) {
        val initialMillis = runCatching {
            JavaLocalDate.parse(form.dateKey).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
        }.getOrNull()
        val dateState = rememberDatePickerState(initialSelectedDateMillis = initialMillis)
        DatePickerDialog(
            onDismissRequest = { showDatePicker = false },
            confirmButton = {
                TextButton(onClick = {
                    dateState.selectedDateMillis?.let { ms ->
                        val d = Instant.ofEpochMilli(ms).atZone(ZoneOffset.UTC).toLocalDate()
                        onUpdate(form.copy(dateKey = d.toString()))
                    }
                    showDatePicker = false
                }) { Text("确定") }
            },
            dismissButton = { TextButton(onClick = { showDatePicker = false }) { Text("取消") } },
        ) { DatePicker(state = dateState) }
    }

    if (showTimePicker) {
        val parts = form.timeText.split(":")
        val timeState = rememberTimePickerState(
            initialHour = parts.getOrNull(0)?.toIntOrNull() ?: 9,
            initialMinute = parts.getOrNull(1)?.toIntOrNull() ?: 0,
            is24Hour = true,
        )
        AlertDialog(
            onDismissRequest = { showTimePicker = false },
            title = { Text("选择时间") },
            text = { TimePicker(state = timeState) },
            confirmButton = {
                TextButton(onClick = {
                    onUpdate(form.copy(timeText = "%02d:%02d".format(timeState.hour, timeState.minute)))
                    showTimePicker = false
                }) { Text("确定") }
            },
            dismissButton = { TextButton(onClick = { showTimePicker = false }) { Text("取消") } },
        )
    }
}
