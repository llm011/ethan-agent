package com.ethan.agent.ui.schedule

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.ScheduleJob
import com.ethan.agent.data.EthanRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ScheduleUiState(
    val jobs: List<ScheduleJob> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class ScheduleViewModel @Inject constructor(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(ScheduleUiState())
    val state: StateFlow<ScheduleUiState> = _state.asStateFlow()

    init { load() }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val jobs = repository.getSchedules()
                _state.update { it.copy(jobs = jobs, isLoading = false) }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun toggleJob(job: ScheduleJob) {
        viewModelScope.launch {
            try {
                val newState = if (job.status == "active") "paused" else "active"
                repository.patchSchedule(job.id, newState)
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun deleteJob(id: String) {
        viewModelScope.launch {
            try {
                repository.deleteSchedule(id)
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun clearError() { _state.update { it.copy(error = null) } }
}
