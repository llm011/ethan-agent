package com.ethan.agent.ui.logs

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.data.EthanRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class LogsUiState(
    val content: String = "",
    val type: String = "backend",
    val query: String = "",
    val isLoading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class LogsViewModel @Inject constructor(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(LogsUiState())
    val state: StateFlow<LogsUiState> = _state.asStateFlow()

    init { load() }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val content = repository.getLogs(
                    type = _state.value.type,
                    query = _state.value.query.ifBlank { null },
                )
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

    fun onQueryChange(query: String) {
        _state.update { it.copy(query = query) }
    }

    fun clearError() { _state.update { it.copy(error = null) } }
}
