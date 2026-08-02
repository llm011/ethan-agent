package com.ethan.agent.shared.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.SkillInfo
import com.ethan.agent.shared.EthanRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SkillsUiState(
    val skills: List<SkillInfo> = emptyList(),
    val query: String = "",
    val selected: SkillInfo? = null,
    val isCreating: Boolean = false,
    val name: String = "",
    val description: String = "",
    val triggers: String = "",
    val content: String = "",
    val isLoading: Boolean = false,
    val error: String? = null,
) {
    val filteredSkills: List<SkillInfo> get() = if (query.isBlank()) {
        skills
    } else {
        val q = query.lowercase()
        skills.filter {
            it.name.lowercase().contains(q) ||
                it.description.lowercase().contains(q) ||
                it.trigger.any { t -> t.lowercase().contains(q) }
        }
    }

    // Skills have no category field yet — group by first trigger keyword if available, else "未分类"
    // toSortedMap 是 JVM-only（依赖 TreeMap），KMP 下用 sortedBy + associate 保序输出。
    val groupedSkills: Map<String, List<SkillInfo>> get() = filteredSkills
        .groupBy { it.trigger.firstOrNull()?.take(8) ?: "未分类" }
        .entries
        .sortedBy { if (it.key == "未分类") "\uFFFF" else it.key }
        .associate { it.key to it.value }
}

class SkillsViewModel(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(SkillsUiState())
    val state: StateFlow<SkillsUiState> = _state.asStateFlow()

    init { load() }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                repository.cachedSkills().collect { skills ->
                    _state.update { it.copy(skills = skills, isLoading = false) }
                }
            } catch (e: Exception) {
                if (_state.value.skills.isEmpty()) {
                    _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
                } else {
                    _state.update { it.copy(isLoading = false) }
                }
            }
        }
    }

    fun onQueryChange(q: String) { _state.update { it.copy(query = q) } }

    fun selectSkill(skill: SkillInfo) {
        _state.update {
            it.copy(
                selected = skill,
                isCreating = false,
                name = skill.name,
                description = skill.description,
                triggers = skill.trigger.joinToString(", "),
                content = skill.content,
            )
        }
    }

    fun deselectSkill() {
        _state.update { it.copy(selected = null, isCreating = false) }
    }

    fun startCreate() {
        _state.update {
            it.copy(isCreating = true, selected = null, name = "", description = "", triggers = "", content = "")
        }
    }

    fun onNameChange(v: String) { _state.update { it.copy(name = v) } }
    fun onDescriptionChange(v: String) { _state.update { it.copy(description = v) } }
    fun onTriggersChange(v: String) { _state.update { it.copy(triggers = v) } }
    fun onContentChange(v: String) { _state.update { it.copy(content = v) } }

    fun save() {
        viewModelScope.launch {
            try {
                val triggers = _state.value.triggers.split(",").map { it.trim() }.filter { it.isNotEmpty() }
                repository.saveSkill(
                    SkillInfo(
                        name = _state.value.name,
                        description = _state.value.description,
                        trigger = triggers,
                        content = _state.value.content,
                    ),
                )
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun delete(name: String) {
        viewModelScope.launch {
            try {
                repository.deleteSkill(name)
                _state.update { it.copy(selected = null) }
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun clearError() { _state.update { it.copy(error = null) } }
}
