package com.ethan.agent.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.AgentSettings
import com.ethan.agent.core.model.ProviderConfig
import com.ethan.agent.core.model.SystemSettings
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    state: SettingsUiState,
    onTabChange: (SettingsTab) -> Unit,
    onServerUrlChange: (String) -> Unit,
    onSaveServerUrl: () -> Unit,
    onUpdateAgent: (AgentSettings) -> Unit,
    onSaveAgent: () -> Unit,
    onUpdateProvider: (String, ProviderConfig) -> Unit,
    onSaveProviders: () -> Unit,
    onUpdateSystem: (SystemSettings) -> Unit,
    onSaveSystem: () -> Unit,
    onProfileChange: (String) -> Unit,
    onSaveProfile: () -> Unit,
    onChannelChange: (String, String, String) -> Unit,
    onSaveChannel: (String) -> Unit,
    onLoadPromptPreview: () -> Unit,
    onCreateApiKey: (String) -> Unit,
    onDeleteApiKey: (String) -> Unit,
    onDismissNewApiKey: () -> Unit,
    onClearError: () -> Unit,
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    state.newApiKey?.let { key ->
        AlertDialog(
            onDismissRequest = onDismissNewApiKey,
            title = { Text("API Key 已创建") },
            text = {
                Column {
                    Text("请立即保存，此密钥不会再次显示：")
                    Text(key.key, style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = { TextButton(onClick = onDismissNewApiKey) { Text("已保存") } },
        )
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text("设置") }) },
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        if (state.isLoading && state.agentSettings == null) {
            LoadingBox(Modifier.padding(padding))
            return@Scaffold
        }

        Column(Modifier.fillMaxSize().padding(padding)) {
            SettingsTabRow(state.tab, onTabChange)

            Column(
                Modifier
                    .weight(1f)
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                when (state.tab) {
                    SettingsTab.Connection -> ConnectionTab(state, onServerUrlChange, onSaveServerUrl)
                    SettingsTab.General -> state.agentSettings?.let {
                        GeneralTab(it, onUpdateAgent, onSaveAgent)
                    }
                    SettingsTab.Providers -> ProvidersTab(state.providers, onUpdateProvider, onSaveProviders)
                    SettingsTab.Channels -> ChannelsTab(state.channels, onChannelChange, onSaveChannel)
                    SettingsTab.Identity -> SystemTextTab("身份 (identity.md)", state.systemSettings?.identity ?: "", {
                        onUpdateSystem(state.systemSettings?.copy(identity = it) ?: SystemSettings(identity = it))
                    }, onSaveSystem)
                    SettingsTab.Soul -> SystemTextTab("灵魂 (soul.md)", state.systemSettings?.soul ?: "", {
                        onUpdateSystem(state.systemSettings?.copy(soul = it) ?: SystemSettings(soul = it))
                    }, onSaveSystem)
                    SettingsTab.Tools -> SystemTextTab("工具 (tools.md)", state.systemSettings?.tools ?: "", {
                        onUpdateSystem(state.systemSettings?.copy(tools = it) ?: SystemSettings(tools = it))
                    }, onSaveSystem)
                    SettingsTab.Heartbeat -> SystemTextTab("心跳 (heartbeat.md)", state.systemSettings?.heartbeat ?: "", {
                        onUpdateSystem(state.systemSettings?.copy(heartbeat = it) ?: SystemSettings(heartbeat = it))
                    }, onSaveSystem)
                    SettingsTab.Profile -> ProfileTab(state.profile, onProfileChange, onSaveProfile)
                    SettingsTab.PromptPreview -> PromptPreviewTab(state, onLoadPromptPreview)
                    SettingsTab.ApiKeys -> ApiKeysTab(state, onCreateApiKey, onDeleteApiKey)
                }
            }
        }
    }
}

