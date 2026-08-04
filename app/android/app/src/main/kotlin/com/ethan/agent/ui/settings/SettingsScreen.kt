package com.ethan.agent.ui.settings

import com.ethan.agent.shared.viewmodel.SettingsTab
import com.ethan.agent.shared.viewmodel.SettingsUiState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import android.widget.Toast
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.fragment.app.FragmentActivity
import com.ethan.agent.auth.BiometricLockManager
import com.ethan.agent.core.model.AgentSettings
import com.ethan.agent.core.model.KnowledgeValidateRequest
import com.ethan.agent.core.model.ProviderConfig
import com.ethan.agent.core.model.SystemSettings
import com.ethan.agent.ui.components.ErrorSnackbar
import com.ethan.agent.ui.components.EthanPrimaryButton
import com.ethan.agent.ui.components.EthanSecondaryButton
import com.ethan.agent.ui.components.EthanScrollableTabBar
import com.ethan.agent.ui.components.EthanTopBar
import com.ethan.agent.ui.components.LoadingBox
import com.ethan.agent.ui.components.SnackbarContainer
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    state: SettingsUiState,
    onBack: () -> Unit = {},
    onTabChange: (SettingsTab) -> Unit,
    onServerUrlChange: (String) -> Unit,
    onAuthTokenChange: (String) -> Unit,
    onSaveServerUrl: () -> Unit,
    onClearConnectionToast: () -> Unit,
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
    onSetAppLock: (Boolean) -> Unit = {},
    onClearCache: () -> Unit = {},
    onClearCacheCleared: () -> Unit = {},
    onClearError: () -> Unit,
) {
    val snackbar = remember { SnackbarHostState() }
    ErrorSnackbar(state.error, onClearError, snackbar)

    if (state.cacheCleared) {
        LaunchedEffect(Unit) {
            snackbar.showSnackbar("缓存已清空")
            onClearCacheCleared()
        }
    }

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
        topBar = { EthanTopBar(title = "设置", onBack = onBack) },
        snackbarHost = { SnackbarContainer(snackbar) },
    ) { padding ->
        val tabs = SettingsTab.entries.toList()
        val pagerState = rememberPagerState(pageCount = { tabs.size })
        val coroutineScope = rememberCoroutineScope()

        // 同步 Tab 点击与 Pager 页面
        LaunchedEffect(state.tab) {
            val index = tabs.indexOf(state.tab)
            if (index >= 0 && index != pagerState.currentPage && pagerState.currentPage != pagerState.targetPage) {
                // 只在 pager 不在动画中时程序化滚动，避免与用户手势冲突
                pagerState.animateScrollToPage(index)
            }
        }

        // 同步 Pager 滑动到 Tab 选中（跳过初始状态，避免覆盖已持久化的 tab）
        val isFirstPagerSync = remember { mutableStateOf(true) }
        LaunchedEffect(pagerState.currentPage) {
            if (isFirstPagerSync.value) {
                isFirstPagerSync.value = false
                // 初次进入：如果 state.tab 不是第0个 tab，同步 pager 到正确页面
                val initialIndex = tabs.indexOf(state.tab)
                if (initialIndex > 0) {
                    pagerState.scrollToPage(initialIndex)
                }
                return@LaunchedEffect
            }
            val index = pagerState.currentPage
            if (index >= 0 && index < tabs.size && tabs[index] != state.tab) {
                onTabChange(tabs[index])
            }
        }

        Column(Modifier.fillMaxSize().padding(padding)) {
            EthanScrollableTabBar(
                tabs = tabs,
                selectedTab = state.tab,
                onTabSelected = { tab ->
                    onTabChange(tab)
                    coroutineScope.launch {
                        pagerState.animateScrollToPage(tabs.indexOf(tab))
                    }
                },
                labelOf = { tab ->
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
                        SettingsTab.FastRules -> "Fast Rules"
                        SettingsTab.ToolTiers -> "路由档位"
                    }
                },
            )

            HorizontalPager(
                state = pagerState,
                modifier = Modifier.fillMaxSize(),
            ) { page ->
                val tab = tabs[page]
                Column(
                    Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    when (tab) {
                        SettingsTab.Connection -> ConnectionTab(state, onServerUrlChange, onAuthTokenChange, onSaveServerUrl, onClearConnectionToast)
                        SettingsTab.General -> {
                            if (state.isLoading && state.agentSettings == null) LoadingBox()
                            else state.agentSettings?.let {
                                GeneralTab(it, state.themeId, state.appLockEnabled, onUpdateAgent, onSaveAgent, onSetTheme, onCheckUpdate, onSetAppLock, onClearCache)
                            }
                        }
                        SettingsTab.Providers -> {
                            if (state.isLoading && state.providers.isEmpty()) LoadingBox()
                            else ProvidersTab(state.providers, onUpdateProvider, onSaveProviders)
                        }
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
                    }
                }
            }
        }
    }
}

