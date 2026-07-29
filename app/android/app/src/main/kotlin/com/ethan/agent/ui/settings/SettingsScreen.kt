package com.ethan.agent.ui.settings

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.AgentSettings
import com.ethan.agent.core.model.KnowledgeValidateRequest
import com.ethan.agent.core.model.ProviderConfig
import com.ethan.agent.core.model.SystemSettings
import com.ethan.agent.ui.components.CuteCard
import com.ethan.agent.ui.components.CuteTopBar
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer
import com.ethan.agent.ui.theme.EthanTheme
import com.ethan.agent.ui.theme.ThemeState

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
    onInstallLarkDeps: () -> Unit,
    onValidateKnowledge: (KnowledgeValidateRequest) -> Unit,
    onClearKnowledgeResult: () -> Unit,
    onSetTheme: (String) -> Unit,
    onCheckUpdate: () -> Unit,
    onClearError: () -> Unit,
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    state.knowledgeValidateResult?.let { msg ->
        LaunchedEffect(msg) {
            snackbar.showSnackbar(msg)
            onClearKnowledgeResult()
        }
    }

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
        topBar = { CuteTopBar(title = "设置") },
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
                        GeneralTab(it, onUpdateAgent, onSaveAgent, onCheckUpdate)
                    }
                    SettingsTab.Providers -> ProvidersTab(state.providers, onUpdateProvider, onSaveProviders)
                    SettingsTab.Channels -> ChannelsTab(
                        state = state,
                        onChange = onChannelChange,
                        onSave = onSaveChannel,
                        onInstallLarkDeps = onInstallLarkDeps,
                        onValidateKnowledge = onValidateKnowledge,
                    )
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
                    SettingsTab.FastRules -> FastRulesTab(state)
                    SettingsTab.ToolTiers -> ToolTiersTab(state)
                    SettingsTab.Theme -> ThemeTab(state.themeId, onSetTheme)
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SettingsTabRow(selected: SettingsTab, onTabChange: (SettingsTab) -> Unit) {
    // Segment Control style: grey container with white floating active indicator
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 8.dp),
        shape = RoundedCornerShape(14.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        border = BorderStroke(1.5.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        LazyRow(
            modifier = Modifier.padding(3.dp),
            horizontalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            items(SettingsTab.entries.toList()) { tab ->
                val isSelected = selected == tab
                Surface(
                    onClick = { onTabChange(tab) },
                    shape = RoundedCornerShape(11.dp),
                    color = if (isSelected) MaterialTheme.colorScheme.surface
                        else androidx.compose.ui.graphics.Color.Transparent,
                    shadowElevation = if (isSelected) 2.dp else 0.dp,
                ) {
                    Text(
                        when (tab) {
                            SettingsTab.Connection -> "连接"
                            SettingsTab.General -> "Agent"
                            SettingsTab.Providers -> "模型"
                            SettingsTab.Channels -> "渠道"
                            SettingsTab.Identity -> "身份"
                            SettingsTab.Soul -> "灵魂"
                            SettingsTab.Tools -> "工具"
                            SettingsTab.Heartbeat -> "心跳"
                            SettingsTab.Profile -> "画像"
                            SettingsTab.PromptPreview -> "预览"
                            SettingsTab.ApiKeys -> "Keys"
                            SettingsTab.FastRules -> "Fast Rules"
                            SettingsTab.ToolTiers -> "路由档位"
                            SettingsTab.Theme -> "主题"
                        },
                        style = MaterialTheme.typography.labelMedium.copy(
                            fontWeight = if (isSelected) androidx.compose.ui.text.font.FontWeight.Bold
                                else androidx.compose.ui.text.font.FontWeight.SemiBold,
                        ),
                        color = if (isSelected) MaterialTheme.colorScheme.primary
                            else MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 9.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun ConnectionTab(state: SettingsUiState, onUrlChange: (String) -> Unit, onSave: () -> Unit) {
    CuteCard {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("服务器连接", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(state.serverUrl, onUrlChange, label = { Text("服务器地址") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            state.serverVersion?.let { Text("版本: $it", style = MaterialTheme.typography.bodySmall) }
            TextButton(onClick = onSave) { Text("测试并保存") }
            Text(
                "示例: http://192.168.1.100:8900 或 https://your-nas.com:8900",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

private val THEME_OPTIONS = listOf(
    Triple("honey", "🍯 暖黄蜜糖", Color(0xFFF5A623)),
    Triple("matcha", "🍵 抹茶", Color(0xFF7BAE6B)),
    Triple("lavender", "💜 薰衣草", Color(0xFF9B7EC8)),
    Triple("sky_blue", "☁️ 天蓝", Color(0xFF5BA4D9)),
    Triple("qingwa", "🏔 青瓦", Color(0xFF4A6572)),
    Triple("warm_orange", "🍊 暖橙", Color(0xFFBF5B17)),
    Triple("plain_paper", "📜 素纸", Color(0xFF5A5347)),
    Triple("mist", "🌫 微雾", Color(0xFF636B74)),
    Triple("system", "✨ 跟随系统", Color(0xFF8E8E93)),
    Triple("light", "☀️ 浅色", Color(0xFFE0E0E0)),
    Triple("dark", "🌙 深色", Color(0xFF333333)),
)

@Composable
private fun GeneralTab(
    settings: AgentSettings,
    onUpdate: (AgentSettings) -> Unit,
    onSave: () -> Unit,
    onCheckUpdate: () -> Unit,
) {
    CuteCard {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(settings.agentName, { onUpdate(settings.copy(agentName = it)) }, label = { Text("Agent 名称") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            OutlinedTextField(settings.defaultModel, { onUpdate(settings.copy(defaultModel = it)) }, label = { Text("默认模型") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            OutlinedTextField(settings.liteModel, { onUpdate(settings.copy(liteModel = it)) }, label = { Text("轻量模型") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            OutlinedTextField(settings.language, { onUpdate(settings.copy(language = it)) }, label = { Text("语言 (zh/en)") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("心跳")
                Switch(settings.heartbeatEnabled, { onUpdate(settings.copy(heartbeatEnabled = it)) })
            }
            TextButton(onClick = onSave) { Text("保存") }
        }
    }

    CuteCard {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("系统", style = MaterialTheme.typography.titleSmall)
            OutlinedButton(onClick = onCheckUpdate, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(modifier = Modifier.width(8.dp))
                Text("检查更新")
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ThemeTab(themeId: String, onSetTheme: (String) -> Unit) {
    CuteCard {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("选择主题", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(
                "点击色点切换主题配色",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(14.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                THEME_OPTIONS.forEach { (id, label, color) ->
                    val isSelected = themeId == id
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Box(
                            modifier = Modifier
                                .size(40.dp)
                                .background(color, CircleShape)
                                .border(
                                    width = if (isSelected) 3.dp else 0.dp,
                                    color = if (isSelected) MaterialTheme.colorScheme.onBackground else Color.Transparent,
                                    shape = CircleShape,
                                )
                                .clickable { onSetTheme(id) },
                        )
                        Text(
                            label,
                            style = MaterialTheme.typography.labelSmall,
                            color = if (isSelected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                            fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
                            modifier = Modifier.padding(top = 4.dp),
                        )
                    }
                }
            }
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
        CuteCard {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(name, style = MaterialTheme.typography.titleSmall)
                OutlinedTextField(
                    config.apiKey,
                    { onUpdate(name, config.copy(apiKey = it)) },
                    label = { Text("API Key") },
                    modifier = Modifier.fillMaxWidth(),
                    visualTransformation = PasswordVisualTransformation(),
                    shape = RoundedCornerShape(12.dp),
                )
                OutlinedTextField(
                    config.baseUrl ?: "",
                    { onUpdate(name, config.copy(baseUrl = it.ifBlank { null })) },
                    label = { Text("Base URL") },
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                )
            }
        }
    }
    TextButton(onClick = onSave) { Text("保存 Provider 配置") }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ChannelsTab(
    state: SettingsUiState,
    onChange: (String, String, String) -> Unit,
    onSave: (String) -> Unit,
    onInstallLarkDeps: () -> Unit,
    onValidateKnowledge: (KnowledgeValidateRequest) -> Unit,
) {
    state.channels.forEach { channel ->
        CuteCard {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(channel.name, style = MaterialTheme.typography.titleSmall)
                channel.config.forEach { (key, value) ->
                    OutlinedTextField(
                        value,
                        { onChange(channel.id, key, it) },
                        label = { Text(key) },
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                    )
                }
                TextButton(onClick = { onSave(channel.id) }) { Text("保存") }

                if (channel.id == "lark") {
                    HorizontalDivider()
                    LarkDepsPanel(state, onInstallLarkDeps)
                }
            }
        }
    }

    KnowledgeValidatePanel(state, onValidateKnowledge)
}

@Composable
private fun LarkDepsPanel(state: SettingsUiState, onInstall: () -> Unit) {
    val deps = state.larkDepsStatus
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("飞书依赖状态", style = MaterialTheme.typography.labelLarge)
        if (deps == null) {
            Text("加载中…", style = MaterialTheme.typography.bodySmall)
            return
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            DepChip("oapi", deps.larkOapiInstalled)
            DepChip("cli", deps.larkCliInstalled)
            DepChip("app", deps.larkCliAppSynced)
        }
        if (deps.installing) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CircularProgressIndicator(strokeWidth = 2.dp)
                Text("安装中…", style = MaterialTheme.typography.bodySmall)
            }
        } else if (!deps.larkOapiInstalled || !deps.larkCliInstalled) {
            Button(onClick = onInstall) { Text("安装依赖") }
        }
        if (deps.lastError.isNotBlank()) {
            Text("错误: ${deps.lastError}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        }
    }
}

@Composable
private fun DepChip(label: String, ok: Boolean) {
    val color = if (ok) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error
    Text(
        "$label: ${if (ok) "✓" else "✗"}",
        style = MaterialTheme.typography.labelSmall,
        color = color,
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun KnowledgeValidatePanel(
    state: SettingsUiState,
    onValidate: (KnowledgeValidateRequest) -> Unit,
) {
    var showSheet by remember { mutableStateOf(false) }

    CuteCard {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("知识库连通性", style = MaterialTheme.typography.titleSmall)
            OutlinedButton(onClick = { showSheet = true }, modifier = Modifier.fillMaxWidth()) {
                Text("测试连接")
            }
        }
    }

    if (showSheet) {
        val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
        ModalBottomSheet(onDismissRequest = { showSheet = false }, sheetState = sheetState) {
            KnowledgeValidateSheet(
                validating = state.knowledgeValidating,
                onValidate = { req ->
                    onValidate(req)
                    showSheet = false
                },
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun KnowledgeValidateSheet(
    validating: Boolean,
    onValidate: (KnowledgeValidateRequest) -> Unit,
) {
    var backend by remember { mutableStateOf("filesystem") }
    var path by remember { mutableStateOf("") }
    var vault by remember { mutableStateOf("") }
    var folder by remember { mutableStateOf(".") }
    var endpoint by remember { mutableStateOf("") }
    var apiKey by remember { mutableStateOf("") }

    val backends = listOf("filesystem", "obsidian", "external")

    Column(
        Modifier.padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("知识库验证", style = MaterialTheme.typography.titleMedium)

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            backends.forEach { b ->
                val isSelected = backend == b
                Surface(
                    onClick = { backend = b },
                    shape = RoundedCornerShape(20.dp),
                    color = if (isSelected) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.surface,
                    border = BorderStroke(
                        1.dp,
                        if (isSelected) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.primary.copy(alpha = 0.2f),
                    ),
                ) {
                    Text(
                        b,
                        style = MaterialTheme.typography.labelMedium,
                        color = if (isSelected) MaterialTheme.colorScheme.onPrimary
                            else MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp),
                    )
                }
            }
        }

        when (backend) {
            "filesystem" -> OutlinedTextField(path, { path = it }, label = { Text("路径") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            "obsidian" -> {
                OutlinedTextField(vault, { vault = it }, label = { Text("Vault 路径") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
                OutlinedTextField(folder, { folder = it }, label = { Text("Folder") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            }
            "external" -> {
                OutlinedTextField(endpoint, { endpoint = it }, label = { Text("Endpoint") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
                OutlinedTextField(
                    apiKey,
                    { apiKey = it },
                    label = { Text("API Key") },
                    modifier = Modifier.fillMaxWidth(),
                    visualTransformation = PasswordVisualTransformation(),
                    shape = RoundedCornerShape(12.dp),
                )
            }
        }

        if (validating) {
            CircularProgressIndicator()
        } else {
            Button(
                onClick = {
                    onValidate(
                        KnowledgeValidateRequest(
                            backend = backend,
                            obsidianVaultPath = vault,
                            obsidianFolder = folder,
                            externalBaseUrl = endpoint,
                            externalApiKey = apiKey,
                        )
                    )
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("测试连接")
            }
        }
    }
}

@Composable
private fun SystemTextTab(title: String, content: String, onChange: (String) -> Unit, onSave: () -> Unit) {
    CuteCard {
        Column(Modifier.padding(16.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(content, onChange, modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp), minLines = 10, shape = RoundedCornerShape(12.dp))
            TextButton(onClick = onSave) { Text("保存") }
        }
    }
}

@Composable
private fun ProfileTab(content: String, onChange: (String) -> Unit, onSave: () -> Unit) {
    CuteCard {
        Column(Modifier.padding(16.dp)) {
            Text("我的画像", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(content, onChange, modifier = Modifier.fillMaxWidth(), minLines = 12, shape = RoundedCornerShape(12.dp))
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
                shape = RoundedCornerShape(12.dp),
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
        OutlinedTextField(name, { name = it }, label = { Text("名称") }, modifier = Modifier.weight(1f), shape = RoundedCornerShape(12.dp))
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

@Composable
private fun FastRulesTab(state: SettingsUiState) {
    val rules = state.fastRules
    val options = state.fastRuleOptions

    if (rules == null) {
        LoadingBox()
        return
    }

    CuteCard {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("快速基础工具 (fast_base_tools)", style = MaterialTheme.typography.titleSmall)
            if (rules.fastBaseTools.isEmpty()) {
                Text("（无）", style = MaterialTheme.typography.bodySmall)
            } else {
                rules.fastBaseTools.forEach { tool ->
                    Text("• $tool", style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
    }

    CuteCard {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Fast Rules (${rules.fastRules.size})", style = MaterialTheme.typography.titleSmall)
            if (rules.fastRules.isEmpty()) {
                Text("尚无规则", style = MaterialTheme.typography.bodySmall)
            } else {
                rules.fastRules.forEach { rule ->
                    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text(rule.name, style = MaterialTheme.typography.labelLarge)
                        if (rule.keywords.isNotEmpty()) {
                            Text("关键词: ${rule.keywords.joinToString(", ")}", style = MaterialTheme.typography.bodySmall)
                        }
                        if (rule.tools.isNotEmpty()) {
                            Text("工具: ${rule.tools.joinToString(", ")}", style = MaterialTheme.typography.bodySmall)
                        }
                        if (rule.skills.isNotEmpty()) {
                            Text("技能: ${rule.skills.joinToString(", ")}", style = MaterialTheme.typography.bodySmall)
                        }
                        HorizontalDivider()
                    }
                }
            }
        }
    }

    if (options != null) {
        CuteCard {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    "可挂载工具 (${options.tools.size}) · 已安装技能 (${options.skills.size})",
                    style = MaterialTheme.typography.labelMedium,
                )
                Text(
                    "在 Web 或桌面端编辑 Fast Rules 后此处自动刷新",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun ToolTiersTab(state: SettingsUiState) {
    val tiers = state.toolTiers

    if (tiers == null) {
        LoadingBox()
        return
    }

    CuteCard {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("汇总", style = MaterialTheme.typography.titleSmall)
            Text("Fast: ${tiers.fastCount} 工具 (含 Fast Rules: ${tiers.fastRuleToolCount})", style = MaterialTheme.typography.bodySmall)
            Text("Full: ${tiers.fullCount} 工具", style = MaterialTheme.typography.bodySmall)
            Text("Longtail: ${tiers.longtailCount} 工具", style = MaterialTheme.typography.bodySmall)
            Text("总计: ${tiers.totalCount}", style = MaterialTheme.typography.bodySmall)
        }
    }

    tiers.tiers.forEach { tier ->
        CuteCard {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("${tier.label} (${tier.tools.size})", style = MaterialTheme.typography.titleSmall)
                Text(tier.desc, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                HorizontalDivider()
                tier.tools.forEach { tool ->
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.Top,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(tool.name, style = MaterialTheme.typography.labelMedium)
                            if (tool.description.isNotBlank()) {
                                Text(
                                    tool.description.take(80) + if (tool.description.length > 80) "…" else "",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                        val flags = buildList {
                            if (tool.fastPath) add("fast")
                            if (tool.sideEffect) add("side")
                            if (tool.noCompress) add("raw")
                        }
                        if (flags.isNotEmpty()) {
                            Text(
                                flags.joinToString(" "),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.primary,
                            )
                        }
                    }
                }
            }
        }
    }
}

// ─── Previews ───

@Preview(showBackground = true, widthDp = 375, heightDp = 720, name = "ThemeTab · Honey")
@Composable
private fun ThemeTabPreviewHoney() {
    ThemeState.themeId = "honey"
    EthanTheme {
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.background,
        ) {
            Column(Modifier.padding(16.dp)) {
                CuteTopBar(title = "设置")
                Spacer(Modifier.height(8.dp))
                ThemeTab(themeId = "honey", onSetTheme = {})
            }
        }
    }
}

@Preview(showBackground = true, widthDp = 375, heightDp = 720, name = "ThemeTab · WarmOrange")
@Composable
private fun ThemeTabPreviewWarmOrange() {
    ThemeState.themeId = "warm_orange"
    EthanTheme {
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.background,
        ) {
            Column(Modifier.padding(16.dp)) {
                CuteTopBar(title = "设置")
                Spacer(Modifier.height(8.dp))
                ThemeTab(themeId = "warm_orange", onSetTheme = {})
            }
        }
    }
}

@Preview(showBackground = true, widthDp = 375, heightDp = 720, name = "ThemeTab · Qingwa")
@Composable
private fun ThemeTabPreviewQingwa() {
    ThemeState.themeId = "qingwa"
    EthanTheme {
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.background,
        ) {
            Column(Modifier.padding(16.dp)) {
                CuteTopBar(title = "设置")
                Spacer(Modifier.height(8.dp))
                ThemeTab(themeId = "qingwa", onSetTheme = {})
            }
        }
    }
}

