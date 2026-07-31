package com.ethan.agent.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.AgentSettings
import com.ethan.agent.core.model.ApiKeyCreated
import com.ethan.agent.core.model.ApiKeyInfo
import com.ethan.agent.core.model.ChannelInfo
import com.ethan.agent.core.model.FastRuleOptionsResponse
import com.ethan.agent.core.model.FastRulesPatch
import com.ethan.agent.core.model.FastRulesResponse
import com.ethan.agent.core.model.KnowledgeValidateRequest
import com.ethan.agent.core.model.LarkDepsStatus
import com.ethan.agent.core.model.ProviderConfig
import com.ethan.agent.core.model.SystemPromptPreview
import com.ethan.agent.core.model.SystemSettings
import com.ethan.agent.core.model.ToolTiersResponse
import com.ethan.agent.data.EthanRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

enum class SettingsTab {
    Connection, General, Providers, Channels, Identity, Soul, Tools, Heartbeat, Profile, PromptPreview, ApiKeys,
    FastRules, ToolTiers,
}

data class SettingsUiState(
    val tab: SettingsTab = SettingsTab.Connection,
    val serverUrl: String = "",
    val serverVersion: String? = null,
    val agentSettings: AgentSettings? = null,
    val providers: Map<String, ProviderConfig> = emptyMap(),
    val systemSettings: SystemSettings? = null,
    val profile: String = "",
    val channels: List<ChannelInfo> = emptyList(),
    val apiKeys: List<ApiKeyInfo> = emptyList(),
    val promptPreview: SystemPromptPreview? = null,
    val newApiKey: ApiKeyCreated? = null,
    val isLoading: Boolean = false,
    val saved: Boolean = false,
    val error: String? = null,
    // Fast Rules
    val fastRules: FastRulesResponse? = null,
    val fastRuleOptions: FastRuleOptionsResponse? = null,
    // Tool Tiers
    val toolTiers: ToolTiersResponse? = null,
    // Lark Deps
    val larkDepsStatus: LarkDepsStatus? = null,
    // Knowledge Validate
    val knowledgeValidating: Boolean = false,
    val knowledgeValidateResult: String? = null,
    // Theme
    val themeId: String = "honey",
    // App lock (biometric)
    val appLockEnabled: Boolean = false,
    // Cache
    val cacheCleared: Boolean = false,
)

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(SettingsUiState())
    val state: StateFlow<SettingsUiState> = _state.asStateFlow()

    private var larkPollJob: Job? = null

    init {
        viewModelScope.launch {
            repository.config.collect { config ->
                _state.update {
                    it.copy(
                        serverUrl = config.serverUrl,
                        themeId = config.themeId,
                        appLockEnabled = config.appLockEnabled,
                    )
                }
            }
        }
        load()
    }

    fun setTab(tab: SettingsTab) {
        _state.update { it.copy(tab = tab) }
        when (tab) {
            SettingsTab.ApiKeys -> if (_state.value.apiKeys.isEmpty()) loadApiKeys()
            SettingsTab.FastRules -> if (_state.value.fastRules == null) loadFastRules()
            SettingsTab.ToolTiers -> if (_state.value.toolTiers == null) loadToolTiers()
            SettingsTab.Channels -> loadLarkDepsStatus()
            else -> Unit
        }
    }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }

            // agentSettings 和 systemSettings 用 cached flow，先秒出缓存，再后台刷新
            launch {
                try {
                    repository.cachedAgentSettings().collect { agent ->
                        _state.update { it.copy(agentSettings = agent, isLoading = false) }
                    }
                } catch (e: Exception) {
                    _state.update { it.copy(error = repository.friendlyError(e), isLoading = false) }
                }
            }
            launch {
                try {
                    repository.cachedSystemSettings().collect { system ->
                        _state.update { it.copy(systemSettings = system) }
                    }
                } catch (_: Exception) { }
            }

            // 其余设置并行请求，避免服务器不可达时串行 30s×N 的死等
            launch {
                coroutineScope {
                    val versionDef = async { runCatching { repository.checkHealth() }.getOrNull() }
                    val providersDef = async { runCatching { repository.getProviderSettings() }.getOrDefault(emptyMap()) }
                    val profileDef = async { runCatching { repository.getUserProfile() }.getOrDefault("") }
                    val channelsDef = async { runCatching { repository.getChannels() }.getOrDefault(emptyList()) }
                    // API Keys 单独加载，失败不阻塞其他设置
                    val keysDef = async { runCatching { repository.getApiKeys() }.getOrDefault(emptyList()) }

                    val version = versionDef.await()
                    val providers = providersDef.await()
                    val profile = profileDef.await()
                    val channels = channelsDef.await()
                    val keys = keysDef.await()

                    _state.update {
                        it.copy(
                            serverVersion = version,
                            providers = providers,
                            profile = profile,
                            channels = channels,
                            apiKeys = keys,
                            isLoading = false,
                        )
                    }
                }
            }
        }
    }

    fun loadApiKeys() {
        viewModelScope.launch {
            runCatching { repository.getApiKeys() }
                .onSuccess { keys -> _state.update { it.copy(apiKeys = keys) } }
                .onFailure { e -> _state.update { it.copy(error = repository.friendlyError(e)) } }
        }
    }

    fun loadFastRules() {
        viewModelScope.launch {
            runCatching {
                val rules = repository.getFastRules()
                val options = repository.getFastRuleOptions()
                _state.update { it.copy(fastRules = rules, fastRuleOptions = options) }
            }.onFailure { e ->
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun updateFastRules(patch: FastRulesPatch) {
        viewModelScope.launch {
            runCatching { repository.updateFastRules(patch) }
                .onSuccess { loadFastRules() }
                .onFailure { e -> _state.update { it.copy(error = repository.friendlyError(e)) } }
        }
    }

    fun loadToolTiers() {
        viewModelScope.launch {
            runCatching { repository.getToolTiers() }
                .onSuccess { tiers -> _state.update { it.copy(toolTiers = tiers) } }
                .onFailure { e -> _state.update { it.copy(error = repository.friendlyError(e)) } }
        }
    }

    fun loadLarkDepsStatus() {
        viewModelScope.launch {
            runCatching { repository.getLarkDepsStatus() }
                .onSuccess { status ->
                    _state.update { it.copy(larkDepsStatus = status) }
                    if (status.installing) startLarkDepsPolling()
                }
                .onFailure { /* silent — Lark may not be configured */ }
        }
    }

    fun installLarkDeps() {
        viewModelScope.launch {
            runCatching { repository.installLarkDeps() }
                .onSuccess {
                    _state.update { it.copy(larkDepsStatus = it.larkDepsStatus?.copy(installing = true)) }
                    startLarkDepsPolling()
                }
                .onFailure { e -> _state.update { it.copy(error = repository.friendlyError(e)) } }
        }
    }

    private fun startLarkDepsPolling() {
        larkPollJob?.cancel()
        larkPollJob = viewModelScope.launch {
            while (true) {
                delay(2_000)
                val status = runCatching { repository.getLarkDepsStatus() }.getOrNull() ?: break
                _state.update { it.copy(larkDepsStatus = status) }
                if (!status.installing) break
            }
            larkPollJob = null
        }
    }

    fun validateKnowledge(request: KnowledgeValidateRequest) {
        viewModelScope.launch {
            _state.update { it.copy(knowledgeValidating = true, knowledgeValidateResult = null) }
            runCatching { repository.validateKnowledgeBackend(request) }
                .onSuccess { resp ->
                    val msg = if (resp.ok) "连接成功：${resp.message}" else "失败：${resp.message}"
                    _state.update { it.copy(knowledgeValidateResult = msg) }
                }
                .onFailure { e ->
                    _state.update { it.copy(knowledgeValidateResult = "错误：${repository.friendlyError(e)}") }
                }
            _state.update { it.copy(knowledgeValidating = false) }
        }
    }

    fun clearKnowledgeValidateResult() {
        _state.update { it.copy(knowledgeValidateResult = null) }
    }

    fun setTheme(themeId: String) {
        // 只更新本地 UI 态（settings 页里的 ✓）+ 持久化；全局主题由 config flow 驱动，
        // MainActivity 观察 config.themeId 应用到 EthanTheme，单向数据流不再直写全局可变状态。
        _state.update { it.copy(themeId = themeId) }
        viewModelScope.launch { runCatching { repository.setThemeId(themeId) } }
    }

    fun setAppLockEnabled(enabled: Boolean) {
        _state.update { it.copy(appLockEnabled = enabled) }
        viewModelScope.launch { runCatching { repository.setAppLockEnabled(enabled) } }
    }

    fun clearCache() {
        viewModelScope.launch {
            runCatching { repository.clearLocalCache() }
                .onSuccess { _state.update { it.copy(cacheCleared = true) } }
                .onFailure { e -> _state.update { it.copy(error = repository.friendlyError(e)) } }
        }
    }

    fun clearCacheCleared() { _state.update { it.copy(cacheCleared = false) } }

    fun onServerUrlChange(url: String) {
        _state.update { it.copy(serverUrl = url) }
    }

    fun saveServerUrl() {
        viewModelScope.launch {
            try {
                repository.saveServerUrl(_state.value.serverUrl)
                _state.update { it.copy(saved = true, serverVersion = repository.checkHealth()) }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun updateAgent(patch: AgentSettings) {
        _state.update { it.copy(agentSettings = patch) }
    }

    fun saveAgent() {
        val settings = _state.value.agentSettings ?: return
        viewModelScope.launch {
            try {
                repository.updateAgentSettings(settings)
                _state.update { it.copy(saved = true) }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun updateProvider(name: String, config: ProviderConfig) {
        _state.update {
            it.copy(providers = it.providers.toMutableMap().apply { put(name, config) })
        }
    }

    fun saveProviders() {
        viewModelScope.launch {
            try {
                repository.updateProviderSettings(_state.value.providers)
                _state.update { it.copy(saved = true) }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun updateSystem(patch: SystemSettings) {
        _state.update { it.copy(systemSettings = patch) }
    }

    fun saveSystem() {
        val settings = _state.value.systemSettings ?: return
        viewModelScope.launch {
            try {
                repository.updateSystemSettings(settings)
                _state.update { it.copy(saved = true) }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun onProfileChange(content: String) {
        _state.update { it.copy(profile = content) }
    }

    fun saveProfile() {
        viewModelScope.launch {
            try {
                repository.updateUserProfile(_state.value.profile)
                _state.update { it.copy(saved = true) }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun updateChannel(channelId: String, key: String, value: String) {
        val channels = _state.value.channels.map { ch ->
            if (ch.id == channelId) ch.copy(config = ch.config.toMutableMap().apply { put(key, value) })
            else ch
        }
        _state.update { it.copy(channels = channels) }
    }

    fun saveChannel(channelId: String) {
        val channel = _state.value.channels.find { it.id == channelId } ?: return
        viewModelScope.launch {
            try {
                repository.patchChannel(channelId, channel.config)
                _state.update { it.copy(saved = true) }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun loadPromptPreview() {
        viewModelScope.launch {
            try {
                val preview = repository.getSystemPromptPreview()
                _state.update { it.copy(promptPreview = preview) }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun createApiKey(name: String) {
        viewModelScope.launch {
            try {
                val created = repository.createApiKey(name)
                _state.update { it.copy(newApiKey = created, apiKeys = repository.getApiKeys()) }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun dismissNewApiKey() {
        _state.update { it.copy(newApiKey = null) }
    }

    fun deleteApiKey(id: String) {
        viewModelScope.launch {
            try {
                repository.deleteApiKey(id)
                _state.update { it.copy(apiKeys = repository.getApiKeys()) }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun clearSaved() { _state.update { it.copy(saved = false) } }
    fun clearError() { _state.update { it.copy(error = null) } }
}
