package com.ethan.agent.ui.memory

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.CalendarToday
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Tune
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
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import com.ethan.agent.core.model.Fact
import com.ethan.agent.core.model.InsightItem
import com.ethan.agent.core.model.Procedure
import com.ethan.agent.core.model.StructuredRecord
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.EthanScrollableTabBar
import com.ethan.agent.ui.components.EthanTopBar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SimpleMarkdown
import com.ethan.agent.ui.components.SnackbarContainer
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlinx.serialization.json.JsonElement

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
            Surface(shape = RoundedCornerShape(16.dp)) {
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
    if (state.selectedFact != null && state.tab == MemoryTab.Facts) {
        FactEditorScreen(
            fact = state.selectedFact,
            content = state.editContent,
            onBack = onDismissFactEditor,
            onContentChange = onEditChange,
            onSave = onSaveFact,
            onDelete = { state.selectedFactIndex?.let(onDeleteFact) },
        )
        return
    }

    // Record editor overlay
    if (state.selectedRecord != null && state.tab == MemoryTab.Records) {
        RecordEditorScreen(
            record = state.selectedRecord,
            content = state.recordEditContent,
            onBack = onDismissRecord,
            onContentChange = onRecordEditContent,
            onSave = onSaveRecord,
            onDelete = { onDeleteRecord(state.selectedRecord.id) },
        )
        return
    }

    Scaffold(
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(bottom = padding.calculateBottomPadding())) {
            // 紧凑顶栏
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

            // 可横滑 Tab 栏
            EthanScrollableTabBar(
                tabs = MemoryTab.entries.toList(),
                selectedTab = state.tab,
                onTabSelected = onTabChange,
                labelOf = { it.title },
            )

            if (state.isLoading) {
                LoadingBox()
                return@Column
            }

            when (state.tab) {
                MemoryTab.Facts -> FactsList(state.facts, onSelectFact)
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

    Scaffold(
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

    Scaffold(
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
private fun FactsList(facts: List<FactItem>, onSelect: (FactItem) -> Unit) {
    if (facts.isEmpty()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("暂无事实记忆", style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        items(facts, key = { it.index }) { item ->
            FactListCard(item, onClick = { onSelect(item) })
        }
    }
}

@Composable
private fun FactListCard(item: FactItem, onClick: () -> Unit) {
    val fact = item.fact
    val date = remember(fact.createdAt) {
        if (fact.createdAt > 0) SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date(fact.createdAt * 1000))
        else ""
    }
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
    ) {
        Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(fact.content, style = MaterialTheme.typography.bodyLarge, maxLines = 3, overflow = TextOverflow.Ellipsis)
                Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (fact.category.isNotBlank()) {
                        Text(fact.category, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                    }
                    Text("${(fact.confidence * 100).toInt()}%", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (date.isNotBlank()) {
                        Text(date, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            Icon(Icons.Default.ChevronRight, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
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
                    .clip(RoundedCornerShape(8.dp))
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
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("暂无永久记忆", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            return@Column
        }
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
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
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(item.text, style = MaterialTheme.typography.bodyLarge)
            if (item.metadata.isNotEmpty()) {
                val dateVal = item.metadata["date"]?.toString()?.trim('"')
                val importance = item.metadata["importance"]?.toString()
                Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (!dateVal.isNullOrBlank()) {
                        Text(dateVal, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    if (!importance.isNullOrBlank()) {
                        Text("重要度 $importance", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
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
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
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
            SwipeToDismissBox(
                state = dismissState,
                backgroundContent = {
                    Box(
                        Modifier
                            .fillMaxSize()
                            .clip(RoundedCornerShape(12.dp))
                            .background(MaterialTheme.colorScheme.errorContainer)
                            .padding(horizontal = 20.dp),
                        contentAlignment = Alignment.CenterEnd,
                    ) {
                        Icon(Icons.Default.Delete, contentDescription = "删除", tint = MaterialTheme.colorScheme.onErrorContainer)
                    }
                },
                enableDismissFromStartToEnd = false,
            ) {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
                ) {
                    Column(Modifier.padding(16.dp)) {
                        Text(proc.rule, style = MaterialTheme.typography.bodyLarge)
                        Text(
                            "命中 ${proc.hitCount} 次",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 6.dp),
                        )
                    }
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
    var filtersExpanded by remember { mutableStateOf(false) }
    var searchVisible by remember { mutableStateOf(false) }
    val scrollState = rememberScrollState()

    Column(Modifier.fillMaxSize()) {
        // Top bar: filter chips (expandable) + fixed icons
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (filtersExpanded) {
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
            } else {
                Spacer(Modifier.weight(1f))
            }
            IconButton(onClick = { filtersExpanded = !filtersExpanded }) {
                Icon(Icons.Default.Tune, contentDescription = "筛选")
            }
            IconButton(onClick = { searchVisible = !searchVisible }) {
                Icon(Icons.Default.Search, contentDescription = "搜索")
            }
        }

        // Search field (conditionally shown)
        AnimatedVisibility(visible = searchVisible) {
            OutlinedTextField(
                value = search,
                onValueChange = onSearchChange,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
                placeholder = { Text("搜索记录…") },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                singleLine = true,
            )
        }

        Spacer(Modifier.height(4.dp))

        if (records.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("暂无结构化记忆", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            return@Column
        }

        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
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

    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onSelect),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                Column(Modifier.weight(1f)) {
                    Text(record.content, style = MaterialTheme.typography.bodyLarge, maxLines = 3, overflow = TextOverflow.Ellipsis)
                }
                IconButton(onClick = { showDeleteConfirm = true }) {
                    Icon(Icons.Default.Delete, contentDescription = "删除", tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }

            RecordMetaRow(record)

            if (record.status == "pending") {
                TextButton(onClick = onConfirm, modifier = Modifier.align(Alignment.End)) {
                    Icon(Icons.Default.Check, contentDescription = null)
                    Text("确认", modifier = Modifier.padding(start = 4.dp))
                }
            }
        }
    }
}

@Composable
private fun RecordMetaRow(record: StructuredRecord) {
    Row(
        Modifier.fillMaxWidth().padding(top = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (record.memoryType.isNotBlank()) {
            Text(record.memoryType, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
        }
        Text(record.status, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text("置信度 ${(record.confidence * 100).toInt()}%", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text("重要度 ${(record.importance * 100).toInt()}%", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

// ── Summaries dialog ─────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SummariesDialog(summaries: List<JsonElement>, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("日摘要") },
        text = {
            if (summaries.isEmpty()) {
                Text("暂无日摘要")
            } else {
                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(summaries) { item ->
                        Surface(shape = RoundedCornerShape(8.dp), tonalElevation = 2.dp) {
                            Text(
                                item.toString().take(200),
                                modifier = Modifier.padding(12.dp),
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("关闭") }
        },
    )
}

// ── Shared ────────────────────────────────────────────────────────────────────

@Composable
private fun MetaChip(label: String) {
    Surface(shape = RoundedCornerShape(8.dp), color = MaterialTheme.colorScheme.secondaryContainer) {
        Text(
            label,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSecondaryContainer,
        )
    }
}
