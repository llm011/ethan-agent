package com.ethan.agent.ui.sessions

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.SessionInfo
import com.ethan.agent.core.model.SummaryResponse
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer
import com.ethan.agent.ui.components.SourceBadge
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val SOURCE_OPTIONS = listOf("All", "web", "lark", "repl", "heartbeat")

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
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
    onSetSourceFilter: (String) -> Unit,
    onToggleHideHeartbeat: () -> Unit,
    onToggleHideScheduled: () -> Unit,
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
        topBar = { TopAppBar(title = { Text("全部对话") }) },
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            OutlinedTextField(
                value = state.query,
                onValueChange = onQueryChange,
                label = { Text("搜索对话") },
                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
                singleLine = true,
            )

            FlowRow(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                SOURCE_OPTIONS.forEach { src ->
                    FilterChip(
                        selected = state.sourceFilter == src,
                        onClick = { onSetSourceFilter(src) },
                        label = { Text(src) },
                    )
                }
                FilterChip(
                    selected = state.hideHeartbeat,
                    onClick = onToggleHideHeartbeat,
                    label = { Text("隐藏心跳") },
                )
                FilterChip(
                    selected = state.hideScheduled,
                    onClick = onToggleHideScheduled,
                    label = { Text("隐藏定时") },
                )
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

    Card(
        Modifier.fillMaxWidth().combinedClickable(
            onClick = onClick,
            onLongClick = { menuExpanded = true },
        ),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(
                if (isRegening) "生成中..." else session.title,
                style = MaterialTheme.typography.titleMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            session.snippet?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            Column(Modifier.padding(top = 8.dp)) {
                Text("${session.model} · $date", style = MaterialTheme.typography.labelSmall)
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