@Composable
private fun SettingsTabRow(selected: SettingsTab, onTabChange: (SettingsTab) -> Unit) {
    LazyColumn {
        item {
            Row(
                Modifier.fillMaxWidth().padding(8.dp),
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                SettingsTab.entries.forEach { tab ->
                    FilterChip(
                        selected = selected == tab,
                        onClick = { onTabChange(tab) },
                        label = {
                            Text(
                                when (tab) {
                                    SettingsTab.Connection -> "连接"
                                    SettingsTab.General -> "通用"
                                    SettingsTab.Providers -> "模型"
                                    SettingsTab.Channels -> "渠道"
                                    SettingsTab.Identity -> "身份"
                                    SettingsTab.Soul -> "灵魂"
                                    SettingsTab.Tools -> "工具"
                                    SettingsTab.Heartbeat -> "心跳"
                                    SettingsTab.Profile -> "画像"
                                    SettingsTab.PromptPreview -> "预览"
                                    SettingsTab.ApiKeys -> "Keys"
                                },
                                style = MaterialTheme.typography.labelSmall,
                            )
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun ConnectionTab(state: SettingsUiState, onUrlChange: (String) -> Unit, onSave: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("服务器连接", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(state.serverUrl, onUrlChange, label = { Text("服务器地址") }, modifier = Modifier.fillMaxWidth())
            state.serverVersion?.let { Text("版本: $it", style = MaterialTheme.typography.bodySmall) }
            TextButton(onClick = onSave) { Text("测试并保存") }
            Text(
                "示例: http://192.168.1.100:8900 或 https://your-nas.com:8900",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun GeneralTab(settings: AgentSettings, onUpdate: (AgentSettings) -> Unit, onSave: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(settings.agentName, { onUpdate(settings.copy(agentName = it)) }, label = { Text("Agent 名称") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(settings.defaultModel, { onUpdate(settings.copy(defaultModel = it)) }, label = { Text("默认模型") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(settings.liteModel, { onUpdate(settings.copy(liteModel = it)) }, label = { Text("轻量模型") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(settings.language, { onUpdate(settings.copy(language = it)) }, label = { Text("语言 (zh/en)") }, modifier = Modifier.fillMaxWidth())
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("心跳")
                Switch(settings.heartbeatEnabled, { onUpdate(settings.copy(heartbeatEnabled = it)) })
            }
            TextButton(onClick = onSave) { Text("保存") }
        }
    }
}

@Composable
private fun ProvidersTab(
    providers: Map<String, ProviderConfig>,
    onUpdate: (String, ProviderConfig) -> Unit,
    onSave: () -> Unit,
) {
    providers.forEach { (name, config) ->
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(name, style = MaterialTheme.typography.titleSmall)
                OutlinedTextField(
                    config.apiKey,
                    { onUpdate(name, config.copy(apiKey = it)) },
                    label = { Text("API Key") },
                    modifier = Modifier.fillMaxWidth(),
                    visualTransformation = PasswordVisualTransformation(),
                )
                OutlinedTextField(
                    config.baseUrl ?: "",
                    { onUpdate(name, config.copy(baseUrl = it.ifBlank { null })) },
                    label = { Text("Base URL") },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
    TextButton(onClick = onSave) { Text("保存 Provider 配置") }
}

@Composable
private fun ChannelsTab(
    channels: List<com.ethan.agent.core.model.ChannelInfo>,
    onChange: (String, String, String) -> Unit,
    onSave: (String) -> Unit,
) {
    channels.forEach { channel ->
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(channel.name, style = MaterialTheme.typography.titleSmall)
                channel.config.forEach { (key, value) ->
                    OutlinedTextField(
                        value,
                        { onChange(channel.id, key, it) },
                        label = { Text(key) },
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                TextButton(onClick = { onSave(channel.id) }) { Text("保存") }
            }
        }
    }
}

@Composable
private fun SystemTextTab(title: String, content: String, onChange: (String) -> Unit, onSave: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(content, onChange, modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp), minLines = 10)
            TextButton(onClick = onSave) { Text("保存") }
        }
    }
}

@Composable
private fun ProfileTab(content: String, onChange: (String) -> Unit, onSave: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text("我的画像", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(content, onChange, modifier = Modifier.fillMaxWidth(), minLines = 12)
            TextButton(onClick = onSave) { Text("保存") }
        }
    }
}

@Composable
private fun PromptPreviewTab(state: SettingsUiState, onLoad: () -> Unit) {
    Column {
        TextButton(onClick = onLoad) { Text("加载预览") }
        state.promptPreview?.let { preview ->
            Text("约 ${preview.approxTotalTokens} tokens · ${preview.toolCount} 工具")
            OutlinedTextField(
                preview.systemPrompt,
                {},
                readOnly = true,
                modifier = Modifier.fillMaxWidth(),
                minLines = 8,
            )
        }
    }
}

@Composable
private fun ApiKeysTab(
    state: SettingsUiState,
    onCreate: (String) -> Unit,
    onDelete: (String) -> Unit,
) {
    var name by remember { mutableStateOf("") }
    Row(verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(name, { name = it }, label = { Text("名称") }, modifier = Modifier.weight(1f))
        TextButton(onClick = { onCreate(name); name = "" }) { Text("创建") }
    }
    state.apiKeys.forEach { key ->
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Column {
                Text(key.name)
                Text(key.keyPreview, style = MaterialTheme.typography.bodySmall)
            }
            IconButton(onClick = { onDelete(key.id) }) {
                Icon(Icons.Default.Delete, contentDescription = "删除")
            }
        }
    }
}
