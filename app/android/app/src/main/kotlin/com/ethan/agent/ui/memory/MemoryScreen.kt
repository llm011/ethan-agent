package com.ethan.agent.ui.memory

import com.ethan.agent.shared.viewmodel.MemoryUiState
import com.ethan.agent.shared.viewmodel.FactItem
import com.ethan.agent.shared.viewmodel.MemoryTab
import com.ethan.agent.shared.viewmodel.RecordsFilter
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
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
    onDismissFactEditor: () -> Unit,
    onEditChange: (String) -> Unit,
    onSaveFact: () -> Unit,
    onDeleteFact: (String) -> Unit,
    onDeleteProcedure: (String) -> Unit,
    onClearError: () -> Unit,
    onBack: () -> Unit = {},
    // new
    onInsightsDateChange: (String) -> Unit = {},
    onRefreshInsights: () -> Unit = {},
    onRecordsFilterChange: (RecordsFilter) -> Unit = {},
    onRecordsSearchChange: (String) -> Unit = {},
    onSelectRecord: (StructuredRecord) -> Unit = {},
    onDismissRecord: () -> Unit = {},
    onRecordEditContent: (String) -> Unit = {},
    onSaveRecord: () -> Unit = {},
    onDeleteRecord: (String) -> Unit = {},
    onConfirmRecord: (String) -> Unit = {},
    onConsolidate: () -> Unit = {},
    onConsolidateRecords: () -> Unit = {},
    onLoadSummaries: () -> Unit = {},
    onHideSummaries: () -> Unit = {},
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
        SummariesDialog(summaries = state.summaries, onDismiss = onHideSummaries)
    }

    // Fact editor overlay
    val selectedFact = state.selectedFact
    if (selectedFact != null && state.tab == MemoryTab.Facts) {
        FactEditorScreen(
            fact = selectedFact,
            content = state.editContent,
            onBack = onDismissFactEditor,
            onContentChange = onEditChange,
            onSave = onSaveFact,
            onDelete = { state.selectedFactIndex?.let(onDeleteFact) },
        )
        return
    }

    // Record editor overlay
    val selectedRecord = state.selectedRecord
    if (selectedRecord != null && state.tab == MemoryTab.Records) {
        RecordEditorScreen(
            record = selectedRecord,
            content = state.recordEditContent,
            onBack = onDismissRecord,
            onContentChange = onRecordEditContent,
            onSave = onSaveRecord,
            onDelete = { onDeleteRecord(selectedRecord.id) },
        )
        return
    }

    var factsSearchQuery by remember { mutableStateOf("") }

    // 「事实」tab 搜索框的收起状态：往下滑收起（tab 栏右侧出现小放大镜），
    // 往上滑或回到顶部再展开。收起只在事实 tab 有意义，切 tab 时复位。
    var factsSearchCollapsed by remember { mutableStateOf(false) }
    var factsSearchForcedOpen by remember { mutableStateOf(false) }

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
                onTabSelected = { tab ->
                    // 切 tab 时把搜索框复位成展开 —— 在别的 tab 收起的图标
                    // 带过来会让人以为「事实」页的搜索没了。
                    factsSearchCollapsed = false
                    onTabChange(tab)
                },
                labelOf = { it.title },
                action = if (state.tab == MemoryTab.Facts && factsSearchCollapsed) {
                    {
                        // 收起后搜索的入口挪到这儿：点一下展开并把焦点留在搜索框上
                        IconButton(onClick = { factsSearchForcedOpen = true }) {
                            Icon(
                                Icons.Default.Search,
                                contentDescription = "搜索",
                                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                } else null,
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
                    collapsed = factsSearchCollapsed && !factsSearchForcedOpen,
                    onCollapsedChange = { collapsed ->
                        factsSearchCollapsed = collapsed
                        // 用户手动点开搜索后，别让「强制展开」标记永久压着滚动折叠，
                        // 下一次下滑仍应能收起。
                        if (collapsed) factsSearchForcedOpen = false
                    },
                )
                MemoryTab.Insights -> InsightsTab(
                    insights = state.insights,
                    date = state.insightsDate,
                    onDateChange = onInsightsDateChange,
                    onRefresh = onRefreshInsights,
                )
                MemoryTab.Procedures -> ProceduresTab(state.procedures, onDeleteProcedure)
                MemoryTab.Records -> RecordsTab(
                    records = state.records,
                    filter = state.recordsFilter,
                    search = state.recordsSearch,
                    onFilterChange = onRecordsFilterChange,
                    onSearchChange = onRecordsSearchChange,
                    onSelect = onSelectRecord,
                    onConfirm = onConfirmRecord,
                    onDelete = onDeleteRecord,
                )
            }
        }
    }
}

