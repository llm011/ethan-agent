package com.ethan.agent.shared.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.Fact
import com.ethan.agent.core.model.InsightItem
import com.ethan.agent.core.model.Procedure
import com.ethan.agent.core.model.StructuredRecord
import com.ethan.agent.core.model.UpdateRecordRequest
import com.ethan.agent.shared.EthanRepository
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.datetime.*
import kotlinx.datetime.TimeZone
import kotlinx.serialization.json.JsonElement

/** Facts from API have no id; backend uses array index for PATCH/DELETE. */
data class FactItem(
    val index: String,
    val fact: Fact,
)

fun List<Fact>.toFactItems(includeSuperseded: Boolean = false): List<FactItem> {
    return mapIndexedNotNull { index, fact ->
        if (!includeSuperseded && fact.superseded) return@mapIndexedNotNull null
        FactItem(index = index.toString(), fact = fact)
    }
}

fun List<Fact>.indexOfFact(target: Fact): String {
    val idx = indexOfFirst { it.content == target.content && it.createdAt == target.createdAt }
    return if (idx >= 0) idx.toString() else "0"
}

data class RecordsFilter(
    val status: String? = null,   // null=全部 / "pending" / "confirmed" / "superseded"
    val type: String? = null,
    val domain: String? = null,   // null=general
)

enum class MemoryTab(val title: String) {
    Facts("事实"), Insights("永久记忆"), Procedures("流程"), Records("结构化记忆")
}

data class MemoryUiState(
    val tab: MemoryTab = MemoryTab.Facts,
    // Facts
    val allFacts: List<Fact> = emptyList(),
    val facts: List<FactItem> = emptyList(),
    val selectedFact: Fact? = null,
    val selectedFactIndex: String? = null,
    val editContent: String = "",
    // Insights
    val insights: List<InsightItem> = emptyList(),
    val insightsDate: String = "",
    // Procedures
    val procedures: List<Procedure> = emptyList(),
    // Records
    val records: List<StructuredRecord> = emptyList(),
    val recordsFilter: RecordsFilter = RecordsFilter(),
    val recordsSearch: String = "",
    val selectedRecord: StructuredRecord? = null,
    val recordEditContent: String = "",
    val recordEditConfidence: Double = 0.0,
    val recordEditImportance: Double = 0.0,
    // Daily summaries
    val summaries: List<JsonElement> = emptyList(),
    val showSummaries: Boolean = false,
    // Loading
    val isLoading: Boolean = false,
    val isConsolidating: Boolean = false,
    val error: String? = null,
)

