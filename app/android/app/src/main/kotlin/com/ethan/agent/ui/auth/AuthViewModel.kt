package com.ethan.agent.ui.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.datastore.AppConfig
import com.ethan.agent.data.EthanRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

data class AuthUiState(
    val config: AppConfig = AppConfig(),
    val isLoading: Boolean = true,
    val isAuthenticated: Boolean = false,
    val error: String? = null,
    val serverVersion: String? = null,
    val darkTheme: Boolean? = null,
)

@HiltViewModel
class AuthViewModel @Inject constructor(
    private val repository: EthanRepository,
) : ViewModel() {
    private val loading = MutableStateFlow(true)
    private val authenticated = MutableStateFlow(false)
    private val error = MutableStateFlow<String?>(null)
    private val serverVersion = MutableStateFlow<String?>(null)

    val state: StateFlow<AuthUiState> = combine(
        repository.config,
        loading,
        authenticated,
        error,
        serverVersion,
    ) { config, isLoading, isAuth, err, version ->
        AuthUiState(
            config = config,
            isLoading = isLoading,
            isAuthenticated = isAuth,
            error = err,
            serverVersion = version,
            darkTheme = config.darkTheme,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), AuthUiState(isLoading = true))

    init {
        viewModelScope.launch {
            repository.repairStoredUrlIfNeeded()
            val config = repository.config.stateIn(viewModelScope).value
            if (config.authToken.isNotBlank()) {
                verifyExistingToken()
            } else {
                loading.value = false
            }
        }
    }

    private suspend fun verifyExistingToken() {
        loading.value = true
        val token = repository.config.stateIn(viewModelScope).value.authToken
        val result = repository.login(token)
        authenticated.value = result.isSuccess
        if (result.isFailure) {
            repository.logout()
        }
        serverVersion.value = repository.checkHealth()
        loading.value = false
    }

    fun saveServerUrl(url: String) {
        viewModelScope.launch {
            error.value = null
            runCatching { repository.saveServerUrl(url) }
                .onSuccess { serverVersion.value = repository.checkHealth() }
                .onFailure { error.value = it.message ?: "无效的服务器地址" }
        }
    }

    fun login(token: String, serverUrl: String) {
        viewModelScope.launch {
            loading.value = true
            error.value = null
            val result = runCatching {
                repository.login(token, serverUrl)
            }.getOrElse {
                Result.failure(it)
            }
            result.onSuccess {
                authenticated.value = true
                serverVersion.value = repository.checkHealth()
            }.onFailure {
                authenticated.value = false
                error.value = when (it) {
                    is IllegalArgumentException -> it.message ?: "无效的服务器地址"
                    else -> repository.friendlyError(it)
                }
            }
            loading.value = false
        }
    }

    fun logout() {
        viewModelScope.launch {
            repository.logout()
            authenticated.value = false
        }
    }

    fun clearError() {
        error.value = null
    }

    fun toggleTheme(dark: Boolean) {
        viewModelScope.launch {
            repository.setDarkTheme(dark)
        }
    }
}
