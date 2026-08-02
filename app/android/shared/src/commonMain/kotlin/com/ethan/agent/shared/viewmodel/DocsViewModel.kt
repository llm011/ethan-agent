package com.ethan.agent.shared.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.DocMeta
import com.ethan.agent.shared.EthanRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class DocsUiState(
    val docs: List<DocMeta> = emptyList(),
    val selectedSlug: String? = null,
    val content: String = "",
    val isLoading: Boolean = false,
    val error: String? = null,
)

class DocsViewModel(
    private val repository: EthanRepository,
    slug: String?,
) : ViewModel() {
    private val _state = MutableStateFlow(DocsUiState())
    val state: StateFlow<DocsUiState> = _state.asStateFlow()

    init {
        load(slug)
    }

    fun load(slug: String? = null) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val docs = repository.getDocsList()
                if (slug != null) {
                    val doc = repository.getDoc(slug)
                    _state.update { it.copy(docs = docs, selectedSlug = slug, content = doc.content, isLoading = false) }
                } else {
                    _state.update { it.copy(docs = docs, isLoading = false) }
                }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun selectDoc(slug: String) {
        viewModelScope.launch {
            try {
                val doc = repository.getDoc(slug)
                _state.update { it.copy(selectedSlug = slug, content = doc.content) }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun clearError() { _state.update { it.copy(error = null) } }
}
