package com.ethan.agent.ui.skills

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.SkillInfo
import com.ethan.agent.data.EthanRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SkillsUiState(
    val skills: List<SkillInfo> = emptyList(),
    val selected: SkillInfo? = null,
    val isCreating: Boolean = false,
    val name: String = "",
    val description: String = "",
    val triggers: String = "",
    val content: String = "",
    val isLoading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class SkillsViewModel @Inject constructor(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(SkillsUiState())
    val state: StateFlow<SkillsUiState> = _state.asStateFlow()

    init { load() }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val skills = repository.getSkills()
                _state.update { it.copy(skills = skills, isLoading = false) }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

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