@Composable
private fun ConnectionTab(
    state: SettingsUiState,
    onUrlChange: (String) -> Unit,
    onAuthTokenChange: (String) -> Unit,
    onSave: () -> Unit,
    onClearToast: () -> Unit,
) {
    val context = LocalContext.current
    // 测试并保存结果 → Toast 反馈
    LaunchedEffect(state.connectionToast) {
        state.connectionToast?.let {
            Toast.makeText(context, it, Toast.LENGTH_LONG).show()
            onClearToast()
        }
    }
    CuteCard {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("服务器连接", style = MaterialTheme.typography.titleSmall)
            OutlinedTextField(state.serverUrl, onUrlChange, label = { Text("服务器地址") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            OutlinedTextField(
                value = state.authToken,
                onValueChange = onAuthTokenChange,
                label = { Text("Access Token") },
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp),
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
            )
            state.serverVersion?.let { Text("版本: $it", style = MaterialTheme.typography.bodySmall) }
            EthanPrimaryButton("测试并保存", onClick = onSave, modifier = Modifier.fillMaxWidth())
            Text(
                "示例: http://192.168.1.100:8900 或 https://your-nas.com:8900",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

private val THEME_OPTIONS = listOf(
    "warm_orange" to "暖橙",
    "system" to "跟随系统",
    "light" to "浅色",
    "dark" to "深色",
    "qingwa" to "青瓦",
    "plain_paper" to "素纸",
    "mist" to "微雾",
)

@Composable
private fun GeneralTab(
    settings: AgentSettings,
    themeId: String,
    appLockEnabled: Boolean,
    onUpdate: (AgentSettings) -> Unit,
    onSave: () -> Unit,
    onSetTheme: (String) -> Unit,
    onCheckUpdate: () -> Unit,
    onSetAppLock: (Boolean) -> Unit,
    onClearCache: () -> Unit,
) {
    CuteCard {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            OutlinedTextField(settings.agentName, { onUpdate(settings.copy(agentName = it)) }, label = { Text("Agent 名称") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            OutlinedTextField(settings.defaultModel, { onUpdate(settings.copy(defaultModel = it)) }, label = { Text("默认模型") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            OutlinedTextField(settings.liteModel, { onUpdate(settings.copy(liteModel = it)) }, label = { Text("轻量模型") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            OutlinedTextField(settings.language, { onUpdate(settings.copy(language = it)) }, label = { Text("语言 (zh/en)") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("心跳")
                Switch(settings.heartbeatEnabled, { onUpdate(settings.copy(heartbeatEnabled = it)) })
            }
            EthanPrimaryButton("保存", onClick = onSave, modifier = Modifier.fillMaxWidth())
        }
    }

    CuteCard {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(0.dp)) {
            Text("主题", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(bottom = 4.dp))
            THEME_OPTIONS.forEach { (id, label) ->
                Row(
                    Modifier.fillMaxWidth().padding(vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(label, style = MaterialTheme.typography.bodyMedium)
                    if (themeId == id) {
                        Text("✓", color = MaterialTheme.colorScheme.primary)
                    } else {
                        TextButton(onClick = { onSetTheme(id) }) { Text("选择") }
                    }
                }
            }
        }
    }

    CuteCard {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("安全", style = MaterialTheme.typography.titleSmall)
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column(Modifier.weight(1f)) {
                    Text("应用锁", style = MaterialTheme.typography.bodyMedium)
                    Text(
                        "启动时用生物识别或设备密码解锁",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                val context = LocalContext.current
                Switch(
                    checked = appLockEnabled,
                    onCheckedChange = onAppLockToggle@{ enabled ->
                        // 打开前校验设备确有可用凭据；无凭据则提示并阻止打开，
                        // 避免「开关开着但设备没锁屏密码 → 解锁时静默放行」的矛盾状态。
                        if (enabled) {
                            val activity = context as? FragmentActivity
                            if (activity == null || !BiometricLockManager.canAuthenticate(activity)) {
                                Toast.makeText(
                                    context,
                                    "请先在系统设置中设置锁屏密码或生物识别",
                                    Toast.LENGTH_LONG,
                                ).show()
                                return@onAppLockToggle
                            }
                        }
                        onSetAppLock(enabled)
                    },
                )
            }
        }
    }

    CuteCard {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("系统", style = MaterialTheme.typography.titleSmall)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                val context = LocalContext.current
                EthanSecondaryButton(
                    text = "检查更新",
                    onClick = {
                        Toast.makeText(context, "正在检查更新…", Toast.LENGTH_SHORT).show()
                        onCheckUpdate()
                    },
                    modifier = Modifier.weight(1f),
                )
                EthanSecondaryButton(
                    text = "清空缓存",
                    onClick = onClearCache,
                    modifier = Modifier.weight(1f),
                )
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
            Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
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
    EthanPrimaryButton("保存 Provider 配置", onClick = onSave, modifier = Modifier.fillMaxWidth())
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
            Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
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

                if (channel.id == "lark") {
                    HorizontalDivider(Modifier.padding(vertical = 4.dp))
                    LarkDepsStatus(state)
                    Spacer(Modifier.height(4.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        EthanSecondaryButton(
                            text = "测试依赖状态",
                            onClick = onInstallLarkDeps,
                            modifier = Modifier.weight(1f),
                        )
                        EthanPrimaryButton(
                            text = "保存并启用",
                            onClick = { onSave(channel.id) },
                            modifier = Modifier.weight(1f),
                        )
                    }
                } else {
                    EthanPrimaryButton("保存", onClick = { onSave(channel.id) }, modifier = Modifier.fillMaxWidth())
                }
            }
        }
    }

    KnowledgeValidatePanel(state, onValidateKnowledge)
}

@Composable
private fun LarkDepsStatus(state: SettingsUiState) {
    val deps = state.larkDepsStatus
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("飞书依赖状态", style = MaterialTheme.typography.labelLarge)
        if (deps == null) {
            Text("加载中…", style = MaterialTheme.typography.bodySmall)
            return
        }
        Surface(
            shape = RoundedCornerShape(8.dp),
            color = androidx.compose.ui.graphics.Color(0xFF1A1A1A),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                DepChip("oapi", deps.larkOapiInstalled, onDark = true)
                DepChip("cli", deps.larkCliInstalled, onDark = true)
                DepChip("app", deps.larkCliAppSynced, onDark = true)
            }
        }
        if (deps.installing) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(16.dp))
                Text("安装中…", style = MaterialTheme.typography.bodySmall)
            }
        }
        if (deps.lastError.isNotBlank()) {
            Text("错误: ${deps.lastError}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        }
    }
}

@Composable
private fun DepChip(label: String, ok: Boolean, onDark: Boolean = false) {
    val color = if (ok) androidx.compose.ui.graphics.Color(0xFF4CAF50) else MaterialTheme.colorScheme.error
    val icon = if (ok) "✓" else "✗"
    Text(
        "$label: $icon",
        style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.Medium),
        color = if (onDark) androidx.compose.ui.graphics.Color.White else color,
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
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("知识库连通性", style = MaterialTheme.typography.titleSmall)
            EthanSecondaryButton("测试连接", onClick = { showSheet = true }, modifier = Modifier.fillMaxWidth())
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
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                CircularProgressIndicator()
            }
        } else {
            EthanPrimaryButton(
                text = "测试连接",
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
            )
        }
    }
}

@Composable
private fun SystemTextTab(title: String, content: String, onChange: (String) -> Unit, onSave: () -> Unit) {
    CuteCard {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall)
            OutlinedTextField(content, onChange, modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp), minLines = 10, shape = RoundedCornerShape(12.dp))
            EthanPrimaryButton("保存", onClick = onSave, modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun ProfileTab(content: String, onChange: (String) -> Unit, onSave: () -> Unit) {
    CuteCard {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp)) {
            Text("我的画像", style = MaterialTheme.typography.titleSmall)
            OutlinedTextField(content, onChange, modifier = Modifier.fillMaxWidth(), minLines = 12, shape = RoundedCornerShape(12.dp))
            EthanPrimaryButton("保存", onClick = onSave, modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun PromptPreviewTab(state: SettingsUiState, onLoad: () -> Unit) {
    Column {
        EthanSecondaryButton("加载预览", onClick = onLoad, modifier = Modifier.fillMaxWidth())
        state.promptPreview?.let { preview ->
            Spacer(Modifier.height(8.dp))
            Text("约 ${preview.approxTotalTokens} tokens · ${preview.toolCount} 工具", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(4.dp))
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
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        OutlinedTextField(
            name, { name = it },
            label = { Text("名称") },
            modifier = Modifier.weight(1f),
            shape = RoundedCornerShape(12.dp),
        )
        EthanPrimaryButton("创建", onClick = { onCreate(name); name = "" })
    }
    Spacer(Modifier.height(8.dp))
    state.apiKeys.forEach { key ->
        Row(
            Modifier.fillMaxWidth().padding(vertical = 4.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(key.name, style = MaterialTheme.typography.bodyMedium)
                Text(key.keyPreview, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
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
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
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
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
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
            Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
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

@Composable
private fun CuteCard(content: @Composable () -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.primary.copy(alpha = 0.1f)),
        shadowElevation = 1.dp,
    ) {
        content()
    }
}
