package com.ethan.agent.ui.memory

import com.ethan.agent.shared.viewmodel.MemoryUiState
import com.ethan.agent.shared.viewmodel.FactItem
import com.ethan.agent.shared.viewmodel.MemoryEditTarget
import com.ethan.agent.shared.viewmodel.MemoryTab
import com.ethan.agent.shared.viewmodel.RecordsFilter
import com.ethan.agent.shared.viewmodel.recordId
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.CalendarToday
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.SelectableDates
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.BorderStroke
import androidx.compose.ui.window.Dialog
import com.ethan.agent.core.model.Fact
import com.ethan.agent.core.model.InsightItem
import com.ethan.agent.core.model.Procedure
import com.ethan.agent.core.model.StructuredRecord
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.EthanCard
import com.ethan.agent.ui.components.EthanEmptyState
import com.ethan.agent.ui.components.EthanScrollableTabBar
import com.ethan.agent.ui.components.EthanTopBar
import com.ethan.agent.ui.components.EthanScaffold
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SimpleMarkdown
import com.ethan.agent.ui.components.SnackbarContainer
import java.text.SimpleDateFormat
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MemoryScreen(
    state: MemoryUiState,
    onTabChange: (MemoryTab) -> Unit,
    onSelectFact: (FactItem) -> Unit,
    onEditChange: (String) -> Unit,
    onClearError: () -> Unit,
    onBack: () -> Unit = {},
    // 共用编辑器
    onDismissEditor: () -> Unit = {},
    onSaveEditing: () -> Unit = {},
    onDeleteEditing: () -> Unit = {},
    // new
    onInsightsDateChange: (String) -> Unit = {},
    onRefreshInsights: () -> Unit = {},
    onRecordsFilterChange: (RecordsFilter) -> Unit = {},
    onRecordsSearchChange: (String) -> Unit = {},
    onSelectRecord: (StructuredRecord) -> Unit = {},
    onSelectProcedure: (Procedure) -> Unit = {},
    onDeleteRecord: (String) -> Unit = {},
    onConfirmRecord: (String) -> Unit = {},
    onDeleteProcedure: (String) -> Unit = {},
    onConsolidate: () -> Unit = {},
    onConsolidateRecords: () -> Unit = {},
    onLoadSummaries: () -> Unit = {},
    onHideSummaries: () -> Unit = {},
    onSummariesDateChange: (String) -> Unit = {},
    onLoadMoreSummaries: () -> Unit = {},
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    // Consolidating dialog
    if (state.isConsolidating) {
        Dialog(onDismissRequest = {}) {
            Surface(shape = MaterialTheme.shapes.large) {
                Column(
                    Modifier.padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    CircularProgressIndicator()
                    Text("正在沉淀，可能需要 1-2 分钟…")
                }
            }
        }
    }

    // Daily summaries sheet
    if (state.showSummaries) {
        SummariesDialog(
            summaries = state.summaries,
            date = state.summariesDate,
            summaryDates = state.summaryDates,
            datesTruncated = state.summaryDatesTruncated,
            loading = state.summariesLoading,
            hasMore = state.summariesHasMore,
            onDateChange = onSummariesDateChange,
            onLoadMore = onLoadMoreSummaries,
            onDismiss = onHideSummaries,
        )
    }

    // 编辑页覆盖层：事实 / 流程 / 结构化记忆共用一个编辑器。
    // 以前「事实」是先开详情页再点编辑进第二层，「流程」压根没有编辑，
    // 「结构化记忆」点一下就直接跳进编辑 —— 三个 tab 三种行为。现在统一。
    val editing = state.editing
    if (editing != null) {
        MemoryEditorScreen(
            target = editing,
            content = state.editContent,
            onBack = onDismissEditor,
            onContentChange = onEditChange,
            onSave = onSaveEditing,
            onDelete = onDeleteEditing,
        )
        return
    }

    var factsSearchQuery by remember { mutableStateOf("") }

    EthanScaffold(
        topBar = {
            EthanTopBar(
                title = "记忆",
                onBack = onBack,
                actions = {
                    when (state.tab) {
                        MemoryTab.Facts -> {
                            IconButton(onClick = onConsolidate) {
                                Icon(Icons.Filled.AutoAwesome, contentDescription = "立即沉淀")
                            }
                        }
                        MemoryTab.Records -> {
                            IconButton(onClick = onLoadSummaries) {
                                Icon(Icons.Filled.CalendarToday, contentDescription = "日摘要")
                            }
                            IconButton(onClick = onConsolidateRecords) {
                                Icon(Icons.Filled.AutoAwesome, contentDescription = "结构化沉淀")
                            }
                        }
                        else -> Unit
                    }
                },
            )
        },
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            EthanScrollableTabBar(
                tabs = MemoryTab.entries.toList(),
                selectedTab = state.tab,
                onTabSelected = { tab -> onTabChange(tab) },
                labelOf = { it.title },
            )

            if (state.isLoading) {
                LoadingBox()
                return@Column
            }

            when (state.tab) {
                MemoryTab.Facts -> FactsListContent(
                    facts = state.facts,
                    searchQuery = factsSearchQuery,
                    onSearchChange = { factsSearchQuery = it },
                    onSelect = onSelectFact,
                )

                MemoryTab.Insights -> InsightsTab(
                    insights = state.insights,
                    date = state.insightsDate,
                    onDateChange = onInsightsDateChange,
                    onRefresh = onRefreshInsights,
                )
                MemoryTab.Procedures -> ProceduresTab(
                    procedures = state.procedures,
                    onEdit = onSelectProcedure,
                    onDelete = onDeleteProcedure,
                )
                MemoryTab.Records -> RecordsTab(
                    records = state.records,
                    filter = state.recordsFilter,
                    search = state.recordsSearch,
                    onFilterChange = onRecordsFilterChange,
                    onSearchChange = onRecordsSearchChange,
                    onEdit = onSelectRecord,
                    onConfirm = onConfirmRecord,
                    onDelete = onDeleteRecord,
                )
            }
        }
    }
}

