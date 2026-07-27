package com.ethan.agent.ui.annotations

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.Annotation
import com.ethan.agent.data.EthanRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class AnnotationsUiState(
    /** messageId (String) → list of annotations */
    val groupedByMessage: Map<String, List<Annotation>> = emptyMap(),
    val isLoading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class AnnotationsViewModel @Inject constructor(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(AnnotationsUiState())
    val state: StateFlow<AnnotationsUiState> = _state.asStateFlow()

    // In-memory tracking of known message IDs — populated by callers (e.g. ChatScreen)
    private val knownMessageIds = mutableSetOf<Long>()

    init { /* Callers invoke loadForMessages() after providing IDs */ }

    fun loadForMessages(messageIds: List<Long>) {
        if (messageIds.isEmpty()) return
        knownMessageIds.addAll(messageIds)
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            try {
                val resp = repository.batchGetAnnotations(messageIds)
                _state.update { it.copy(groupedByMessage = resp, isLoading = false) }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun deleteAnnotation(annoId: Long) {
        viewModelScope.launch {
            try {
                repository.deleteAnnotation(annoId)
                // Remove from state optimistically
                _state.update { s ->
                    s.copy(
                        groupedByMessage = s.groupedByMessage.mapValues { (_, list) ->
                            list.filter { it.id.toLong() != annoId }
                        }.filterValues { it.isNotEmpty() },
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun clearError() { _state.update { it.copy(error = null) } }
}
