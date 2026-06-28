package com.ethan.agent.ui.schedule

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.ScheduleJob
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScheduleScreen(
    state: ScheduleUiState,
    onToggle: (ScheduleJob) -> Unit,
    onDelete: (String) -> Unit,
    onOpenSession: (String) -> Unit,
    onClearError: () -> Unit,
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    Scaffold(
        topBar = { TopAppBar(title = { Text("定时任务") }) },
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        if (state.isLoading) {
            LoadingBox(Modifier.padding(padding))
            return@Scaffold
        }

        LazyColumn(
            Modifier.fillMaxSize().padding(padding).padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(state.jobs, key = { it.id }) { job ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Text(job.name, style = MaterialTheme.typography.titleMedium)
                        Text(job.trigger, style = MaterialTheme.typography.bodySmall)
                        job.nextRunTime?.let { Text("下次: $it", style = MaterialTheme.typography.labelSmall) }
                        Text(
                            if (job.status == "active") "运行中" else "已暂停",
                            color = if (job.status == "active") MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.labelMedium,
                        )
                        Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                            if (job.sessionId.isNotBlank()) {
                                TextButton(onClick = { onOpenSession(job.sessionId) }) { Text("查看对话") }
                            }
                            IconButton(onClick = { onToggle(job) }) {
                                Icon(Icons.Default.PlayArrow, contentDescription = "暂停/恢复")
                            }
                            IconButton(onClick = { onDelete(job.id) }) {
                                Icon(Icons.Default.Delete, contentDescription = "删除")
                            }
                        }
                    }
                }
            }
        }
    }
}
