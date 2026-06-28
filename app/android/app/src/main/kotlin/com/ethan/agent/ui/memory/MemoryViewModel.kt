package com.ethan.agent.ui.memory

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.Episode
import com.ethan.agent.core.model.Fact
import com.ethan.agent.core.model.Procedure
import com.ethan.agent.data.EthanRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

enum class MemoryTab { Facts, Episodes, Procedures }

data class MemoryUiState(
    val tab: MemoryTab = MemoryTab.Facts,
    val allFacts: List<Fact> = emptyList(),
    val facts: List<FactItem> = emptyList(),
    val episodes: List<Episode> = emptyList(),
    val procedures: List<Procedure> = emptyList(),
    val selectedFact: Fact? = null,
    val selectedFactIndex: String? = null,
    val editContent: String = "",
    val isLoading: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class MemoryViewModel @Inject constructor(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(MemoryUiState())
    val state: StateFlow<MemoryUiState> = _state.asStateFlow()

    init { load() }

    fun setTab(tab: MemoryTab) {
        _state.update { it.copy(tab = tab) }
    }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val allFacts = repository.getFacts()
                val episodes = repository.getEpisodes()
                val procedures = repository.getProcedures()
                _state.update {
                    it.copy(
                        allFacts = allFacts,
                        facts = allFacts.toFactItems(),
                        episodes = episodes,
                        procedures = procedures,
                        isLoading = false,
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun selectFact(item: FactItem) {
        _state.update {
            it.copy(
                selectedFact = item.fact,
                selectedFactIndex = item.index,
                editContent = item.fact.content,
            )
        }
    }

    fun onEditChange(text: String) {
        _state.update { it.copy(editContent = text) }
    }

    fun dismissFactEditor() {
        _state.update {
            it.copy(selectedFact = null, selectedFactIndex = null, editContent = "")
        }
    }

    fun saveFact() {
        val index = _state.value.selectedFactIndex ?: return
        viewModelScope.launch {
            try {
                repository.updateFact(index, _state.value.editContent)
                dismissFactEditor()
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun deleteFact(index: String) {
        viewModelScope.launch {
            try {
                repository.deleteFact(index)
                dismissFactEditor()
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun deleteEpisode(sessionId: String) {
        viewModelScope.launch {
            try {
                repository.deleteEpisode(sessionId)
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun deleteProcedure(id: String) {
        viewModelScope.launch {
            try {
                repository.deleteProcedure(id)
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun clearError() {
        _state.update { it.copy(error = null) }
    }
}