// ── 共用编辑器（事实 / 流程 / 结构化记忆）─────────────────────────────────────

/**
 * 三张卡共用的编辑页。
 *
 * 统一的不只是「双击进编辑」这个入口，页面本身也收敛了：
 * - 顶栏固定三段式：返回 | 标题 | 删除 + 保存（都用 [EthanTopBar]，不再手搓 `TopAppBar`）
 * - 正文一个多行输入框，占据中间全部高度
 * - 底部一行只读的元信息，与列表卡片的 [MemoryCardMeta] 同字号同配色
 *
 * 删掉的两套旧实现里，「事实」是「详情页 + 二级编辑」两层，「记录」是点卡片直接进，
 * 元信息一行靠 `RecordMetaRow` 自己贴左边缘（用户反馈的「底下的字顶到左边」就是
 * 它没吃到横向 padding）。
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun MemoryEditorScreen(
    target: MemoryEditTarget,
    content: String,
    onBack: () -> Unit,
    onContentChange: (String) -> Unit,
    onSave: () -> Unit,
    onDelete: () -> Unit,
) {
    var showDeleteConfirm by remember { mutableStateOf(false) }

    if (showDeleteConfirm) {
        AlertDialog(
            onDismissRequest = { showDeleteConfirm = false },
            title = { Text("删除这条记忆？") },
            text = { Text("删除后无法恢复。") },
            confirmButton = {
                TextButton(onClick = { showDeleteConfirm = false; onDelete() }) { Text("删除") }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteConfirm = false }) { Text("取消") }
            },
        )
    }

    // 内容为空时不给保存：后端会因为空正文写入一条无意义记录。
    val canSave = content.isNotBlank()

    EthanScaffold(
        topBar = {
            EthanTopBar(
                title = target.title,
                onBack = onBack,
                actions = {
                    IconButton(onClick = { showDeleteConfirm = true }) {
                        Icon(Icons.Default.Delete, contentDescription = "删除")
                    }
                    TextButton(onClick = onSave, enabled = canSave) {
                        Text("保存", fontWeight = FontWeight.SemiBold)
                    }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .imePadding(),
        ) {
            OutlinedTextField(
                value = content,
                onValueChange = onContentChange,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 12.dp),
                label = { Text(if (target is MemoryEditTarget.Procedure) "规则" else "内容") },
                placeholder = { Text("支持 Markdown") },
                textStyle = MaterialTheme.typography.bodyLarge,
                minLines = 6,
            )

            // 元信息行：整行加横向 padding —— 旧实现里它直接贴着 Column 左上角，
            // 于是「preference 生效 置信度 100%…」那行字顶到了屏幕最左边。
            Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
                EditorMetaRow(target)
            }
        }
    }
}

/** 编辑页底部的只读元信息。字段随卡片类型变化，样式统一走 [MemoryCardMeta]。 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun EditorMetaRow(target: MemoryEditTarget) {
    when (target) {
        is MemoryEditTarget.Fact -> {
            val fact = target.original
            FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                MemoryCardMeta(
                    fact.category.ifBlank { "knowledge" } to true,
                    "置信度 ${(fact.confidence * 100).toInt()}%" to false,
                    formatEpochDate(fact.createdAt) to false,
                    (if (fact.source.isNotBlank()) "来源 ${fact.source.take(12)}" else "") to false,
                )
            }
        }
        is MemoryEditTarget.Procedure -> {
            val proc = target.original
            FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                MemoryCardMeta(
                    "命中 ${proc.hitCount} 次" to false,
                    formatEpochDate(proc.createdAt) to false,
                )
            }
        }
        is MemoryEditTarget.Record -> RecordMetaRow(target.original)
    }
}

// ── Facts tab ────────────────────────────────────────────────────────────────

@Composable
private fun FactsListContent(
    facts: List<FactItem>,
    searchQuery: String,
    onSearchChange: (String) -> Unit,
    onSelect: (FactItem) -> Unit,
) {
    val listState = rememberLazyListState()

    val filteredFacts = if (searchQuery.isBlank()) {
        facts
    } else {
        facts.filter { it.fact.content.contains(searchQuery, ignoreCase = true) }
    }

    // 搜索框是**列表的第一项**，跟着内容一起滑走。
    //
    // 之前它是个常驻/可收起的头部，为此写过好几版滚动检测：位置量、行程量、
    // 收起后 animateScrollToItem 对齐……全都在和用户的手指抢滚动位置。
    // 根因是「收起会改变列表视口高度」—— 视口一变，「顶端对着哪一项」就变，
    // 内容被顶走（用户反馈「第一条永远看不到」），而且一旦想用代码把位置
    // 掰回去，就会和手势打架（滑不动、被拽回、收起又立刻展开）。
    //
    // 放进列表里当第一项，这些问题一次性消失：没有收缩动画、没有视口变化、
    // 没有任何 animateScrollToItem。搜索框自己也是被 LazyColumn 虚拟化管理的，
    // 滑上去就回收，长列表也不会因为它在顶上而多留一块空白。
    LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item(key = "__search__") {
            SearchField(
                value = searchQuery,
                onValueChange = onSearchChange,
                placeholder = "搜索记忆，支持 Markdown...",
            )
        }

        if (filteredFacts.isEmpty()) {
            item(key = "__empty__") {
                Box(
                    Modifier.fillMaxWidth().padding(top = 48.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        if (searchQuery.isBlank()) "暂无事实记忆" else "未找到匹配的记忆",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        } else {
            items(filteredFacts, key = { it.index }) { item ->
                FactListCard(item, onClick = { onSelect(item) })
            }
        }
    }
}

/** 列表里的搜索框。事实 / 结构化记忆两个 tab 共用，外观一致。 */
@Composable
private fun SearchField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = Modifier.fillMaxWidth(),
        placeholder = { Text(placeholder) },
        leadingIcon = {
            Icon(
                Icons.Default.Search,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        },
        singleLine = true,
        shape = MaterialTheme.shapes.small,
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.5f),
            unfocusedBorderColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.3f),
        ),
    )
}

