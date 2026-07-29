package com.ethan.agent.ui.logs

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.EthanTopBar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LogsScreen(
    state: LogsUiState,
    onBack: () -> Unit = {},
    onTypeChange: (String) -> Unit,
    onQueryChange: (String) -> Unit,
    onRefresh: () -> Unit,
    onClearError: () -> Unit,
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    Scaffold(
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(top = padding.calculateTopPadding())) {
            EthanTopBar(
                title = "日志",
                onBack = onBack,
                actions = {
                    IconButton(onClick = onRefresh) {
                        Icon(Icons.Default.Refresh, contentDescription = "刷新")
                    }
                },
            )

            Column(
                Modifier
                    .fillMaxSize()
                    .padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(
                        selected = state.type == "backend",
                        onClick = { onTypeChange("backend") },
                        label = { Text("Backend") },
                    )
                    FilterChip(
                        selected = state.type == "frontend",
                        onClick = { onTypeChange("frontend") },
                        label = { Text("Frontend") },
                    )
                }

                OutlinedTextField(
                    value = state.query,
                    onValueChange = onQueryChange,
                    placeholder = { Text("关键字过滤") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )

                if (state.isLoading && state.content.isEmpty()) {
                    LoadingBox()
                } else {
                    Text(
                        text = state.content.ifBlank { "（无日志）" },
                        fontFamily = FontFamily.Monospace,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier
                            .fillMaxWidth()
                            .verticalScroll(rememberScrollState()),
                    )
                }
            }
        }
    }
}
