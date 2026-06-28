package com.ethan.agent.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.AgentSettings
import com.ethan.agent.core.model.ApiKeyCreated
import com.ethan.agent.core.model.ApiKeyInfo
import com.ethan.agent.core.model.ChannelInfo
import com.ethan.agent.core.model.ProviderConfig
import com.ethan.agent.core.model.SystemPromptPreview
import com.ethan.agent.core.model.SystemSettings
import com.ethan.agent.data.EthanRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

enum class SettingsTab {
    Connection, General, Providers, Channels, Identity, Soul, Tools, Heartbeat, Profile, PromptPreview, ApiKeys,
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
)

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(SettingsUiState())
    val state: StateFlow<SettingsUiState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            repository.config.collect { config ->
                _state.update { it.copy(serverUrl = config.serverUrl) }
            }
        }
        load()
    }

    fun setTab(tab: SettingsTab) {
        _state.update { it.copy(tab = tab) }
        if (tab == SettingsTab.ApiKeys && _state.value.apiKeys.isEmpty()) {
            loadApiKeys()
        }
    }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            var error: String? = null

            val version = runCatching { repository.checkHealth() }.getOrNull()
            val agent = runCatching { repository.getAgentSettings() }
                .onFailure { error = repository.friendlyError(it) }.getOrNull()
            val providers = runCatching { repository.getProviderSettings() }
                .onFailure { if (error == null) error = repository.friendlyError(it) }.getOrDefault(emptyMap())
            val system = runCatching { repository.getSystemSettings() }
                .onFailure { if (error == null) error = repository.friendlyError(it) }.getOrNull()
            val profile = runCatching { repository.getUserProfile() }
                .onFailure { if (error == null) error = repository.friendlyError(it) }.getOrDefault("")
            val channels = runCatching { repository.getChannels() }
                .onFailure { if (error == null) error = repository.friendlyError(it) }.getOrDefault(emptyList())
            val keys = runCatching { repository.getApiKeys() }
                .onFailure { /* API Keys 单独加载，失败不阻塞其他设置 */ }.getOrDefault(emptyList())

            _state.update {
                it.copy(
                    serverVersion = version,
                    agentSettings = agent,
                    providers = providers,
                    systemSettings = system,
                    profile = profile,
                    channels = channels,
                    apiKeys = keys,
                    isLoading = false,
                    error = error,
                )
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
