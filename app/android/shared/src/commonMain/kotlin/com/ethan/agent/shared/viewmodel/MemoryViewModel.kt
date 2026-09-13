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

/**
 * 日摘要弹窗每页条数。
 *
 * 摘要正文是多段 Markdown，一条动辄几 KB —— 以前一次拉 30 条再一次性渲染，
 * 打开弹窗要卡一下。取 20 是为了「滚一屏还有内容」和「首屏够快」的折中。
 */
private const val DAILY_SUMMARIES_PAGE = 20

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
    /** 事实列表还有没有下一页（下滑加载更多用）。 */
    val factsHasMore: Boolean = false,
    val factsLoading: Boolean = false,
    /**
     * 下一页要从服务端的第几条开始拉。
     *
     * **不能**用 `facts.size` 当 offset —— [toFactItems] 会把 superseded 的事实
     * 滤掉（后端 `/facts` 的 status 过滤同时包含 active 和 superseded），本地条数
     * 因此可能小于服务端已经翻过的条数。拿本地条数当 offset，只要第一页里有一条
     * superseded，第二页就会把同样的记录再拉一遍，然后一直原地打转。
     *
     * 这里记的是「服务端已消费的条数」，与 UI 上显示多少条无关。
     */
    val factsOffset: Int = 0,
    // Insights
    val insights: List<InsightItem> = emptyList(),
    val insightsDate: String = "",
    val insightsHasMore: Boolean = false,
    val insightsLoading: Boolean = false,
    /** 同 [factsOffset]：服务端已消费的条数（by-date 分支会丢解码失败的项）。 */
    val insightsOffset: Int = 0,
    // Procedures
    val procedures: List<Procedure> = emptyList(),
    // Records
    val records: List<StructuredRecord> = emptyList(),
    val recordsFilter: RecordsFilter = RecordsFilter(),
    val recordsSearch: String = "",
    val recordsHasMore: Boolean = false,
    val recordsLoading: Boolean = false,
    /** 同 [factsOffset]：服务端已消费的条数（追加时会按 id 去重，本地条数会偏小）。 */
    val recordsOffset: Int = 0,
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
    /**
     * 日摘要弹窗里选中的日期（`YYYY-MM-DD`，空 = 全部日期）。
     *
     * 与 [insightsDate] 分开维护：两个弹窗/页签各自筛选，互不干扰。
     */
    val summariesDate: String = "",
    /** 日摘要是否正在加载（切日期时给弹窗转圈，而不是先闪「暂无日摘要」）。 */
    val summariesLoading: Boolean = false,
    /** 弹窗列表是否还有更早的摘要可以加载（按 [DAILY_SUMMARIES_PAGE] 分页）。 */
    val summariesHasMore: Boolean = false,
    /**
     * 所有有日摘要的日期（`YYYY-MM-DD`）。空集合 = 还没拉到，或确实一条都没有。
     *
     * 用途：让日期选择器把「没摘要的日子」置灰，用户一眼看出哪些天有内容。
     * 这是**全量索引**，不随 [summariesDate] 变，也不进分页。
     */
    val summaryDates: Set<String> = emptySet(),
    /**
     * [summaryDates] 是否被后端上限截断（还有更早的日期没返回）。
     *
     * 为 true 时，比 [summaryDates] 里最早一天更早的日子**不代表没内容**，
     * 只是没拉回来 —— 日历要提示「还有更早的」，不能把它们当成空日子置灰。
     */
    val summaryDatesTruncated: Boolean = false,
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
                    // 缓存先渲染（离线也有内容），再拉第一页替换。
                    // 注意：缓存 write 仍在 cachedFacts() 里、写的是全量 list，
                    // 分页结果绝不能写回缓存 —— 一页覆盖全量会让离线只剩当前页。
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
            launch { loadFactsFirstPage() }
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

    // ── Facts 分页 ─────────────────────────────────────────────────────────────

    /**
     * 拉事实第一页。
     *
     * 事实是四个 tab 里最可能真正变长的（上限 1000），所以走分页接口而不是
     * 一次性全量。第一页成功后用 [replaceHeadKeepLater] 覆盖：**保留**用户已经
     * 翻出来的后续页 —— 编辑/删除后重新拉第一页时，直接整表替换会让那些页凭空消失。
     */
    private suspend fun loadFactsFirstPage() {
        _state.update { it.copy(factsLoading = true) }
        try {
            val page = repository.getFactsPage(limit = MEMORY_PAGE, offset = 0)
            val fresh = page.facts.toFactItems()
            _state.update {
                val merged = if (it.facts.size > fresh.size) {
                    replaceHeadKeepLater(it.facts, fresh, { f -> f.recordId })
                } else {
                    fresh
                }
                it.copy(
                    allFacts = page.facts,
                    facts = merged,
                    factsOffset = page.facts.size,
                    factsHasMore = hasMoreAfter(page.facts, page.total, offset = 0),
                    factsLoading = false,
                )
            }
        } catch (e: Exception) {
            _state.update { it.copy(factsLoading = false, error = repository.friendlyError(e)) }
        }
    }

    /** 事实列表滚到底：拉下一页追加。 */
    fun loadMoreFacts() {
        val s = _state.value
        if (s.factsLoading || !s.factsHasMore) return
        _state.update { it.copy(factsLoading = true) }
        viewModelScope.launch {
            try {
                // 用服务端口径的 offset，不是 facts.size —— 后者被 superseded
                // 过滤影响，会偏小（见 MemoryUiState.factsOffset 的注释）。
                val offset = s.factsOffset
                val page = repository.getFactsPage(limit = MEMORY_PAGE, offset = offset)
                val appended = page.facts.toFactItems()
                _state.update { st ->
                    st.copy(
                        facts = appendPage(st.facts, appended, { f -> f.recordId }),
                        factsOffset = offset + page.facts.size,
                        factsHasMore = hasMoreAfter(page.facts, page.total, offset = offset),
                        factsLoading = false,
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(factsLoading = false, error = repository.friendlyError(e)) }
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
                val page = fetchInsightsPage(offset = 0)
                _state.update {
                    it.copy(
                        insights = page.items,
                        insightsOffset = page.rawCount,
                        insightsHasMore = hasMoreAfter(page.items, page.total, offset = 0),
                        isLoading = false,
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    /**
     * 拉一页永久记忆。两条分支（全部 / 指定日期）形状对齐，调用方不用分别处理。
     *
     * [rawCount] 是**服务端这一页返回了几条**（解码前），不是 [items] 的长度：
     * by-date 分支要逐条解码 JsonElement，解码失败的会被 `mapNotNull` 丢掉，
     * 拿 [items] 的长度当 offset 会越翻越偏、把后面的条目整段跳过。
     */
    private class InsightsPage(
        val items: List<InsightItem>,
        val total: Int?,
        val rawCount: Int,
    )

    private suspend fun fetchInsightsPage(offset: Int): InsightsPage {
        val date = _state.value.insightsDate
        // 有日期 → 走 by-date（一天通常 1-2 条，但接口已支持分页，两条分支
        // 形状对齐后这里能共用同一套「还有没有下一页」判断）
        return if (date.isBlank()) {
            val r = repository.getInsights(limit = MEMORY_PAGE, offset = offset)
            InsightsPage(r.items, r.total, r.items.size)
        } else {
            val r = repository.getInsightsByDate(date, limit = MEMORY_PAGE, offset = offset)
            val decoded = r.items.mapNotNull { el ->
                try {
                    kotlinx.serialization.json.Json.decodeFromJsonElement(InsightItem.serializer(), el)
                } catch (_: Exception) { null }
            }
            InsightsPage(decoded, r.total, r.items.size)
        }
    }

    /** 永久记忆滚到底：拉下一页追加。 */
    fun loadMoreInsights() {
        val s = _state.value
        if (s.insightsLoading || !s.insightsHasMore) return
        _state.update { it.copy(insightsLoading = true) }
        viewModelScope.launch {
            try {
                // 服务端口径的 offset，不是 insights.size（见 InsightsPage.rawCount）
                val offset = s.insightsOffset
                val page = fetchInsightsPage(offset = offset)
                _state.update {
                    it.copy(
                        insights = appendPage(it.insights, page.items, { i -> i.id }),
                        insightsOffset = offset + page.rawCount,
                        insightsHasMore = hasMoreAfter(page.items, page.total, offset = offset),
                        insightsLoading = false,
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(insightsLoading = false, error = repository.friendlyError(e)) }
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
                if (q.isNotBlank()) {
                    // 搜索走 /records/search，该接口**没有 offset**（FTS 排序 + 无游标，
                    // 分页要让 FTS 稳定排序，是独立的一件事），所以搜索结果不分页。
                    val items = repository.searchRecords(
                        query = q, domain = filter.domain, status = filter.status,
                    ).items
                    _state.update { it.copy(records = items, recordsHasMore = false, isLoading = false) }
                    return@launch
                }
                val page = repository.getRecords(
                    type = filter.type,
                    status = filter.status,
                    domain = filter.domain,
                    limit = MEMORY_PAGE,
                    offset = 0,
                )
                _state.update {
                    it.copy(
                        records = page.items,
                        recordsOffset = page.items.size,
                        recordsHasMore = hasMoreAfter(page.items, page.total, offset = 0),
                        isLoading = false,
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    /** 结构化记忆滚到底：拉下一页追加。搜索中不分页（接口没有 offset）。 */
    fun loadMoreRecords() {
        val s = _state.value
        if (s.recordsLoading || !s.recordsHasMore || s.recordsSearch.isNotBlank()) return
        _state.update { it.copy(recordsLoading = true) }
        viewModelScope.launch {
            try {
                val filter = s.recordsFilter
                // 服务端口径的 offset，不是 records.size —— 追加时按 id 去重，
                // 后端重排时下一遍可能又发来已加载的行，本地条数会落后于 offset，
                // 用本地条数会原地打转。
                val offset = s.recordsOffset
                val page = repository.getRecords(
                    type = filter.type,
                    status = filter.status,
                    domain = filter.domain,
                    limit = MEMORY_PAGE,
                    offset = offset,
                )
                _state.update {
                    it.copy(
                        records = appendPage(it.records, page.items, { r -> r.id }),
                        recordsOffset = offset + page.items.size,
                        recordsHasMore = hasMoreAfter(page.items, page.total, offset = offset),
                        recordsLoading = false,
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(recordsLoading = false, error = repository.friendlyError(e)) }
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
                // 沉淀可能刚生成今天的摘要，日期全集要跟着更新，
                // 否则日历上「今天」还是灰的、点不了。
                loadSummaryDates()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            } finally {
                _state.update { it.copy(isConsolidating = false) }
            }
        }
    }

    // ── Daily summaries ────────────────────────────────────────────────────────

    /**
     * 拉「有摘要的日期」全集，供日期选择器置灰没有内容的日子。
     *
     * 与 [loadSummaries] 分开：这是一次性的全量索引（几百个日期串），
     * 不进分页、不随 [MemoryUiState.summariesDate] 变，弹窗打开时拉一次即可。
     *
     * 失败**静默忽略**：这只是辅助信息，接口挂了就退化成「全部日期可选」，
     * 不能让一个附属请求把弹窗卡住。
     */
    fun loadSummaryDates() {
        viewModelScope.launch {
            try {
                val resp = repository.getDailySummaryDates()
                _state.update {
                    it.copy(summaryDates = resp.dates.toSet(), summaryDatesTruncated = resp.truncated)
                }
            } catch (_: Exception) {
                // 保持原样（空集合 → 日历全可选）
            }
        }
    }

    /**
     * 打开日摘要弹窗：按当前 [MemoryUiState.summariesDate] 重新拉第一页。
     *
     * 以前是「一次拉 30 条全塞列表」，而且只有全部日期、没法按天看。现在：
     * - 有日期 → 走 `summaries/{date}`（一天通常 1-2 条，一次到位）；
     * - 无日期 → 走列表接口，首页取 [DAILY_SUMMARIES_PAGE] 条，滚到底再拉下一页。
     *
     * 分页用 `offset`：日摘要是**按 local_date DESC 排序的只读归档**，
     * 不像消息那样会增量追加，offset 不会错位。
     */
    fun loadSummaries() {
        val date = _state.value.summariesDate
        // 日期全集只在第一次打开时拉。带上幂等守卫，否则每次切日期
        // （setSummariesDate → loadSummaries）都会重拉一遍同一个全集。
        if (_state.value.summaryDates.isEmpty()) loadSummaryDates()
        _state.update { it.copy(showSummaries = true, summariesLoading = true) }
        viewModelScope.launch {
            try {
                val items = if (date.isNotBlank()) {
                    repository.getDailySummaryByDate(date).items
                } else {
                    repository.getDailySummaries(limit = DAILY_SUMMARIES_PAGE).items
                }
                _state.update {
                    it.copy(
                        summaries = items,
                        summariesLoading = false,
                        // 按日期查一定是一次性全量；无日期时按返回条数判断是否还有更早的
                        summariesHasMore = date.isBlank() && items.size >= DAILY_SUMMARIES_PAGE,
                    )
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(summariesLoading = false, error = repository.friendlyError(e))
                }
            }
        }
    }

    /** 弹窗里的「加载更早」：按 offset 续拉下一页，追加到列表尾部（列表是日期降序）。 */
    fun loadMoreSummaries() {
        val s = _state.value
        if (s.summariesLoading || !s.summariesHasMore || s.summariesDate.isNotBlank()) return
        _state.update { it.copy(summariesLoading = true) }
        viewModelScope.launch {
            try {
                val items = repository.getDailySummaries(limit = DAILY_SUMMARIES_PAGE, offset = s.summaries.size).items
                _state.update {
                    it.copy(
                        summaries = it.summaries + items,
                        summariesLoading = false,
                        summariesHasMore = items.size >= DAILY_SUMMARIES_PAGE,
                    )
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(summariesLoading = false, error = repository.friendlyError(e))
                }
            }
        }
    }

    /** 弹窗里换日期（空串 = 全部日期），立刻重新加载。 */
    fun setSummariesDate(date: String) {
        if (_state.value.summariesDate == date) return
        _state.update { it.copy(summariesDate = date) }
        loadSummaries()
    }

    fun hideSummaries() {
        _state.update { it.copy(showSummaries = false) }
    }

    fun clearError() {
        _state.update { it.copy(error = null) }
    }
}
