package com.ethan.agent.shared.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.BackgroundTask
import com.ethan.agent.shared.EthanRepository
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

data class BackgroundTasksUiState(
    val tasks: List<BackgroundTask> = emptyList(),
    val stoppingIds: Set<String> = emptySet(),
    val isLoading: Boolean = false,
    val error: String? = null,
) {
    val hasRunning: Boolean get() = tasks.any { it.status == "running" }
}

class BackgroundTasksViewModel(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(BackgroundTasksUiState())
    val state: StateFlow<BackgroundTasksUiState> = _state.asStateFlow()
    private var pollJob: Job? = null

    init { load() }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            try {
                val tasks = repository.getBackgroundTasks()
                _state.update { it.copy(tasks = tasks, isLoading = false) }
                if (tasks.any { it.status == "running" }) startPolling() else stopPolling()
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    private fun startPolling() {
        if (pollJob?.isActive == true) return
        pollJob = viewModelScope.launch {
            while (isActive) {
                delay(3_000)
                try {
                    val tasks = repository.getBackgroundTasks()
                    _state.update { it.copy(tasks = tasks) }
                    if (tasks.none { it.status == "running" }) break
                } catch (_: Exception) {}
            }
        }
    }

    private fun stopPolling() {
        pollJob?.cancel()
        pollJob = null
    }

    fun stopTask(id: String) {
        viewModelScope.launch {
            _state.update { it.copy(stoppingIds = it.stoppingIds + id) }
            try {
                repository.stopBackgroundTask(id)
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            } finally {
                _state.update { it.copy(stoppingIds = it.stoppingIds - id) }
            }
        }
    }

    fun clearError() { _state.update { it.copy(error = null) } }

    override fun onCleared() {
        super.onCleared()
        stopPolling()
    }
}
