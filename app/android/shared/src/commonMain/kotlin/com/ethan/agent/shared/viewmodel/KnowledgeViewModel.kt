package com.ethan.agent.shared.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.KnowledgeItem
import com.ethan.agent.shared.EthanRepository
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class KnowledgeUiState(
    val items: List<KnowledgeItem> = emptyList(),
    val query: String = "",
    val semanticSearch: Boolean = true,
    val selected: KnowledgeItem? = null,
    val title: String = "",
    val content: String = "",
    val tagChips: List<String> = emptyList(),
    val tagInput: String = "",
    val isCreating: Boolean = false,
    val isLoading: Boolean = false,
    val error: String? = null,
)

class KnowledgeViewModel(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(KnowledgeUiState())
    val state: StateFlow<KnowledgeUiState> = _state.asStateFlow()
    private var searchJob: Job? = null

    init { load() }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            val q = _state.value.query
            if (q.isBlank()) {
                // 非搜索：用 cached flow 秒出
                try {
                    repository.cachedKnowledge().collect { items ->
                        _state.update { it.copy(items = items, isLoading = false) }
                    }
                } catch (e: Exception) {
                    if (_state.value.items.isEmpty()) {
                        _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
                    } else {
                        _state.update { it.copy(isLoading = false) }
                    }
                }
            } else {
                // 搜索：直接网络请求
                try {
                    val items = if (_state.value.semanticSearch) {
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
    }

    fun onQueryChange(query: String) {
        _state.update { it.copy(query = query) }
        searchJob?.cancel()
        searchJob = viewModelScope.launch { delay(300); load() }
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
                tagChips = item.tags ?: emptyList(),
                tagInput = "",
            )
        }
    }

    fun startCreate() {
        _state.update {
            it.copy(selected = null, isCreating = true, title = "", content = "", tagChips = emptyList(), tagInput = "")
        }
    }

    fun onTitleChange(v: String) { _state.update { it.copy(title = v) } }
    fun onContentChange(v: String) { _state.update { it.copy(content = v) } }

    fun onTagInputChange(v: String) {
        if (v.endsWith(",") || v.endsWith("\n")) {
            val tag = v.trimEnd(',', '\n').trim()
            if (tag.isNotEmpty() && tag !in _state.value.tagChips) {
                _state.update { it.copy(tagChips = it.tagChips + tag, tagInput = "") }
            } else {
                _state.update { it.copy(tagInput = "") }
            }
        } else {
            _state.update { it.copy(tagInput = v) }
        }
    }

    fun addTagFromInput() {
        val tag = _state.value.tagInput.trim()
        if (tag.isNotEmpty() && tag !in _state.value.tagChips) {
            _state.update { it.copy(tagChips = it.tagChips + tag, tagInput = "") }
        } else {
            _state.update { it.copy(tagInput = "") }
        }
    }

    fun removeTag(tag: String) {
        _state.update { it.copy(tagChips = it.tagChips - tag) }
    }

    fun save() {
        viewModelScope.launch {
            try {
                val tags = buildList {
                    addAll(_state.value.tagChips)
                    val pending = _state.value.tagInput.trim()
                    if (pending.isNotEmpty()) add(pending)
                }
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
