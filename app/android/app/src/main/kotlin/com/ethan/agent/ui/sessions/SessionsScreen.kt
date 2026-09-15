package com.ethan.agent.ui.sessions

import com.ethan.agent.shared.viewmodel.SessionsUiState
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.PushPin
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Surface
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import com.ethan.agent.core.model.SessionInfo
import com.ethan.agent.core.model.SummaryResponse
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer
import com.ethan.agent.ui.components.SourceBadge
import com.ethan.agent.ui.components.EthanTopBar
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// All source chips shown in filter bar。
// 心跳/定时不算「来源」—— 它们是类别（web all-sessions-view 的 categoryFilter），
// 用下面这排排他类别 chip 承接；之前混在来源里且把后端值拼成 "scheduled"
// （实际是 "schedule"），筛选永远不生效。
private val ALL_SOURCE_CHIPS = listOf("web", "lark", "repl", "desktop", "wechat")

// 类别筛选（排他）：「全部对话」默认排除定时/心跳，与 web all-sessions-view 一致
private val CATEGORY_CHIPS = listOf(
    "全部对话" to "",
    "定时任务对话" to "scheduled",
    "心跳对话" to "heartbeat",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SessionsScreen(
    state: SessionsUiState,
    onQueryChange: (String) -> Unit,
    onSessionClick: (String) -> Unit,
    onRename: (SessionInfo) -> Unit,
    onRenameTextChange: (String) -> Unit,
    onConfirmRename: () -> Unit,
    onCancelRename: () -> Unit,
    onDelete: (String) -> Unit,
    onClearError: () -> Unit,
    onRegenTitle: (String) -> Unit,
    onSummary: (String) -> Unit,
    onDismissSummary: () -> Unit,
    onSetSourceFilter: (String) -> Unit = {},
    onToggleCategory: (String) -> Unit = {},
    onToggleSource: (String) -> Unit = {},
    onSelectAllSources: () -> Unit = {},
    onTogglePin: (SessionInfo) -> Unit = {},
    onBack: () -> Unit = {},
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    state.renameTarget?.let {
        AlertDialog(
            onDismissRequest = onCancelRename,
            title = { Text("重命名对话") },
            text = {
                OutlinedTextField(
                    value = state.renameText,
                    onValueChange = onRenameTextChange,
                    modifier = Modifier.fillMaxWidth(),
                )
            },
            confirmButton = { TextButton(onClick = onConfirmRename) { Text("保存") } },
            dismissButton = { TextButton(onClick = onCancelRename) { Text("取消") } },
        )
    }

    state.summarySheet?.let { summary ->
        SummaryBottomSheet(summary = summary, onDismiss = onDismissSummary)
    }

    var searchExpanded by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            // 标准 EthanTopBar（返回 | 标题 | 搜索），与设置/文档等子页一致。
            // 之前返回键挤在来源筛选行里、外面还套了张带描边的卡片，层级很怪 ——
            // 现在顶栏归顶栏，类别/来源筛选平铺在顶栏下方，不再有那个框。
            EthanTopBar(title = "全部对话", onBack = onBack) {
                IconButton(onClick = { searchExpanded = !searchExpanded }) {
                    Icon(
                        Icons.Default.Search,
                        contentDescription = "搜索",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(20.dp),
                    )
                }
            }
        },
        snackbarHost = { SnackbarContainer(snackbar) },
        containerColor = MaterialTheme.colorScheme.background,
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            // 类别 chips（排他，对齐 web all-sessions-view）：全部对话 / 定时任务对话 / 心跳对话。
            // 「全部对话」= 排除定时/心跳（它们有专属类别入口），不再是全部混在一起。
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                CATEGORY_CHIPS.forEach { (label, key) ->
                    val categorySelected = state.categoryFilter == key
                    Surface(
                        shape = RoundedCornerShape(50),
                        color = if (categorySelected) MaterialTheme.colorScheme.secondaryContainer
                            else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
                        border = if (categorySelected) null else BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                        modifier = Modifier.clickable(
                            indication = null,
                            interactionSource = remember { MutableInteractionSource() },
                        ) { onToggleCategory(key) },
                    ) {
                        Text(
                            text = label,
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 5.dp),
                            style = MaterialTheme.typography.labelMedium,
                            color = if (categorySelected) MaterialTheme.colorScheme.onSecondaryContainer
                                else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            // 来源 chips（多选）：「全部」= 空集合
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 12.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                val allSelected = state.selectedSources.isEmpty()
                Surface(
                    shape = RoundedCornerShape(50),
                    color = if (allSelected) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
                    border = if (allSelected) null else BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                    modifier = Modifier.clickable(
                        indication = null,
                        interactionSource = remember { MutableInteractionSource() },
                    ) { onSelectAllSources() },
                ) {
                    Text(
                        text = "全部",
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 5.dp),
                        style = MaterialTheme.typography.labelMedium,
                        color = if (allSelected) MaterialTheme.colorScheme.onPrimary
                            else MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                ALL_SOURCE_CHIPS.forEach { sourceKey ->
                    val selected = state.selectedSources.contains(sourceKey)
                    Surface(
                        shape = RoundedCornerShape(50),
                        color = if (selected) MaterialTheme.colorScheme.primary
                            else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
                        border = if (selected) null else BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                        modifier = Modifier.clickable(
                            indication = null,
                            interactionSource = remember { MutableInteractionSource() },
                        ) { onToggleSource(sourceKey) },
                    ) {
                        Text(
                            text = sourceKey,
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 5.dp),
                            style = MaterialTheme.typography.labelMedium,
                            color = if (selected) MaterialTheme.colorScheme.onPrimary
                                else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            // Expandable inline search bar
            AnimatedVisibility(
                visible = searchExpanded,
                enter = expandVertically(),
                exit = shrinkVertically(),
            ) {
                Surface(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 4.dp),
                    shape = MaterialTheme.shapes.extraLarge,
                    color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                    border = BorderStroke(1.5.dp, MaterialTheme.colorScheme.outlineVariant),
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(
                            Icons.Default.Search,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(18.dp),
                        )
                        OutlinedTextField(
                            value = state.query,
                            onValueChange = onQueryChange,
                            placeholder = { Text("搜索对话…", color = MaterialTheme.colorScheme.onSurfaceVariant) },
                            modifier = Modifier.weight(1f).height(48.dp),
                            singleLine = true,
                            shape = MaterialTheme.shapes.large,
                            colors = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = androidx.compose.ui.graphics.Color.Transparent,
                                unfocusedBorderColor = androidx.compose.ui.graphics.Color.Transparent,
                            ),
                        )
                        IconButton(
                            onClick = { searchExpanded = false; onQueryChange("") },
                            modifier = Modifier.size(24.dp),
                        ) {
                            Icon(
                                Icons.Default.Close,
                                contentDescription = "关闭",
                                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.size(16.dp),
                            )
                        }
                    }
                }
            }

            if (state.isLoading && state.sessions.isEmpty()) {
                LoadingBox()
            } else {
                LazyVerticalGrid(
                    columns = GridCells.Fixed(1),
                    contentPadding = PaddingValues(12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    // 置顶分组（独立展示于顶部）
                    if (state.pinnedSessions.isNotEmpty()) {
                        item(key = "pinned_header") {
                            GroupHeader("置顶")
                        }
                        items(state.pinnedSessions, key = { it.id }) { session ->
                            SessionCard(
                                session = session,
                                isRegening = session.id in state.regeningIds,
                                onClick = { onSessionClick(session.id) },
                                onRename = { onRename(session) },
                                onDelete = { onDelete(session.id) },
                                onRegenTitle = { onRegenTitle(session.id) },
                                onSummary = { onSummary(session.id) },
                                onTogglePin = { onTogglePin(session) },
                            )
                        }
                    }

                    item(key = "all_header") {
                        // 分组标题跟随类别（类别筛选下还写「全部对话」会文不对题）
                        GroupHeader(
                            when (state.categoryFilter) {
                                "scheduled" -> "定时任务对话"
                                "heartbeat" -> "心跳对话"
                                else -> "全部对话"
                            },
                        )
                    }
                    items(state.filteredSessions, key = { it.id }) { session ->
                        SessionCard(
                            session = session,
                            isRegening = session.id in state.regeningIds,
                            onClick = { onSessionClick(session.id) },
                            onRename = { onRename(session) },
                            onDelete = { onDelete(session.id) },
                            onRegenTitle = { onRegenTitle(session.id) },
                            onSummary = { onSummary(session.id) },
                            onTogglePin = { onTogglePin(session) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun GroupHeader(title: String) {
    Text(
        text = title,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(start = 4.dp, top = 4.dp, bottom = 2.dp),
    )
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun SessionCard(
    session: SessionInfo,
    isRegening: Boolean,
    onClick: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
    onRegenTitle: () -> Unit,
    onSummary: () -> Unit,
    onTogglePin: () -> Unit = {},
) {
    val date = remember(session.updatedAt) {
        SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()).format(Date(session.updatedAt * 1000))
    }
    var menuExpanded by remember { mutableStateOf(false) }
    val isPinned = session.pinnedAt > 0

    // 会话卡片：去掉 2dp 阴影 + 淡主色描边（M3 用 surface 色阶表达层级，不靠描边和投影）。
    // 保留 combinedClickable 是因为需要长按菜单，所以不用 Card(onClick)。
    Surface(
        modifier = Modifier.fillMaxWidth().combinedClickable(
            onClick = onClick,
            onLongClick = { menuExpanded = true },
        ),
        shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        shadowElevation = 0.dp,
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (isPinned) {
                    Icon(
                        Icons.Default.PushPin,
                        contentDescription = "已置顶",
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(14.dp),
                    )
                    androidx.compose.foundation.layout.Spacer(Modifier.size(4.dp))
                }
                Text(
                    if (isRegening) "生成中..." else session.title,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
            }
            session.snippet?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
            Row(
                modifier = Modifier.padding(top = 8.dp).fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "${session.model} · $date",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                SourceBadge(session.source)
            }
        }

        DropdownMenu(expanded = menuExpanded, onDismissRequest = { menuExpanded = false }) {
            DropdownMenuItem(text = { Text("重命名") }, onClick = { menuExpanded = false; onRename() })
            DropdownMenuItem(
                text = { Text(if (isPinned) "取消置顶" else "置顶") },
                onClick = { menuExpanded = false; onTogglePin() },
            )
            DropdownMenuItem(
                text = { Text("重生成标题") },
                onClick = { menuExpanded = false; onRegenTitle() },
                enabled = !isRegening,
            )
            DropdownMenuItem(text = { Text("生成总结") }, onClick = { menuExpanded = false; onSummary() })
            DropdownMenuItem(text = { Text("删除") }, onClick = { menuExpanded = false; onDelete() })
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SummaryBottomSheet(summary: SummaryResponse, onDismiss: () -> Unit) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val clipboard = LocalClipboardManager.current

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp, vertical = 8.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("对话总结", style = MaterialTheme.typography.titleLarge)
                TextButton(onClick = { clipboard.setText(AnnotatedString(summary.summary)); onDismiss() }) {
                    Text("复制全文")
                }
            }
            Text(
                text = summary.summary,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(top = 12.dp, bottom = 24.dp),
            )
        }
    }
}
