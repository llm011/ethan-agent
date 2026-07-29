package com.ethan.agent.ui.sessions

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
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
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
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// All source chips shown in filter bar
private val ALL_SOURCE_CHIPS = listOf("web", "lark", "repl", "desktop", "wechat", "心跳", "定时")
private val SOURCE_CHIP_MAP = mapOf("心跳" to "heartbeat", "定时" to "scheduled")

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
    onToggleHideHeartbeat: () -> Unit = {},
    onToggleHideScheduled: () -> Unit = {},
    onToggleSource: (String) -> Unit = {},
    onSelectAllSources: () -> Unit = {},
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

    Scaffold(
        snackbarHost = { SnackbarContainer(snackbar) },
        containerColor = MaterialTheme.colorScheme.background,
    ) { padding ->
        var searchExpanded by remember { mutableStateOf(false) }

        Column(Modifier.fillMaxSize().padding(padding)) {
            // Filter bar card
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                shape = RoundedCornerShape(20.dp),
                color = MaterialTheme.colorScheme.surface,
                shadowElevation = 2.dp,
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 8.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    // Back button
                    IconButton(onClick = onBack, modifier = Modifier.size(36.dp)) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "返回",
                            tint = MaterialTheme.colorScheme.onSurface,
                            modifier = Modifier.size(20.dp),
                        )
                    }

                    // Scrollable chips
                    Row(
                        modifier = Modifier
                            .weight(1f)
                            .horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                    // "全部" chip：空集合表示全部
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
                    ALL_SOURCE_CHIPS.forEach { label ->
                        val sourceKey = SOURCE_CHIP_MAP[label] ?: label
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
                                text = label,
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 5.dp),
                                style = MaterialTheme.typography.labelMedium,
                                color = if (selected) MaterialTheme.colorScheme.onPrimary
                                    else MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }

                // Search icon
                IconButton(
                    onClick = { searchExpanded = !searchExpanded },
                    modifier = Modifier.size(36.dp),
                ) {
                    Icon(
                        Icons.Default.Search,
                        contentDescription = "搜索",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(20.dp),
                    )
                }
            }
            } // end filter bar Surface

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
                    shape = RoundedCornerShape(20.dp),
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
                            shape = RoundedCornerShape(16.dp),
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
                    items(state.filteredSessions, key = { it.id }) { session ->
                        SessionCard(
                            session = session,
                            isRegening = session.id in state.regeningIds,
                            onClick = { onSessionClick(session.id) },
                            onRename = { onRename(session) },
                            onDelete = { onDelete(session.id) },
                            onRegenTitle = { onRegenTitle(session.id) },
                            onSummary = { onSummary(session.id) },
                        )
                    }
                }
            }
        }
    }
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
) {
    val date = remember(session.updatedAt) {
        SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()).format(Date(session.updatedAt * 1000))
    }
    var menuExpanded by remember { mutableStateOf(false) }

    Surface(
        modifier = Modifier.fillMaxWidth().combinedClickable(
            onClick = onClick,
            onLongClick = { menuExpanded = true },
        ),
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surface,
        shadowElevation = 2.dp,
        border = androidx.compose.foundation.BorderStroke(
            width = 1.dp,
            color = MaterialTheme.colorScheme.primary.copy(alpha = 0.15f),
        ),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(
                if (isRegening) "生成中..." else session.title,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
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