@Composable
private fun FactListCard(item: FactItem, onClick: () -> Unit) {
    val fact = item.fact
    val date = remember(fact.createdAt) { formatEpochDate(fact.createdAt) }

    // 不再放 🧠 头像：四个 tab 里只有它带头像，且 emoji 在深浅主题下
    // 渲染出来的观感飘忽（不是主题色、不跟随 tint）。正文直接从卡片左边起排，
    // 横向空间也让给了内容。
    //
    // 双击进编辑：以前是单击 → 详情页 → 再点右上角编辑 → 才进编辑，两层跳。
    // 详情页本身没有额外信息（就是同一段正文的只读渲染），所以整层砍掉。
    MemoryCard(onDoubleClick = onClick) {
        MemoryCardBody(fact.content)
        MemoryCardMeta(
            fact.category to true,
            "${(fact.confidence * 100).toInt()}%" to false,
            date to false,
        )
    }
}

// ── Insights tab ─────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun InsightsTab(
    insights: List<InsightItem>,
    date: String,
    onDateChange: (String) -> Unit,
    onRefresh: () -> Unit,
) {
    var showDatePicker by remember { mutableStateOf(false) }
    val datePickerState = rememberDatePickerState()

    if (showDatePicker) {
        DatePickerDialog(
            onDismissRequest = { showDatePicker = false },
            confirmButton = {
                TextButton(onClick = {
                    showDatePicker = false
                    datePickerState.selectedDateMillis?.let { millis ->
                        onDateChange(isoFromUtcMillis(millis))
                    }
                }) { Text("确定") }
            },
            dismissButton = {
                TextButton(onClick = { showDatePicker = false }) { Text("取消") }
            },
        ) {
            DatePicker(state = datePickerState)
        }
    }

    Column(Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.weight(1f).clickable { showDatePicker = true }
                    .clip(MaterialTheme.shapes.small)
                    .background(MaterialTheme.colorScheme.surfaceContainerLow)
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Icon(Icons.Default.CalendarToday, contentDescription = "选择日期", tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(
                    text = date.ifBlank { "全部日期" },
                    style = MaterialTheme.typography.bodyLarge,
                    color = if (date.isBlank()) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface,
                )
            }
            if (date.isNotBlank()) {
                TextButton(onClick = { onDateChange("") }) { Text("清除") }
            }
            IconButton(onClick = onRefresh) {
                Icon(Icons.Default.Refresh, contentDescription = "刷新")
            }
        }
        if (insights.isEmpty()) {
            EthanEmptyState(
                title = "还没有永久记忆",
                description = "Ethan 会把重要的事记在这里",
                icon = Icons.Default.Psychology,
            )
            return@Column
        }
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            items(insights, key = { it.id }) { item ->
                InsightCard(item)
            }
        }
    }
}

