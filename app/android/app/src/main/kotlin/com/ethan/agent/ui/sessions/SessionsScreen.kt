package com.ethan.agent.ui.sessions

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.SessionInfo
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer
import com.ethan.agent.ui.components.SourceBadge
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

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
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    state.renameTarget?.let { target ->
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

    Scaffold(
        topBar = { TopAppBar(title = { Text("全部对话") }) },
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            OutlinedTextField(
                value = state.query,
                onValueChange = onQueryChange,
                label = { Text("搜索对话") },
                modifier = Modifier.fillMaxWidth().padding(12.dp),
                singleLine = true,
            )

            if (state.isLoading && state.sessions.isEmpty()) {
                LoadingBox()
            } else {
                LazyVerticalGrid(
                    columns = GridCells.Fixed(1),
                    contentPadding = PaddingValues(12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(state.sessions, key = { it.id }) { session ->
                        SessionCard(
                            session = session,
                            onClick = { onSessionClick(session.id) },
                            onRename = { onRename(session) },
                            onDelete = { onDelete(session.id) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun SessionCard(
    session: SessionInfo,
    onClick: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    val date = remember(session.updatedAt) {
        SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()).format(Date(session.updatedAt * 1000))
    }

    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(Modifier.padding(16.dp)) {
            Text(session.title, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            session.snippet?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            Column(Modifier.padding(top = 8.dp)) {
                Text("${session.model} · $date", style = MaterialTheme.typography.labelSmall)
                SourceBadge(session.source)
            }
            RowActions(onRename, onDelete)
        }
    }
}

@Composable
private fun RowActions(onRename: () -> Unit, onDelete: () -> Unit) {
    androidx.compose.foundation.layout.Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
        IconButton(onClick = onRename) { Icon(Icons.Default.Edit, contentDescription = "重命名") }
        IconButton(onClick = onDelete) { Icon(Icons.Default.Delete, contentDescription = "删除") }
    }
}
