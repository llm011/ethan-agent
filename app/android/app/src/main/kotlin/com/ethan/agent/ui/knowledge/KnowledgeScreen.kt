package com.ethan.agent.ui.knowledge

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.InputChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onKeyEvent
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.KnowledgeItem
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.EthanTopBar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SimpleMarkdown
import com.ethan.agent.ui.components.SnackbarContainer

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun KnowledgeScreen(
    state: KnowledgeUiState,
    onBack: () -> Unit = {},
    onQueryChange: (String) -> Unit,
    onToggleSemantic: () -> Unit,
    onSelect: (KnowledgeItem) -> Unit,
    onStartCreate: () -> Unit,
    onTitleChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onTagInputChange: (String) -> Unit,
    onAddTag: () -> Unit,
    onRemoveTag: (String) -> Unit,
    onSave: () -> Unit,
    onDelete: () -> Unit,
    onClearError: () -> Unit,
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    Scaffold(
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
            EthanTopBar(title = "知识库", onBack = onBack)
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
                        KnowledgeCard(item = item, query = state.query, onClick = { onSelect(item) })
                    }
                }

                Column(Modifier.weight(1.2f).padding(8.dp)) {
                    if (state.selected != null || state.isCreating) {
                        OutlinedTextField(
                            state.title, onTitleChange,
                            label = { Text("标题") },
                            modifier = Modifier.fillMaxWidth(),
                        )
                        OutlinedTextField(
                            state.content, onContentChange,
                            label = { Text("内容 (Markdown)") },
                            modifier = Modifier.fillMaxWidth().weight(1f),
                        )
                        SimpleMarkdown(
                            text = state.content,
                            modifier = Modifier.fillMaxWidth().weight(1f).padding(horizontal = 4.dp),
                        )
                        TagChipInput(
                            chips = state.tagChips,
                            input = state.tagInput,
                            onInputChange = onTagInputChange,
                            onAddTag = onAddTag,
                            onRemoveTag = onRemoveTag,
                        )
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

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun TagChipInput(
    chips: List<String>,
    input: String,
    onInputChange: (String) -> Unit,
    onAddTag: () -> Unit,
    onRemoveTag: (String) -> Unit,
) {
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            chips.forEach { tag ->
                InputChip(
                    selected = false,
                    onClick = { onRemoveTag(tag) },
                    label = { Text(tag) },
                    trailingIcon = { Icon(Icons.Default.Close, contentDescription = null) },
                )
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = input,
                onValueChange = onInputChange,
                label = { Text("添加标签") },
                singleLine = true,
                modifier = Modifier.weight(1f).onKeyEvent { event ->
                    if (event.key == Key.Enter) { onAddTag(); true } else false
                },
            )
            IconButton(onClick = onAddTag) {
                Icon(Icons.Default.Add, contentDescription = "添加")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun KnowledgeCard(item: KnowledgeItem, query: String, onClick: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth(), onClick = onClick) {
        Column(Modifier.padding(12.dp)) {
            Text(
                text = highlightText(item.title, query),
                style = MaterialTheme.typography.titleSmall,
            )
            item.tags?.let {
                Text(it.joinToString(", "), style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}

private fun highlightText(text: String, query: String) = buildAnnotatedString {
    if (query.isBlank()) {
        append(text)
        return@buildAnnotatedString
    }
    val lower = text.lowercase()
    val lowerQ = query.lowercase()
    var start = 0
    while (start < text.length) {
        val idx = lower.indexOf(lowerQ, start)
        if (idx < 0) { append(text.substring(start)); break }
        append(text.substring(start, idx))
        withStyle(SpanStyle(fontWeight = FontWeight.Bold)) {
            append(text.substring(idx, idx + lowerQ.length))
        }
        start = idx + lowerQ.length
    }
}