@Composable
private fun InsightCard(item: InsightItem) {
    // metadata 里 date/importance 是 JsonElement，`.toString()` 会带引号
    // （`"2026-09-13"`），直接显示很难看 —— 统一 trim('"')。
    val dateVal = remember(item.metadata) {
        item.metadata["date"]?.toString()?.trim('"').orEmpty()
    }
    val importance = remember(item.metadata) {
        item.metadata["importance"]?.toString()?.trim('"').orEmpty()
    }

    MemoryCard {
        MemoryCardBody(item.text, maxLines = 6)
        MemoryCardMeta(
            dateVal to false,
            (if (importance.isNotBlank()) "重要度 $importance" else "") to false,
        )
    }
}

// ── Procedures tab ───────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ProceduresTab(
    procedures: List<Procedure>,
    onEdit: (Procedure) -> Unit,
    onDelete: (String) -> Unit,
) {
    if (procedures.isEmpty()) {
        EthanEmptyState(
            title = "暂无流程记忆",
            description = "Ethan 从你的纠正里学到的行为准则会记在这里",
            icon = Icons.Default.Psychology,
        )
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        // 顶部只留 8dp（原本四边都是 16dp）—— tab 栏刚结束，再垫 16dp 显得中间空了
        // 一段。左右和底部保持 16dp。
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        items(procedures, key = { it.id }) { proc ->
            var showDeleteConfirm by remember { mutableStateOf(false) }
            if (showDeleteConfirm) {
                AlertDialog(
                    onDismissRequest = { showDeleteConfirm = false },
                    title = { Text("删除这条流程？") },
                    text = { Text("删除后无法恢复。") },
                    confirmButton = {
                        TextButton(onClick = { showDeleteConfirm = false; onDelete(proc.id) }) { Text("删除") }
                    },
                    dismissButton = {
                        TextButton(onClick = { showDeleteConfirm = false }) { Text("取消") }
                    },
                )
            }
            val dismissState = rememberSwipeToDismissBoxState(
                confirmValueChange = { value ->
                    if (value == SwipeToDismissBoxValue.EndToStart) {
                        showDeleteConfirm = true
                    }
                    false
                },
            )
            val date = remember(proc.createdAt) { formatEpochDate(proc.createdAt) }
            SwipeToDismissBox(
                state = dismissState,
                backgroundContent = {
                    // 圆角必须和卡片一致（`EthanCard` 用 shapes.large）。
                    // 之前这里写的是 shapes.small，比卡片更「方」—— 滑动手势没发生、
                    // 卡片静止时，背景在卡片四个圆角处会露出一点点，看着像卡片带了
                    // 一圈随机颜色的描边（流程 tab 上表现为粉色边）。
                    Box(
                        Modifier
                            .fillMaxSize()
                            .clip(MaterialTheme.shapes.large)
                            .background(MaterialTheme.colorScheme.errorContainer)
                            .padding(horizontal = 20.dp),
                        contentAlignment = Alignment.CenterEnd,
                    ) {
                        Icon(Icons.Default.Delete, contentDescription = "删除", tint = MaterialTheme.colorScheme.onErrorContainer)
                    }
                },
                enableDismissFromStartToEnd = false,
            ) {
                // 双击进编辑，与另外两个 tab 一致（单击不做事 —— 流程卡片以前
                // 完全没有编辑入口，现在给了入口就要避免误触）。
                MemoryCard(onDoubleClick = { onEdit(proc) }) {
                    MemoryCardBody(proc.rule, maxLines = 4)
                    MemoryCardMeta(
                        "命中 ${proc.hitCount} 次" to false,
                        date to false,
                    )
                }
            }
        }
    }
}

