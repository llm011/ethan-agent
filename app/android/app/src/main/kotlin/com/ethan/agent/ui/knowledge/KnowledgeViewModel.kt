package com.ethan.agent.ui.knowledge

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.KnowledgeItem
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

data class KnowledgeUiState(
    val items: List<KnowledgeItem> = emptyList(),
    val query: String = "",
    val semanticSearch: Boolean = true,
    val selected: KnowledgeItem? = null,
    val title: String = "",
    val content: String = "",
    val tags: String = "",
    val isCreating: Boolean = false,
    val isLoading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class KnowledgeViewModel @Inject constructor(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(KnowledgeUiState())
    val state: StateFlow<KnowledgeUiState> = _state.asStateFlow()
    private var searchJob: Job? = null

    init { load() }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val q = _state.value.query
                val items = if (q.isBlank()) {
                    repository.getKnowledge()
                } else if (_state.value.semanticSearch) {
                    repository.searchKnowledge(q)
                } else {
                    repository.getKnowledge(q, "keyword")
                }
                _state.update { it.copy(items = items, isLoading = false) }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun onQueryChange(query: String) {
        _state.update { it.copy(query = query) }
        searchJob?.cancel()
        searchJob = viewModelScope.launch {
            delay(300)
            load()
        }
    }

    fun toggleSemantic() {
        _state.update { it.copy(semanticSearch = !it.semanticSearch) }
        load()
    }

    fun selectItem(item: KnowledgeItem) {
        _state.update {
            it.copy(
                selected = item,
                isCreating = false,
                title = item.title,
                content = item.content ?: "",
                tags = item.tags?.joinToString(", ") ?: "",
            )
        }
    }

    fun startCreate() {
        _state.update {
            it.copy(selected = null, isCreating = true, title = "", content = "", tags = "")
        }
    }

    fun onTitleChange(v: String) { _state.update { it.copy(title = v) } }
    fun onContentChange(v: String) { _state.update { it.copy(content = v) } }
    fun onTagsChange(v: String) { _state.update { it.copy(tags = v) } }

    fun save() {
        viewModelScope.launch {
            try {
                val tags = _state.value.tags.split(",").map { it.trim() }.filter { it.isNotEmpty() }
                if (_state.value.isCreating) {
                    repository.addKnowledge(_state.value.title, _state.value.content, tags)
                } else {
                    val source = _state.value.selected?.source ?: return@launch
                    repository.updateKnowledge(source, _state.value.title, _state.value.content, tags)
                }
                _state.update { it.copy(isCreating = false, selected = null) }
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun delete() {
        val source = _state.value.selected?.source ?: return
        viewModelScope.launch {
            try {
                repository.deleteKnowledge(source)
                _state.update { it.copy(selected = null) }
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun clearError() { _state.update { it.copy(error = null) } }
}
