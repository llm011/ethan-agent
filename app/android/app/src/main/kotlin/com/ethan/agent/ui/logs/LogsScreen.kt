package com.ethan.agent.ui.logs

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LogsScreen(
    state: LogsUiState,
    onTypeChange: (String) -> Unit,
    onQueryChange: (String) -> Unit,
    onRefresh: () -> Unit,
    onClearError: () -> Unit,
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("日志") },
                actions = { TextButton(onClick = onRefresh) { Text("刷新") } },
            )
        },
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).padding(12.dp)) {
            androidx.compose.foundation.layout.Row {
                FilterChip(selected = state.type == "backend", onClick = { onTypeChange("backend") }, label = { Text("后端") })
                FilterChip(selected = state.type == "frontend", onClick = { onTypeChange("frontend") }, label = { Text("前端") })
            }
            OutlinedTextField(
                state.query,
                onQueryChange,
                label = { Text("过滤") },
                modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                singleLine = true,
            )
            if (state.isLoading) {
                LoadingBox()
            } else {
                Text(
                    state.content.ifBlank { "暂无日志" },
                    modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                )
            }
        }
    }
}