// ── Fact editor ──────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun FactEditorScreen(
    fact: Fact,
    content: String,
    onBack: () -> Unit,
    onContentChange: (String) -> Unit,
    onSave: () -> Unit,
    onDelete: () -> Unit,
) {
    var showDeleteConfirm by remember { mutableStateOf(false) }
    // 默认预览模式，点编辑才进入编辑模式
    var isEditing by remember { mutableStateOf(false) }

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

    EthanScaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (isEditing) "编辑事实" else "事实详情") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { showDeleteConfirm = true }) {
                        Icon(Icons.Default.Delete, contentDescription = "删除")
                    }
                    if (isEditing) {
                        TextButton(onClick = { isEditing = false; onSave() }) {
                            Text("保存", fontWeight = FontWeight.SemiBold)
                        }
                    } else {
                        IconButton(onClick = { isEditing = true }) {
                            Icon(Icons.Default.Edit, contentDescription = "编辑")
                        }
                    }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).imePadding()) {
            FlowRow(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                MetaChip(fact.category.ifBlank { "knowledge" })
                MetaChip("置信度 ${(fact.confidence * 100).toInt()}%")
                if (fact.source.isNotBlank()) MetaChip("来源 ${fact.source.take(12)}")
            }
            if (isEditing) {
                OutlinedTextField(
                    value = content,
                    onValueChange = onContentChange,
                    modifier = Modifier.fillMaxWidth().weight(1f).padding(horizontal = 16.dp),
                    placeholder = { Text("输入记忆内容，支持 Markdown") },
                    textStyle = MaterialTheme.typography.bodyLarge,
                )
            } else {
                // 预览模式：Markdown 渲染，可滚动
                Box(
                    Modifier
                        .fillMaxWidth()
                        .weight(1f)
                        .verticalScroll(rememberScrollState())
                        .padding(horizontal = 16.dp),
                ) {
                    SimpleMarkdown(
                        text = content.ifBlank { "*暂无内容*" },
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }
    }
}

// ── Record editor ────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RecordEditorScreen(
    record: StructuredRecord,
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
            title = { Text("删除这条记录？") },
            text = { Text("删除后无法恢复。") },
            confirmButton = {
                TextButton(onClick = { showDeleteConfirm = false; onDelete() }) { Text("删除") }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteConfirm = false }) { Text("取消") }
            },
        )
    }

    EthanScaffold(
        topBar = {
            TopAppBar(
                title = { Text("编辑记录") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { showDeleteConfirm = true }) {
                        Icon(Icons.Default.Delete, contentDescription = "删除")
                    }
                    TextButton(onClick = onSave) { Text("保存", fontWeight = FontWeight.SemiBold) }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).imePadding()
        ) {
            OutlinedTextField(
                value = content,
                onValueChange = onContentChange,
                modifier = Modifier.fillMaxWidth().padding(16.dp),
                label = { Text("内容") },
                minLines = 4,
            )
            RecordMetaRow(record)
        }
    }
}

// ── Facts tab ────────────────────────────────────────────────────────────────

