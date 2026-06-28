package com.ethan.agent.ui.knowledge

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KnowledgeScreen(
    state: KnowledgeUiState,
    onQueryChange: (String) -> Unit,
    onToggleSemantic: () -> Unit,
    onSelect: (com.ethan.agent.core.model.KnowledgeItem) -> Unit,
    onStartCreate: () -> Unit,
    onTitleChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onTagsChange: (String) -> Unit,
    onSave: () -> Unit,
    onDelete: () -> Unit,
    onClearError: () -> Unit,
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    Scaffold(
        topBar = { TopAppBar(title = { Text("知识库") }) },
        floatingActionButton = {
            FloatingActionButton(onClick = onStartCreate) {
                Icon(Icons.Default.Add, contentDescription = "新建")
            }
        },
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        if (state.isLoading && state.items.isEmpty()) {
            LoadingBox(Modifier.padding(padding))
            return@Scaffold
        }

        Column(Modifier.fillMaxSize().padding(padding)) {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedTextField(
                    value = state.query,
                    onValueChange = onQueryChange,
                    label = { Text("搜索") },
                    modifier = Modifier.weight(1f),
                    singleLine = true,
                )
                Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.padding(start = 8.dp)) {
                    Text("语义", style = MaterialTheme.typography.labelSmall)
                    Switch(checked = state.semanticSearch, onCheckedChange = { onToggleSemantic() })
                }
            }

            Row(Modifier.weight(1f)) {
                LazyColumn(Modifier.weight(1f).padding(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    items(state.items, key = { it.source }) { item ->
                        Card(Modifier.fillMaxWidth().clickable { onSelect(item) }) {
                            Column(Modifier.padding(12.dp)) {
                                Text(item.title, style = MaterialTheme.typography.titleSmall)
                                item.tags?.let { Text(it.joinToString(", "), style = MaterialTheme.typography.labelSmall) }
                            }
                        }
                    }
                }

                Column(Modifier.weight(1.2f).padding(8.dp)) {
                    if (state.selected != null || state.isCreating) {
                        OutlinedTextField(state.title, onTitleChange, label = { Text("标题") }, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(
                            state.content,
                            onContentChange,
                            label = { Text("内容 (Markdown)") },
                            modifier = Modifier.fillMaxWidth().weight(1f),
                        )
                        OutlinedTextField(state.tags, onTagsChange, label = { Text("标签 (逗号分隔)") }, modifier = Modifier.fillMaxWidth())
                        Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                            TextButton(onClick = onSave) { Text("保存") }
                            if (!state.isCreating) {
                                IconButton(onClick = onDelete) {
                                    Icon(Icons.Default.Delete, contentDescription = "删除")
                                }
                            }
                        }
                    } else {
                        Text("选择或新建知识条目", modifier = Modifier.padding(16.dp))
                    }
                }
            }
        }
    }
}
