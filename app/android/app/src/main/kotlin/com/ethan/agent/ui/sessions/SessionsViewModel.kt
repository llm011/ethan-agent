package com.ethan.agent.ui.sessions

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.SessionInfo
import com.ethan.agent.data.EthanRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SessionsUiState(
    val sessions: List<SessionInfo> = emptyList(),
    val query: String = "",
    val isLoading: Boolean = false,
    val error: String? = null,
    val renameTarget: SessionInfo? = null,
    val renameText: String = "",
)

@HiltViewModel
class SessionsViewModel @Inject constructor(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(SessionsUiState())
    val state: StateFlow<SessionsUiState> = _state.asStateFlow()
    private var pollJob: Job? = null

    init {
        load()
        startPolling()
    }

    private fun startPolling() {
        pollJob?.cancel()
        pollJob = viewModelScope.launch {
            while (isActive) {
                delay(3000)
                if (_state.value.query.isBlank()) {
                    refreshQuietly()
                }
            }
        }
    }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            try {
                val sessions = repository.getSessions(limit = 50, query = _state.value.query.ifBlank { null })
                _state.update { it.copy(sessions = sessions, isLoading = false) }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    private suspend fun refreshQuietly() {
        try {
            val sessions = repository.poll()
            if (_state.value.query.isBlank()) {
                _state.update { it.copy(sessions = sessions) }
            }
        } catch (_: Exception) {
        }
    }

    fun onQueryChange(query: String) {
        _state.update { it.copy(query = query) }
        viewModelScope.launch {
            delay(300)
            load()
        }
    }

    fun startRename(session: SessionInfo) {
        _state.update { it.copy(renameTarget = session, renameText = session.title) }
    }

    fun onRenameTextChange(text: String) {
        _state.update { it.copy(renameText = text) }
    }

    fun confirmRename() {
        val target = _state.value.renameTarget ?: return
        viewModelScope.launch {
            try {
                repository.renameSession(target.id, _state.value.renameText)
                _state.update { it.copy(renameTarget = null) }
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun cancelRename() {
        _state.update { it.copy(renameTarget = null) }
    }

    fun deleteSession(id: String) {
        viewModelScope.launch {
            try {
                repository.deleteSession(id)
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun clearError() {
        _state.update { it.copy(error = null) }
    }
}
