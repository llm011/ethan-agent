package com.ethan.agent.ui.knowledge

import androidx.compose.foundation.clickable
import com.ethan.agent.shared.viewmodel.KnowledgeUiState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
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
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.KnowledgeItem
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.EthanTopBar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KnowledgeScreen(
    state: KnowledgeUiState,
    onBack: () -> Unit = {},
    onQueryChange: (String) -> Unit,
    onToggleSemantic: () -> Unit,
    onSelect: (KnowledgeItem) -> Unit,
    onDeselect: () -> Unit,
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

    val isDetailOpen = state.selected != null || state.isCreating

    Scaffold(
        topBar = {
            if (isDetailOpen) {
                EthanTopBar(
                    title = if (state.isCreating) "新建知识" else "编辑知识",
                    onBack = onDeselect,
                    actions = {
                        TextButton(onClick = onSave) { Text("保存") }
                        if (!state.isCreating) {
                            IconButton(onClick = onDelete) {
                                Icon(Icons.Default.Delete, contentDescription = "删除")
                            }
                        }
                    }
                )
            } else {
                EthanTopBar(
                    title = "知识库",
                    onBack = onBack,
                )
            }
        },
        floatingActionButton = {
            if (!isDetailOpen) {
                FloatingActionButton(onClick = onStartCreate) {
                    Icon(Icons.Default.Add, contentDescription = "新建")
                }
            }
        },
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        if (state.isLoading && state.items.isEmpty()) {
            LoadingBox(Modifier.padding(padding))
            return@Scaffold
        }

        Column(Modifier.fillMaxSize().padding(padding)) {
            if (isDetailOpen) {
                KnowledgeDetailContent(
                    state = state,
                    onTitleChange = onTitleChange,
                    onContentChange = onContentChange,
                    onTagInputChange = onTagInputChange,
                    onAddTag = onAddTag,
                    onRemoveTag = onRemoveTag,
                )
            } else {
                KnowledgeListContent(
                    state = state,
                    onQueryChange = onQueryChange,
                    onToggleSemantic = onToggleSemantic,
                    onSelect = onSelect,
                )
            }
        }
    }
}

@Composable
private fun KnowledgeListContent(
    state: KnowledgeUiState,
    onQueryChange: (String) -> Unit,
    onToggleSemantic: () -> Unit,
    onSelect: (KnowledgeItem) -> Unit,
) {
    Column {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = state.query,
                onValueChange = onQueryChange,
                label = { Text("搜索知识") },
                modifier = Modifier.weight(1f),
                singleLine = true,
            )
            Spacer(Modifier.width(8.dp))
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.clickable { onToggleSemantic() },
            ) {
                Text("语义", style = MaterialTheme.typography.labelMedium)
                Switch(
                    checked = state.semanticSearch,
                    onCheckedChange = { onToggleSemantic() },
                    modifier = Modifier.height(32.dp),
                )
            }
        }
        LazyColumn(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        ) {
            items(state.items, key = { it.source }) { item ->
                KnowledgeCard(item = item, onClick = { onSelect(item) })
            }
        }
    }
}

@Composable
private fun KnowledgeDetailContent(
    state: KnowledgeUiState,
    onTitleChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onTagInputChange: (String) -> Unit,
    onAddTag: () -> Unit,
    onRemoveTag: (String) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        OutlinedTextField(
            value = state.title,
            onValueChange = onTitleChange,
            label = { Text("标题") },
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = state.content,
            onValueChange = onContentChange,
            label = { Text("内容 (Markdown)") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 8,
        )
        Column {
            Text("标签", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(
                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                state.tagChips.forEach { tag ->
                    Chip(label = tag, onRemove = { onRemoveTag(tag) })
                }
            }
            OutlinedTextField(
                value = state.tagInput,
                onValueChange = onTagInputChange,
                label = { Text("添加标签，回车确认") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
        }
    }
}

@Composable
private fun Chip(label: String, onRemove: () -> Unit) {
    androidx.compose.material3.AssistChip(
        onClick = onRemove,
        label = { Text(label) },
        trailingIcon = {
            Icon(
                Icons.Default.Close,
                contentDescription = "移除",
                modifier = Modifier.padding(start = 4.dp).size(16.dp)
            )
        },
    )
}

@Composable
private fun KnowledgeCard(item: KnowledgeItem, query: String = "", onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(
                item.title,
                style = MaterialTheme.typography.titleSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            item.content?.takeIf { it.isNotBlank() }?.let { content ->
                Text(
                    content.take(150),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
            item.tags?.takeIf { it.isNotEmpty() }?.let { tags ->
                Row(
                    modifier = Modifier.padding(top = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    tags.take(3).forEach { tag ->
                        androidx.compose.material3.SuggestionChip(
                            onClick = {},
                            label = { Text(tag, style = MaterialTheme.typography.labelSmall) },
                            modifier = Modifier.height(24.dp),
                        )
                    }
                }
            }
        }
    }
}