// ── Records tab ──────────────────────────────────────────────────────────────

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RecordsTab(
    records: List<StructuredRecord>,
    filter: RecordsFilter,
    search: String,
    onFilterChange: (RecordsFilter) -> Unit,
    onSearchChange: (String) -> Unit,
    onEdit: (StructuredRecord) -> Unit,
    onConfirm: (String) -> Unit,
    onDelete: (String) -> Unit,
) {
    val chipsScrollState = rememberScrollState()
    val listState = rememberLazyListState()

    val statuses = listOf(
        null to "全部", "pending" to "候选",
        "confirmed" to "已确认", "superseded" to "已替代",
    )

    // 筛选 chips + 搜索框都是**列表的开头两项**，跟着内容一起滑走。
    // 和「事实」tab 同一套做法，理由见 FactsListContent 上方的注释 ——
    // 核心就一句：不改变列表视口高度，就不会和用户的滚动位置打架。
    LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item(key = "__chips__") {
            Row(
                modifier = Modifier.fillMaxWidth().horizontalScroll(chipsScrollState),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                statuses.forEach { (value, label) ->
                    FilterChip(
                        selected = filter.status == value,
                        onClick = { onFilterChange(filter.copy(status = value)) },
                        label = { Text(label) },
                    )
                }
            }
        }

        item(key = "__search__") {
            SearchField(
                value = search,
                onValueChange = onSearchChange,
                placeholder = "搜索记录…",
            )
        }

        if (records.isEmpty()) {
            item(key = "__empty__") {
                Box(
                    Modifier.fillMaxWidth().padding(top = 48.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text("暂无结构化记忆", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        } else {
            items(records, key = { it.id }) { record ->
                RecordCard(
                    record = record,
                    onEdit = { onEdit(record) },
                    onConfirm = { onConfirm(record.id) },
                    onDelete = { onDelete(record.id) },
                )
            }
        }
    }
}

@Composable
private fun RecordCard(
    record: StructuredRecord,
    onEdit: () -> Unit,
    onConfirm: () -> Unit,
    onDelete: () -> Unit,
) {
    var showDeleteConfirm by remember { mutableStateOf(false) }
    if (showDeleteConfirm) {
        AlertDialog(
            onDismissRequest = { showDeleteConfirm = false },
            title = { Text("删除这条记录？") },
            confirmButton = {
                TextButton(onClick = { showDeleteConfirm = false; onDelete() }) { Text("删除") }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteConfirm = false }) { Text("取消") }
            },
        )
    }

    MemoryCard(onDoubleClick = onEdit) {
        Row(verticalAlignment = Alignment.Top) {
            Box(Modifier.weight(1f)) {
                MemoryCardBody(record.content)
            }
            // 删除按钮压到卡片右上角并收紧内边距 —— IconButton 自带 48dp 命中区，
            // 不收缩的话它会替正文让出一大块空白。
            IconButton(
                onClick = { showDeleteConfirm = true },
                modifier = Modifier.size(32.dp).offset(y = (-4).dp),
            ) {
                Icon(
                    Icons.Default.Delete,
                    contentDescription = "删除",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(18.dp),
                )
            }
        }

        RecordMetaRow(record)

        if (record.status == "pending") {
            TextButton(
                onClick = onConfirm,
                modifier = Modifier.align(Alignment.End).offset(y = 4.dp),
            ) {
                Icon(Icons.Default.Check, contentDescription = null, modifier = Modifier.size(16.dp))
                Text("确认", modifier = Modifier.padding(start = 4.dp))
            }
        }
    }
}

@Composable
private fun RecordMetaRow(record: StructuredRecord) {
    // 状态用中文：后端给的是 active/pending/superseded，直接显示英文很突兀。
    val statusLabel = remember(record.status) {
        when (record.status) {
            "active" -> "生效"
            "pending" -> "候选"
            "confirmed" -> "已确认"
            "superseded" -> "已替代"
            "expired" -> "已过期"
            "disputed" -> "冲突"
            "" -> ""
            else -> record.status
        }
    }
    val date = remember(record.createdAt) { formatEpochDate(record.createdAt) }

    // 一行装不下就换行（FlowRow），免得长类型名把后面的置信度挤出去。
    // 四个 tab 的元信息行统一用 MemoryCardMeta 的字号与配色。
    MemoryCardMeta(
        record.memoryType to true,
        statusLabel to false,
        "置信度 ${(record.confidence * 100).toInt()}%" to false,
        "重要度 ${(record.importance * 100).toInt()}%" to false,
        date to false,
    )
}

// ── Summaries dialog ─────────────────────────────────────────────────────────

/**
 * Material3 日期选择器给的是 **UTC 当天 00:00 的毫秒**（`selectedDateMillis`、
 * `SelectableDates.isSelectableDate` 都是这个语义），所以换算必须用 [ZoneOffset.UTC]。
 *
 * 以前这里用 `SimpleDateFormat(..., Locale.getDefault())` 格式化，在东八区碰巧没事
 * （UTC 00:00 → 本地 08:00，还是同一天），但在西半球会整体退回前一天 ——
 * 用户选 9/13，筛出来的是 9/12 的摘要。
 */
private fun isoFromUtcMillis(millis: Long): String =
    Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate().toString()

/** [isoFromUtcMillis] 的反向：让已选日期在日历上正确高亮。格式非法时返回 null。 */
private fun utcMillisFromIso(iso: String): Long? =
    if (iso.isBlank()) null
    else runCatching {
        LocalDate.parse(iso).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
    }.getOrNull()

/**
 * 只让「有日摘要的日子」可选，其余置灰。
 *
 * Material3 的 `DatePicker` 没有「在指定日期上画点」的 API，所以「标注哪些天有内容」
 * 只能靠置灰实现 —— 效果上等价：用户一眼就能看出哪些格子能点。
 *
 * 集合用 `mutableStateOf` 持有而不是普通 `var`：日期全集是异步拉回来的，
 * 晚到时读它的 `DatePicker` 需要感知到变化才会重算格子。
 */
@OptIn(ExperimentalMaterial3Api::class)
private class SummaryDatesSelectable(initial: Set<String>) : SelectableDates {
    private var dates by mutableStateOf(initial)

    fun update(newDates: Set<String>) { dates = newDates }

    override fun isSelectableDate(utcTimeMillis: Long): Boolean {
        // 空集合 = 还没拉到（或确实一条摘要都没有）。此时全放开，
        // 否则接口一挂整个日历就锁死了，用户连"全部日期"都回不去。
        if (dates.isEmpty()) return true
        return dates.contains(isoFromUtcMillis(utcTimeMillis))
    }

    override fun isSelectableYear(year: Int): Boolean = true
}

/**
 * 日摘要弹窗。
 *
 * 之前是把后端的原始 JSON 直接 `toString().take(200)` 丢进文本框 —— 用户看到的是
 * `{"id":"daily_67278c41...","user_id":"","pipeline_version":"v1",...}` 这种串，
 * 连 `id` 和 `user_id` 都在里面，而且 `\n` 是转义的、正文被 200 字硬截断。
 *
 * 对齐 Web 的 `DailySummaryCard`（`web/components/memory-view.tsx:194`）：
 * 每张卡显示「领域徽章 + 本地日期 + pipeline 版本」，正文用 Markdown 渲染。
 * 同时按用户要求**放宽弹窗**，正文占满可用宽度。
 *
 * 字段是从 `JsonElement` 里按 key 取的（后端返回的是自由 JSON），取不到就不显示。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SummariesDialog(
    summaries: List<JsonElement>,
    date: String,
    summaryDates: Set<String>,
    datesTruncated: Boolean,
    loading: Boolean,
    hasMore: Boolean,
    onDateChange: (String) -> Unit,
    onLoadMore: () -> Unit,
    onDismiss: () -> Unit,
) {
    var showDatePicker by remember { mutableStateOf(false) }
    // 同一个实例跨重组复用（否则每次重组新建一个，等于重置）。
    // 日期全集是异步到的（弹窗先显示、数据后到），所以要把它同步进 selectable。
    //
    // ⚠️ 必须用 rememberUpdatedState 包一层，不能直接 `snapshotFlow { summaryDates }`：
    // `summaryDates` 是普通入参而不是 Compose 的 State，snapshotFlow 只跟踪快照对象里
    // State 的读取，读普通参数捕获不到任何东西 —— flow 只会发一次初值就不动了，
    // 等于把「弹窗开着、数据后到」这条路彻底堵死。包成 State 之后 snapshotFlow 读的是
    // `summaryDatesState.value`，写入走快照观察链，DatePicker 里读 selectable 的格子
    // 才会重算。（同款写法见 ChatScreen.kt 的 snapshotFlow { isAtBottom }。）
    val summaryDatesState = rememberUpdatedState(summaryDates)
    val selectable = remember { SummaryDatesSelectable(summaryDates) }
    LaunchedEffect(selectable) {
        snapshotFlow { summaryDatesState.value }
            .distinctUntilChanged()
            .collect { selectable.update(it) }
    }
    // usePlatformDefaultWidth = false 是关键：Compose 的 Dialog 默认会被平台约束到
    // 一个较窄的宽度（约屏宽 80% 再减去系统边距），光在内容里写 fillMaxWidth() 是
    // 撑不开的 —— 这正是「弹窗不够宽、正文挤成窄条」的原因。
    // 日期选择：Web 端是 `daily` 页签上放一个 `<input type="date">`（memory-view.tsx:365），
    // 这里做成弹窗里的一行，语义等价 —— 选一天只看那天的摘要，清空回到全部。
    if (showDatePicker) {
        // state 建在 if 里而不是外层：`rememberDatePickerState` 只在首次组合时读一次
        // `selectableDates`，建在外层的话，「在日期全集到达前打开过一次」就会把空的
        // 可选集合永久捕获住，之后日历怎么都不置灰。放进 if 后每次打开都是全新 state。
        val datePickerState = rememberDatePickerState(
            initialSelectedDateMillis = utcMillisFromIso(date),
            selectableDates = selectable,
        )
        DatePickerDialog(
            onDismissRequest = { showDatePicker = false },
            confirmButton = {
                TextButton(onClick = {
                    showDatePicker = false
                    datePickerState.selectedDateMillis?.let { millis ->
                        onDateChange(isoFromUtcMillis(millis))
                    }
                }) { Text("确定") }
            },
            dismissButton = {
                TextButton(onClick = { showDatePicker = false }) { Text("取消") }
            },
        ) {
            DatePicker(state = datePickerState)
        }
    }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogPropertiesCompat.wide,
    ) {
        Surface(
            modifier = Modifier.fillMaxWidth().fillMaxHeight(0.88f).padding(horizontal = 12.dp),
            shape = MaterialTheme.shapes.large,
            color = MaterialTheme.colorScheme.surface,
        ) {
            Column(Modifier.fillMaxSize()) {
                Text(
                    "日摘要",
                    style = MaterialTheme.typography.titleLarge,
                    modifier = Modifier.padding(start = 20.dp, end = 20.dp, top = 18.dp, bottom = 6.dp),
                )

                // 日期行：点整条开系统日期选择器；有日期时右侧出现「清除」。
                // 样式与 InsightsTab 的日期条保持一致（同样的底色和圆角），
                // 同一个 App 里两处「按日期筛选」不该长得不一样。
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 2.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Row(
                        modifier = Modifier
                            .weight(1f)
                            .clip(MaterialTheme.shapes.small)
                            .background(MaterialTheme.colorScheme.surfaceContainerLow)
                            .clickable { showDatePicker = true }
                            .padding(horizontal = 12.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Icon(
                            Icons.Default.CalendarToday,
                            contentDescription = "选择日期",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(18.dp),
                        )
                        Text(
                            text = date.ifBlank { "全部日期" },
                            style = MaterialTheme.typography.bodyMedium,
                            color = if (date.isBlank()) MaterialTheme.colorScheme.onSurfaceVariant
                            else MaterialTheme.colorScheme.onSurface,
                        )
                    }
                    if (date.isNotBlank()) {
                        TextButton(onClick = { onDateChange("") }) { Text("清除") }
                    }
                }
                // 说明「灰格子 = 那天没有摘要」。不给提示的话，用户会以为日历坏了。
                // 只在确实拿到了日期全集时显示：空集合代表还没拉到或真的一条都没有，
                // 那时日历是全放开的，这句话就不成立了。
                // 若日期集被后端上限截断（还有更早的没返回），要额外说明 —— 否则用户
                // 会以为更早的那些灰格子也是「没内容」，其实只是没拉回来。
                if (summaryDates.isNotEmpty()) {
                    Text(
                        text = if (datesTruncated) "灰色日期没有日摘要；更早的日期未加载" else "灰色日期没有日摘要",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        // 左侧对齐日期条的图标（日期条 padding 12dp + 图标前 12dp），
                        // 下方留 10dp：列表的 contentPadding 只有 2dp，不留白的话
                        // 这行字会贴着第一张卡片的顶边。
                        modifier = Modifier.padding(start = 24.dp, top = 2.dp, bottom = 10.dp),
                    )
                }

                when {
                    // 切日期时先转圈，不要先闪一下「暂无日摘要」再出内容 —— 那是两帧假信息
                    loading && summaries.isEmpty() -> LoadingBox()
                    summaries.isEmpty() -> {
                        Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                            Text(
                                if (date.isBlank()) "暂无日摘要" else "$date 没有日摘要",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    else -> {
                        val listState = rememberLazyListState()
                        // 滚到接近底部就预拉下一页。用 derivedStateOf 包一层，
                        // 否则每帧滚动都会重算并触发重组。
                        val nearEnd by remember(summaries.size, hasMore) {
                            derivedStateOf {
                                val last = listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0
                                hasMore && last >= summaries.size - 2
                            }
                        }
                        LaunchedEffect(nearEnd) {
                            if (nearEnd) onLoadMore()
                        }
                        LazyColumn(
                            state = listState,
                            modifier = Modifier.weight(1f),
                            // 左右只留 12dp、不用 16dp：这是全屏宽的弹窗，
                            // 正文段落希望尽量宽（用户明确要求）。
                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 2.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            items(summaries) { item -> DailySummaryCard(item) }
                            if (hasMore) {
                                item {
                                    Box(
                                        Modifier.fillMaxWidth().padding(vertical = 12.dp),
                                        contentAlignment = Alignment.Center,
                                    ) {
                                        CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                                    }
                                }
                            }
                        }
                    }
                }

                // 关闭按钮固定在弹窗底部，底下压一条分隔线。
                // 之前按钮和列表之间没有任何视觉区隔，正文滚到底时最后一行的字
                // 正好贴着按钮，看起来像文字被按钮盖住了。
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f))
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
                    horizontalArrangement = Arrangement.End,
                ) {
                    TextButton(onClick = onDismiss) { Text("关闭") }
                }
            }
        }
    }
}

/**
 * 从自由 JSON 里取字符串字段，取不到返回空串。
 *
 * 用 `JsonPrimitive.content` 而**不是** `toString()`：`toString()` 会把字符串
 * 重新按 JSON 编码一次，里面的真换行（0x0A）就变回字面量 `\n` 两个字符了。
 * 摘要正文是多行的（`## 标题\n- 列表项`），经 `toString()` 之后就变成整段挤在
 * 一行、末尾挂着一串 `\n` —— 用户在「日摘要」弹窗里看到的乱码就是这个。
 * `content` 直接拿解码后的原始字符串，换行保持为真换行。
 *
 * 注意 `JsonNull` 要先于 `JsonPrimitive` 判断，否则会取到 "null"。
 */
private fun JsonElement.str(key: String): String {
    val value = (this as? JsonObject)?.get(key) ?: return ""
    if (value is JsonNull) return ""
    return (value as? JsonPrimitive)?.contentOrNull ?: ""
}

/**
 * 宽屏对话框属性：`usePlatformDefaultWidth = false` 才能让内容自己决定宽度。
 */
private object DialogPropertiesCompat {
    val wide = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false)
}

