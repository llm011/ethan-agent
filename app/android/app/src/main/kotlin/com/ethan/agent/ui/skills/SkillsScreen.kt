package com.ethan.agent.ui.skills

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
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SkillsScreen(
    state: SkillsUiState,
    onSelect: (com.ethan.agent.core.model.SkillInfo) -> Unit,
    onStartCreate: () -> Unit,
    onNameChange: (String) -> Unit,
    onDescriptionChange: (String) -> Unit,
    onTriggersChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onSave: () -> Unit,
    onDelete: (String) -> Unit,
    onClearError: () -> Unit,
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    Scaffold(
        topBar = { TopAppBar(title = { Text("技能") }) },
        floatingActionButton = {
            FloatingActionButton(onClick = onStartCreate) {
                Icon(Icons.Default.Add, contentDescription = "新建")
            }
        },
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        if (state.isLoading) {
            LoadingBox(Modifier.padding(padding))
            return@Scaffold
        }

        Row(Modifier.fillMaxSize().padding(padding)) {
            LazyColumn(Modifier.weight(1f).padding(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                items(state.skills, key = { it.name }) { skill ->
                    Card(Modifier.fillMaxWidth().clickable { onSelect(skill) }) {
                        Column(Modifier.padding(12.dp)) {
                            Text(skill.name, style = MaterialTheme.typography.titleSmall)
                            Text(skill.description, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }

            Column(Modifier.weight(1.3f).padding(8.dp)) {
                if (state.selected != null || state.isCreating) {
                    OutlinedTextField(
                        state.name,
                        onNameChange,
                        label = { Text("名称") },
                        modifier = Modifier.fillMaxWidth(),
                        enabled = state.isCreating,
                    )
                    OutlinedTextField(state.description, onDescriptionChange, label = { Text("描述") }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(state.triggers, onTriggersChange, label = { Text("触发词 (逗号分隔)") }, modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(
                        state.content,
                        onContentChange,
                        label = { Text("内容 (Markdown)") },
                        modifier = Modifier.fillMaxWidth().weight(1f),
                    )
                    Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                        TextButton(onClick = onSave) { Text("保存") }
                        state.selected?.let {
                            IconButton(onClick = { onDelete(it.name) }) {
                                Icon(Icons.Default.Delete, contentDescription = "删除")
                            }
                        }
                    }
                } else {
                    Text("选择或新建技能", modifier = Modifier.padding(16.dp))
                }
            }
        }
    }
}