@Composable
private fun FactsListContent(
    facts: List<FactItem>,
    searchQuery: String,
    onSearchChange: (String) -> Unit,
    onSelect: (FactItem) -> Unit,
    /** 列表是否已下滑到底 —— true 时把搜索框收起来，只留 tab 栏右侧的小图标。 */
    collapsed: Boolean = false,
    onCollapsedChange: (Boolean) -> Unit = {},
) {
    val listState = rememberLazyListState()

    // 滚动方向驱动的收起/展开。
    //
    // 判定用「当前可见项」而不是 `listState.isScrollInProgress` + 累计位移 ——
    // 后者在 fling 时方向会抖，搜索框会跟着抽。
    // 规则：滑过第一项（正在看列表深处）就收起；回到顶部附近就展开。
    LaunchedEffect(listState) {
        snapshotFlow {
            val info = listState.layoutInfo
            val firstVisible = info.visibleItemsInfo.firstOrNull()
                ?: return@snapshotFlow false
            // 首项整体已滚出屏幕上方 → 视为「在看后面」
            firstVisible.index > 0 || firstVisible.offset < -24
        }
            .distinctUntilChanged()
            .collect { scrolledPastTop -> onCollapsedChange(scrolledPastTop) }
    }

    Column(Modifier.fillMaxSize()) {
        // 搜索框：往下滑时收起。
        //
        // 用 AnimatedVisibility + shrink/expandVertically 而不是切换 height ——
        // 动画只影响这一行自身的高度，不碰 LazyColumn 的滚动位置，
        // 所以收起/展开时列表内容不会跳。
        AnimatedVisibility(
            visible = !collapsed,
            enter = expandVertically(animationSpec = tween(180)),
            exit = shrinkVertically(animationSpec = tween(180)),
        ) {
            OutlinedTextField(
                value = searchQuery,
                onValueChange = onSearchChange,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 6.dp),
                placeholder = { Text("搜索记忆，支持 Markdown...") },
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

        val filteredFacts = if (searchQuery.isBlank()) {
            facts
        } else {
            facts.filter { it.fact.content.contains(searchQuery, ignoreCase = true) }
        }

        if (filteredFacts.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(
                    if (searchQuery.isBlank()) "暂无事实记忆" else "未找到匹配的记忆",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            return@Column
        }

        LazyColumn(
            state = listState,
            modifier = Modifier.fillMaxSize(),
            // 上边距给 4dp：搜索框自己带了 6dp 的下边距，再叠 8dp 顶部会显空。
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            items(filteredFacts, key = { it.index }) { item ->
                FactListCard(item, onClick = { onSelect(item) })
            }
        }
    }
}

@Composable
private fun FactListCard(item: FactItem, onClick: () -> Unit) {
    val fact = item.fact
    val date = remember(fact.createdAt) { formatEpochDate(fact.createdAt) }

    // 不再放 🧠 头像：四个 tab 里只有它带头像，且 emoji 在深浅主题下
    // 渲染出来的观感飘忽（不是主题色、不跟随 tint）。正文直接从卡片左边起排，
    // 横向空间也让给了内容。
    MemoryCard(onClick = onClick) {
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
                        val formatted = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date(millis))
                        onDateChange(formatted)
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
private fun ProceduresTab(procedures: List<Procedure>, onDelete: (String) -> Unit) {
    if (procedures.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("暂无流程记忆", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
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
                MemoryCard {
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
    onSelect: (StructuredRecord) -> Unit,
    onConfirm: (String) -> Unit,
    onDelete: (String) -> Unit,
) {
    var searchVisible by remember { mutableStateOf(false) }
    val scrollState = rememberScrollState()

    Column(Modifier.fillMaxSize()) {
        // Top bar: filter chips (always visible) + search icon
        Row(
            modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 4.dp, bottom = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val statuses = listOf(null to "全部", "pending" to "候选", "confirmed" to "已确认", "superseded" to "已替代")
            Row(
                modifier = Modifier.weight(1f).horizontalScroll(scrollState),
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
            IconButton(onClick = { searchVisible = !searchVisible }, modifier = Modifier.size(40.dp)) {
                Icon(Icons.Default.Search, contentDescription = "搜索", modifier = Modifier.size(20.dp))
            }
        }

        // Search field (conditionally shown)
        AnimatedVisibility(visible = searchVisible) {
            OutlinedTextField(
                value = search,
                onValueChange = onSearchChange,
                modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 6.dp),
                placeholder = { Text("搜索记录…") },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                singleLine = true,
            )
        }

        if (records.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("暂无结构化记忆", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            return@Column
        }

        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            // 顶部间距收到 8dp。这里原本是「chips 行下边距 + Spacer(4dp) + 列表
            // contentPadding 16dp」三层叠加，卡片离筛选栏老远 —— 用户反馈的
            // 「离上方有点远、间距太大」就是这个。现在只留一层 8dp。
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            items(records, key = { it.id }) { record ->
                RecordCard(
                    record = record,
                    onSelect = { onSelect(record) },
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
    onSelect: () -> Unit,
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

    MemoryCard(onClick = onSelect) {
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
@Composable
private fun SummariesDialog(summaries: List<JsonElement>, onDismiss: () -> Unit) {
    // usePlatformDefaultWidth = false 是关键：Compose 的 Dialog 默认会被平台约束到
    // 一个较窄的宽度（约屏宽 80% 再减去系统边距），光在内容里写 fillMaxWidth() 是
    // 撑不开的 —— 这正是「弹窗不够宽、正文挤成窄条」的原因。
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
                    modifier = Modifier.padding(start = 20.dp, end = 20.dp, top = 18.dp, bottom = 10.dp),
                )

                if (summaries.isEmpty()) {
                    Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Text("暂无日摘要", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                } else {
                    LazyColumn(
                        modifier = Modifier.weight(1f),
                        // 左右只留 12dp、不用 16dp：这是全屏宽的弹窗，
                        // 正文段落希望尽量宽（用户明确要求）。
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 2.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        items(summaries) { item -> DailySummaryCard(item) }
                    }
                }

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
 * @param onClick 传了就有涟漪（列表项）；不传就是纯展示
 */
@Composable
private fun MemoryCard(
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    EthanCard(onClick = onClick) {
        Column(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
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
