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

/**
 * 列表项 = Fact + 一个稳定的 key。
 *
 * **注意 `index` 不再是给后端用的标识**：它只是「原始列表里的位置」，仅用作
 * LazyColumn 的 key（同一位置换内容时能复用视图）。真正的读改写一律走
 * [Fact.id]。
 *
 * 以前这里注释写的是「Facts from API have no id; backend uses array index」——
 * 那是错的：后端一直在返回 memory id，是 Kotlin 侧没声明该字段。用位置下标去
 * PATCH 会错位（详见 `Fact.id` 的注释）。
 */
data class FactItem(
    val index: String,
    val fact: Fact,
)

/** 后端标识：优先用 memory id，老缓存里没有 id 时退回位置下标（至少不会更糟）。 */
val FactItem.recordId: String
    get() = fact.id.ifBlank { index }

fun List<Fact>.toFactItems(includeSuperseded: Boolean = false): List<FactItem> {
    return mapIndexedNotNull { index, fact ->
        if (!includeSuperseded && fact.superseded) return@mapIndexedNotNull null
        FactItem(index = index.toString(), fact = fact)
    }
}

data class RecordsFilter(
    val status: String? = null,   // null=全部 / "pending" / "confirmed" / "superseded"
    val type: String? = null,
    val domain: String? = null,   // null=general
)

enum class MemoryTab(val title: String) {
    Facts("事实"),
    Insights("永久记忆"),
    Procedures("流程"),
    Records("结构化记忆")
}

/**
 * 三张卡（事实 / 流程 / 结构化记忆）共用同一个编辑器。
 *
 * 以前每个 tab 各写一套编辑页：事实是「详情页 → 点编辑 → 才进编辑」，流程根本没
 * 有编辑，结构化记忆点卡片就进编辑（太容易误触）。现在统一成「双击卡片进编辑」，
 * 编辑页也收敛成一个 —— 顶栏结构、字段排版、底部元信息行都一致。
 */
sealed interface MemoryEditTarget {
    val title: String

    data class Fact(val id: String, val original: com.ethan.agent.core.model.Fact) : MemoryEditTarget {
        override val title = "编辑事实"
    }

    data class Procedure(val id: String, val original: com.ethan.agent.core.model.Procedure) : MemoryEditTarget {
        override val title = "编辑流程"
    }

    data class Record(val id: String, val original: StructuredRecord) : MemoryEditTarget {
        override val title = "编辑记录"
    }
}

data class MemoryUiState(
    val tab: MemoryTab = MemoryTab.Facts,
    // Facts
    val allFacts: List<Fact> = emptyList(),
    val facts: List<FactItem> = emptyList(),
    // Insights
    val insights: List<InsightItem> = emptyList(),
    val insightsDate: String = "",
    // Procedures
    val procedures: List<Procedure> = emptyList(),
    // Records
    val records: List<StructuredRecord> = emptyList(),
    val recordsFilter: RecordsFilter = RecordsFilter(),
    val recordsSearch: String = "",
    // ── 共用编辑器（事实 / 流程 / 结构化记忆）──────────────────────────────
    /** 非空时，编辑页盖在列表之上。 */
    val editing: MemoryEditTarget? = null,
    /** 编辑中的正文（三张卡共用）。 */
    val editContent: String = "",
    /** 结构化记忆专有：编辑中的置信度 / 重要度。 */
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

    // ── 共用编辑器：进入 / 改内容 / 取消 / 保存 / 删除 ────────────────────────

    fun selectFact(item: FactItem) {
        _state.update {
            it.copy(
                editing = MemoryEditTarget.Fact(item.recordId, item.fact),
                editContent = item.fact.content,
            )
        }
    }

    fun selectProcedure(procedure: Procedure) {
        _state.update {
            it.copy(
                editing = MemoryEditTarget.Procedure(procedure.id, procedure),
                editContent = procedure.rule,
            )
        }
    }

    fun selectRecord(record: StructuredRecord) {
        _state.update {
            it.copy(
                editing = MemoryEditTarget.Record(record.id, record),
                editContent = record.content,
                recordEditConfidence = record.confidence,
                recordEditImportance = record.importance,
            )
        }
    }

    /** 关闭编辑页（返回键 / 取消）。不保存。 */
    fun dismissEditor() {
        _state.update { it.copy(editing = null, editContent = "") }
    }

    fun onEditChange(text: String) {
        _state.update { it.copy(editContent = text) }
    }

    fun onRecordEditConfidence(v: Double) {
        _state.update { it.copy(recordEditConfidence = v) }
    }

    fun onRecordEditImportance(v: Double) {
        _state.update { it.copy(recordEditImportance = v) }
    }

    /** 保存当前编辑页。按 [MemoryEditTarget] 分派到对应的接口。 */
    fun saveEditing() {
        val target = _state.value.editing ?: return
        val content = _state.value.editContent
        viewModelScope.launch {
            try {
                when (target) {
                    is MemoryEditTarget.Fact -> {
                        repository.updateFact(target.id, content)
                        dismissEditor()
                        load()
                    }
                    is MemoryEditTarget.Procedure -> {
                        repository.updateProcedure(target.id, content)
                        dismissEditor()
                        load()
                    }
                    is MemoryEditTarget.Record -> {
                        repository.updateRecord(
                            target.id,
                            UpdateRecordRequest(
                                content = content,
                                confidence = _state.value.recordEditConfidence,
                                importance = _state.value.recordEditImportance,
                            ),
                        )
                        dismissEditor()
                        loadRecords()
                    }
                }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    /** 删除当前编辑页对应的记录。 */
    fun deleteEditing() {
        val target = _state.value.editing ?: return
        viewModelScope.launch {
            try {
                when (target) {
                    is MemoryEditTarget.Fact -> {
                        repository.deleteFact(target.id)
                        dismissEditor()
                        load()
                    }
                    is MemoryEditTarget.Procedure -> {
                        repository.deleteProcedure(target.id)
                        dismissEditor()
                        load()
                    }
                    is MemoryEditTarget.Record -> {
                        repository.deleteRecord(target.id)
                        dismissEditor()
                        loadRecords()
                    }
                }
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    /** 列表内联删除（流程 tab 左滑、结构化记忆卡片上的垃圾桶）。不经过编辑页。 */
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

    /** 卡片上的垃圾桶：直接删，不进编辑页。 */
    fun deleteRecord(id: String) {
        viewModelScope.launch {
            try {
                repository.deleteRecord(id)
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
