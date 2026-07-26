package com.ethan.agent.ui.logs

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.data.EthanRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class LogsUiState(
    val type: String = "backend",
    val query: String = "",
    val lines: Int = 500,
    val content: String = "",
    val isLoading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class LogsViewModel @Inject constructor(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(LogsUiState())
    val state: StateFlow<LogsUiState> = _state.asStateFlow()

    private var queryJob: Job? = null

    init { load() }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            try {
                val s = _state.value
                val content = repository.getLogs(s.type, s.lines, s.query.takeIf { it.isNotBlank() })
                _state.update { it.copy(content = content, isLoading = false) }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun setType(type: String) {
        _state.update { it.copy(type = type) }
        load()
    }

    fun onQueryChange(q: String) {
        _state.update { it.copy(query = q) }
        // 300ms debounce，避免边输入边请求
        queryJob?.cancel()
        queryJob = viewModelScope.launch {
            delay(300)
            load()
        }
    }

    fun clearError() { _state.update { it.copy(error = null) } }
}
