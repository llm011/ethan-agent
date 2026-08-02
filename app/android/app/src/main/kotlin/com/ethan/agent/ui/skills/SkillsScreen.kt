package com.ethan.agent.ui.skills

import com.ethan.agent.shared.viewmodel.SkillsUiState
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.SkillInfo
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.EthanTopBar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SkillsScreen(
    state: SkillsUiState,
    onBack: () -> Unit = {},
    onQueryChange: (String) -> Unit,
    onSelect: (SkillInfo) -> Unit,
    onDeselect: () -> Unit,
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

    val isDetailOpen = state.selected != null || state.isCreating

    Scaffold(
        topBar = {
            if (isDetailOpen) {
                EthanTopBar(
                    title = if (state.isCreating) "新建技能" else "编辑技能",
                    onBack = onDeselect,
                    actions = {
                        TextButton(onClick = onSave) { Text("保存") }
                        if (!state.isCreating) {
                            IconButton(onClick = { state.selected?.name?.let(onDelete) }) {
                                Icon(Icons.Default.Delete, contentDescription = "删除")
                            }
                        }
                    }
                )
            } else {
                EthanTopBar(
                    title = "技能",
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
        if (state.isLoading && state.skills.isEmpty()) {
            LoadingBox(Modifier.padding(padding))
            return@Scaffold
        }

        Column(Modifier.fillMaxSize().padding(padding)) {
            if (isDetailOpen) {
                SkillDetailContent(
                    state = state,
                    onNameChange = onNameChange,
                    onDescriptionChange = onDescriptionChange,
                    onTriggersChange = onTriggersChange,
                    onContentChange = onContentChange,
                )
            } else {
                SkillListContent(
                    state = state,
                    onQueryChange = onQueryChange,
                    onSelect = onSelect,
                )
            }
        }
    }
}

@Composable
private fun SkillListContent(
    state: SkillsUiState,
    onQueryChange: (String) -> Unit,
    onSelect: (SkillInfo) -> Unit,
) {
    Column {
        OutlinedTextField(
            value = state.query,
            onValueChange = onQueryChange,
            label = { Text("搜索技能") },
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            singleLine = true,
        )
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = PaddingValues(16.dp),
        ) {
            state.groupedSkills.forEach { (category, skills) ->
                item(key = "header_$category") {
                    Row(
                        Modifier.fillMaxWidth().padding(vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        HorizontalDivider(Modifier.weight(1f).padding(end = 8.dp))
                        Text(
                            category,
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.primary,
                        )
                        HorizontalDivider(Modifier.weight(1f).padding(start = 8.dp))
                    }
                }
                items(skills, key = { it.name }) { skill ->
                    SkillCard(
                        skill = skill,
                        isSelected = state.selected?.name == skill.name,
                        onClick = { onSelect(skill) }
                    )
                }
            }
        }
    }
}

@Composable
private fun SkillDetailContent(
    state: SkillsUiState,
    onNameChange: (String) -> Unit,
    onDescriptionChange: (String) -> Unit,
    onTriggersChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        OutlinedTextField(
            state.name, onNameChange,
            label = { Text("名称") },
            modifier = Modifier.fillMaxWidth(),
            enabled = state.isCreating,
        )
        OutlinedTextField(
            state.description, onDescriptionChange,
            label = { Text("描述") },
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            state.triggers, onTriggersChange,
            label = { Text("触发词 (逗号分隔)") },
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            state.content, onContentChange,
            label = { Text("内容 (Markdown)") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 10,
        )
    }
}

@Composable
private fun SkillCard(skill: SkillInfo, isSelected: Boolean, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = if (isSelected) {
            androidx.compose.material3.CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.primaryContainer,
            )
        } else {
            androidx.compose.material3.CardDefaults.cardColors()
        },
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(skill.name, style = MaterialTheme.typography.titleSmall)
            if (skill.description.isNotBlank()) {
                Text(
                    skill.description,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
            if (skill.trigger.isNotEmpty()) {
                Row(
                    modifier = Modifier.padding(top = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    skill.trigger.take(3).forEach { trigger ->
                        androidx.compose.material3.SuggestionChip(
                            onClick = {},
                            label = { Text(trigger, style = MaterialTheme.typography.labelSmall) },
                            modifier = Modifier,
                        )
                    }
                }
            }
        }
    }
}