class MemoryViewModel(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(MemoryUiState())
    val state: StateFlow<MemoryUiState> = _state.asStateFlow()

    private var searchJob: Job? = null

    init { load() }

    fun setTab(tab: MemoryTab) {
        _state.update { it.copy(tab = tab) }
        when (tab) {
            MemoryTab.Insights -> loadInsights()
            MemoryTab.Records -> loadRecords()
            else -> Unit
        }
    }

    // ── Facts ──────────────────────────────────────────────────────────────────

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            launch {
                try {
                    repository.cachedFacts().collect { allFacts ->
                        _state.update {
                            it.copy(allFacts = allFacts, facts = allFacts.toFactItems(), isLoading = false)
                        }
                    }
                } catch (e: Exception) {
                    if (_state.value.allFacts.isEmpty()) {
                        _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
                    }
                }
            }
            launch {
                try {
                    repository.cachedProcedures().collect { procedures ->
                        _state.update { it.copy(procedures = procedures) }
                    }
                } catch (e: Exception) {
                    if (_state.value.procedures.isEmpty()) {
                        _state.update { it.copy(error = repository.friendlyError(e)) }
                    }
                }
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
        _state.update { it.copy(selectedFact = null, selectedFactIndex = null, editContent = "") }
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

    // ── Insights ───────────────────────────────────────────────────────────────

    fun loadInsights() {
        val date = _state.value.insightsDate
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val items = if (date.isBlank()) {
                    repository.getInsights(limit = 50).items
                } else {
                    repository.getInsightsByDate(date).items.mapNotNull { el ->
                        try {
                            kotlinx.serialization.json.Json.decodeFromJsonElement(InsightItem.serializer(), el)
                        } catch (_: Exception) { null }
                    }
                }
                _state.update { it.copy(insights = items, isLoading = false) }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun setInsightsDate(date: String) {
        _state.update { it.copy(insightsDate = date) }
        loadInsights()
    }

    // ── Records ────────────────────────────────────────────────────────────────

    fun loadRecords() {
        val filter = _state.value.recordsFilter
        val q = _state.value.recordsSearch.trim()
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val items = if (q.isNotBlank()) {
                    repository.searchRecords(query = q, domain = filter.domain, status = filter.status).items
                } else {
                    repository.getRecords(
                        type = filter.type,
                        status = filter.status,
                        domain = filter.domain,
                        limit = 50,
                    ).items
                }
                _state.update { it.copy(records = items, isLoading = false) }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun setRecordsFilter(filter: RecordsFilter) {
        _state.update { it.copy(recordsFilter = filter) }
        loadRecords()
    }

    fun setRecordsSearch(query: String) {
        _state.update { it.copy(recordsSearch = query) }
        searchJob?.cancel()
        searchJob = viewModelScope.launch {
            delay(300)
            loadRecords()
        }
    }

    fun selectRecord(record: StructuredRecord) {
        _state.update {
            it.copy(
                selectedRecord = record,
                recordEditContent = record.content,
                recordEditConfidence = record.confidence,
                recordEditImportance = record.importance,
            )
        }
    }

    fun dismissRecord() {
        _state.update { it.copy(selectedRecord = null) }
    }

    fun onRecordEditContent(text: String) {
        _state.update { it.copy(recordEditContent = text) }
    }

    fun onRecordEditConfidence(v: Double) {
        _state.update { it.copy(recordEditConfidence = v) }
    }

    fun onRecordEditImportance(v: Double) {
        _state.update { it.copy(recordEditImportance = v) }
    }

    fun saveRecord() {
        val id = _state.value.selectedRecord?.id ?: return
        viewModelScope.launch {
            try {
                repository.updateRecord(
                    id,
                    UpdateRecordRequest(
                        content = _state.value.recordEditContent,
                        confidence = _state.value.recordEditConfidence,
                        importance = _state.value.recordEditImportance,
                    ),
                )
                dismissRecord()
                loadRecords()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun deleteRecord(id: String) {
        viewModelScope.launch {
            try {
                repository.deleteRecord(id)
                dismissRecord()
                loadRecords()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun confirmRecord(id: String) {
        viewModelScope.launch {
            try {
                repository.confirmRecord(id)
                loadRecords()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    // ── Consolidate ────────────────────────────────────────────────────────────

    fun triggerConsolidate() {
        viewModelScope.launch {
            _state.update { it.copy(isConsolidating = true) }
            try {
                repository.consolidateMemory()
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            } finally {
                _state.update { it.copy(isConsolidating = false) }
            }
        }
    }

    fun triggerRecordsConsolidate(targetDate: String? = null) {
        viewModelScope.launch {
            _state.update { it.copy(isConsolidating = true) }
            try {
                val date = targetDate ?: Clock.System.todayIn(TimeZone.currentSystemDefault()).toString()
                repository.consolidateRecords(date)
                loadRecords()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            } finally {
                _state.update { it.copy(isConsolidating = false) }
            }
        }
    }

    // ── Daily summaries ────────────────────────────────────────────────────────

    fun loadSummaries() {
        viewModelScope.launch {
            try {
                val items = repository.getDailySummaries(limit = 30).items
                _state.update { it.copy(summaries = items, showSummaries = true) }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun hideSummaries() {
        _state.update { it.copy(showSummaries = false) }
    }

    fun clearError() {
        _state.update { it.copy(error = null) }
    }
}
