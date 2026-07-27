package com.ethan.agent.ui.ppt

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.DeckResponse
import com.ethan.agent.data.EthanRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import javax.inject.Inject

data class PptSlide(
    val index: Int,
    val title: String,
    val content: String,
)

data class PptPreviewUiState(
    val deckName: String = "",
    val slides: List<PptSlide> = emptyList(),
    val pageCount: Int = 0,
    val isLoading: Boolean = false,
    val error: String? = null,
)

private fun parseSlides(deck: DeckResponse): List<PptSlide> {
    return deck.pages.mapIndexedNotNull { idx, el ->
        runCatching {
            val obj = el as? JsonObject ?: return@mapIndexedNotNull null
            val title = obj["title"]?.jsonPrimitive?.content ?: "Slide ${idx + 1}"
            val content = obj["content"]?.jsonPrimitive?.content ?: ""
            PptSlide(idx, title, content)
        }.getOrNull()
    }
}

@HiltViewModel
class PptPreviewViewModel @Inject constructor(
    private val repository: EthanRepository,
    savedStateHandle: SavedStateHandle,
) : ViewModel() {
    private val _state = MutableStateFlow(PptPreviewUiState())
    val state: StateFlow<PptPreviewUiState> = _state.asStateFlow()

    init {
        val sessionId = savedStateHandle.get<String>("sessionId") ?: ""
        load(sessionId)
    }

    fun load(sessionId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            try {
                val deck = repository.getDeck("", sessionId)
                _state.update {
                    it.copy(
                        deckName = deck.name,
                        pageCount = deck.pageCount,
                        slides = parseSlides(deck),
                        isLoading = false,
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun clearError() { _state.update { it.copy(error = null) } }
}