@Composable
private fun DailySummaryCard(item: JsonElement) {
    val domain = remember(item) { item.str("memory_domain") }
    val localDate = remember(item) { item.str("local_date") }
    val pipeline = remember(item) { item.str("pipeline_version") }
    // 后端字段名是 summary_text，也见过直接叫 summary 的，两个都试一下。
    val body = remember(item) {
        item.str("summary_text").ifBlank { item.str("summary") }
    }

    MemoryCard {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            // 领域徽章（对齐 Web 的 Badge：companion → 苏念，其余 → 普通）
            if (domain.isNotBlank()) {
                Surface(
                    shape = MaterialTheme.shapes.extraSmall,
                    color = if (domain == "companion") MaterialTheme.colorScheme.secondaryContainer
                    else MaterialTheme.colorScheme.primaryContainer,
                ) {
                    Text(
                        text = if (domain == "companion") "苏念" else "普通",
                        modifier = Modifier.padding(horizontal = 7.dp, vertical = 2.dp),
                        style = MaterialTheme.typography.labelSmall,
                        color = if (domain == "companion") MaterialTheme.colorScheme.onSecondaryContainer
                        else MaterialTheme.colorScheme.onPrimaryContainer,
                    )
                }
            }
            if (localDate.isNotBlank()) {
                Text(
                    localDate,
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }

        if (body.isBlank()) {
            Text("（空）", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            // Markdown 渲染：后端正文是 `## 活动\n- xxx` 这种，直接当纯文本显示
            // 会带一堆 `##` 和字面 `\n`。
            SimpleMarkdown(text = body, modifier = Modifier.fillMaxWidth())
        }

        if (pipeline.isNotBlank()) {
            Text(
                "pipeline $pipeline",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
            )
        }
    }
}

// ── Shared ────────────────────────────────────────────────────────────────────

/**
 * 四个 tab 的列表卡片统一走这一层。
 *
 * 之前每个 tab 各写各的 `Card`：事实带 🧠 头像 + `outlineVariant.copy(alpha=.3)` 描边，
 * 流程没有描边、结构化记忆又用了 `elevation = 1.dp`，看起来像四拨人做的。这里收敛成
 * 一个 `EthanCard` + 统一的 `columns` 文案列，只有「正文怎么排」由调用方决定。
 *
 * **双击进编辑，单击不响应**：卡片上原本单击 = 进编辑（结构化记忆）或进详情页
 * （事实），手指在列表里滑一下就误进了编辑页，反馈很强烈。双击是「明确要改」的
 * 手势，误触率低得多；长按留给引用/菜单之类的扩展。
 *
 * 实现说明：`EthanCard(onClick=…)` 走的是 M3 `Card` 的 clickable，吃不到「双击」，
 * 所以这里自己用 `detectTapGestures(onDoubleTap=…)`。**不加 `indication`** —— 单击
 * 不做事时给涟漪反而让人以为点中了。
 */
@Composable
private fun MemoryCard(
    onDoubleClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val tapModifier = if (onDoubleClick != null) {
        Modifier.pointerInput(onDoubleClick) {
            detectTapGestures(onDoubleTap = { onDoubleClick() })
        }
    } else {
        Modifier
    }
    EthanCard {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .then(tapModifier)
                .padding(horizontal = 14.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
            content = content,
        )
    }
}

/**
 * 正文行 —— 四个 tab 的卡片主体统一用它，行高一致。
 *
 * @param maxLines 列表里限行避免一张卡撑满屏；详情页传 null 不截断
 */
@Composable
private fun MemoryCardBody(text: String, maxLines: Int? = 3) {
    Text(
        text = text,
        style = MaterialTheme.typography.bodyLarge,
        maxLines = maxLines ?: Int.MAX_VALUE,
        overflow = TextOverflow.Ellipsis,
        lineHeight = MaterialTheme.typography.bodyLarge.lineHeight,
    )
}

/** 四个 tab 卡片底部的元信息行：chip + 若干灰字，统一间距与字号。 */
@Composable
private fun MemoryCardMeta(vararg parts: Pair<String, Boolean>) {
    // parts: (文案, 是否用 primary 色) —— 第一个通常是记忆类型，用 primary 强调
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        parts.filter { it.first.isNotBlank() }.forEach { (label, primary) ->
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = if (primary) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

/**
 * `created_at`（秒）→ `yyyy-MM-dd`。0/负数返回空串，UI 侧据此不渲染。
 *
 * 注意 `EpochSecondsSerializer` 已把各种输入归一成**秒**，所以这里统一 ×1000 给 `Date`。
 */
private fun formatEpochDate(seconds: Long): String =
    if (seconds > 0) SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date(seconds * 1000))
    else ""

@Composable
private fun MetaChip(label: String) {
    Surface(shape = MaterialTheme.shapes.small, color = MaterialTheme.colorScheme.secondaryContainer) {
        Text(
            label,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSecondaryContainer,
        )
    }
}
