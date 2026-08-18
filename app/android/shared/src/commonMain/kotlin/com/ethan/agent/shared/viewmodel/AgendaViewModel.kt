package com.ethan.agent.shared.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.AgendaCreateRequest
import com.ethan.agent.core.model.AgendaEvent
import com.ethan.agent.core.model.AgendaPatchRequest
import com.ethan.agent.shared.EthanRepository
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.datetime.Clock
import kotlinx.datetime.Instant
import kotlinx.datetime.LocalDate
import kotlinx.datetime.LocalDateTime
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime

data class AgendaEventForm(
    val title: String = "",
    val dateKey: String = "",   // YYYY-MM-DD
    val timeText: String = "09:00", // HH:MM
    val repeat: String = "none",    // none / daily / weekly
    val weekdays: Set<Int> = emptySet(), // ISO 1..7
    val note: String = "",
)

data class AgendaUiState(
    val events: List<AgendaEvent> = emptyList(),
    val enabled: Boolean = false,
    val isLoading: Boolean = false,
    val error: String? = null,
    // 日历
    val selectedDateKey: String = "",
    val displayYear: Int = 0,
    val displayMonth: Int = 0,
    val calendarExpanded: Boolean = true,
    // 编辑
    val showEditSheet: Boolean = false,
    val editingId: String? = null,
    val form: AgendaEventForm = AgendaEventForm(),
    val isSaving: Boolean = false,
    // 删除确认
    val pendingDeleteId: String? = null,
    // per-item 操作中
    val completingIds: Set<String> = emptySet(),
    val togglingEnabled: Boolean = false,
)

// ── 日期工具（commonMain，kotlinx-datetime；供 ViewModel 与 app UI 共用） ──

fun localNow(): LocalDateTime =
    Clock.System.now().toLocalDateTime(TimeZone.currentSystemDefault())

fun todayKey(): String = localNow().date.toString() // LocalDate.toString() = YYYY-MM-DD

/** 'YYYY-MM-DD HH:MM' → 'YYYY-MM-DD'；失败返回 null */
fun whenDateKey(whenText: String): String? =
    if (whenText.length >= 10 && whenText.getOrNull(4) == '-' && whenText.getOrNull(7) == '-')
        whenText.substring(0, 10) else null

/** 'YYYY-MM-DD HH:MM' → 'HH:MM'；失败返回 null */
fun whenTimeText(whenText: String): String? =
    if (whenText.length >= 16 && (whenText.getOrNull(10) == ' ' || whenText.getOrNull(10) == 'T'))
        whenText.substring(11, 16) else null

/** ISO 8601（含时区）→ 本地时区 dateKey；解析失败 fallback 前 10 位 */
fun isoToDateKey(iso: String): String? = runCatching {
    Instant.parse(iso).toLocalDateTime(TimeZone.currentSystemDefault()).date.toString()
}.getOrElse { if (iso.length >= 10) iso.substring(0, 10) else null }

/** ISO 8601（含时区）→ 本地时区 'HH:MM'；失败返回 null */
fun isoToTimeText(iso: String): String? = runCatching {
    val t = Instant.parse(iso).toLocalDateTime(TimeZone.currentSystemDefault()).time
    "%02d:%02d".format(t.hour, t.minute)
}.getOrNull()

/** 事件归属日期：pending 且有 next_run_time → 用它；否则用 when。 */
fun eventDateKey(ev: AgendaEvent): String? =
    if (ev.status == "pending" && !ev.nextRunTime.isNullOrBlank()) isoToDateKey(ev.nextRunTime!!)
    else whenDateKey(ev.whenText)

/** 事件展示时间：pending 时优先 next_run_time 的本地时间；否则 when 的时分。 */
fun eventTimeText(ev: AgendaEvent): String {
    if (ev.status == "pending" && !ev.nextRunTime.isNullOrBlank()) {
        isoToTimeText(ev.nextRunTime!!)?.let { return it }
    }
    return whenTimeText(ev.whenText) ?: "--:--"
}

fun daysInMonth(year: Int, month: Int): Int {
    val first = LocalDate(year, month, 1).toEpochDays()
    val next = if (month == 12) LocalDate(year + 1, 1, 1).toEpochDays() else LocalDate(year, month + 1, 1).toEpochDays()
    return (next - first).toInt()
}

/** 某月 1 号是周几（ISO：1=周一 … 7=周日）。1970-01-01 是周四（ISO 4）。 */
fun firstDayOfMonthIso(year: Int, month: Int): Int {
    val epochDays = LocalDate(year, month, 1).toEpochDays()
    return (((epochDays + 3) % 7) + 7) % 7 + 1
}

fun dateKeyOf(year: Int, month: Int, day: Int): String = "%04d-%02d-%02d".format(year, month, day)

class AgendaViewModel(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(AgendaUiState())
    val state: StateFlow<AgendaUiState> = _state.asStateFlow()

    init {
        val now = localNow()
        _state.update {
            it.copy(selectedDateKey = todayKey(), displayYear = now.year, displayMonth = now.monthNumber)
        }
        load()
        // 30s 静默轮询，与 Web 端一致
        viewModelScope.launch {
            while (isActive) {
                delay(30_000)
                load(silent = true)
            }
        }
    }

    fun load(silent: Boolean = false) {
        viewModelScope.launch {
            if (!silent) _state.update { it.copy(isLoading = true) }
            try {
                val resp = repository.getAgenda()
                _state.update { it.copy(events = resp.events, enabled = resp.enabled, isLoading = false) }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    // ── 日历交互：点某天 → 切换到该天并自动收起日历 ──

    fun selectDate(dateKey: String) {
        _state.update { it.copy(selectedDateKey = dateKey, calendarExpanded = false) }
    }

    fun toggleCalendar() { _state.update { it.copy(calendarExpanded = !it.calendarExpanded) } }

    fun prevMonth() = shiftMonth(-1)
    fun nextMonth() = shiftMonth(1)

    private fun shiftMonth(delta: Int) {
        _state.update {
            var m = it.displayMonth + delta
            var y = it.displayYear
            if (m < 1) { m = 12; y -= 1 }
            if (m > 12) { m = 1; y += 1 }
            it.copy(displayYear = y, displayMonth = m)
        }
    }

    fun goToday() {
        val now = localNow()
        _state.update {
            it.copy(selectedDateKey = todayKey(), displayYear = now.year, displayMonth = now.monthNumber)
        }
    }

    // ── Agent 日程工具开关（乐观更新，失败回滚） ──

    fun toggleEnabled() {
        val next = !_state.value.enabled
        _state.update { it.copy(enabled = next, togglingEnabled = true) }
        viewModelScope.launch {
            try {
                repository.setAgendaEnabled(next)
            } catch (e: Exception) {
                _state.update { it.copy(enabled = !next, error = repository.friendlyError(e)) }
            } finally {
                _state.update { it.copy(togglingEnabled = false) }
            }
        }
    }

    // ── 事件编辑 ──

    fun showCreateSheet() {
        val s = _state.value
        _state.update {
            it.copy(showEditSheet = true, editingId = null, form = AgendaEventForm(dateKey = s.selectedDateKey.ifBlank { todayKey() }))
        }
    }

    fun editEvent(ev: AgendaEvent) {
        val form = AgendaEventForm(
            title = ev.title,
            dateKey = eventDateKey(ev) ?: todayKey(),
            timeText = whenTimeText(ev.whenText) ?: "09:00",
            repeat = ev.repeat,
            weekdays = ev.weekdays.toSet(),
            note = ev.note,
        )
        _state.update { it.copy(showEditSheet = true, editingId = ev.id, form = form) }
    }

    fun dismissSheet() { _state.update { it.copy(showEditSheet = false, editingId = null) } }

    fun updateForm(form: AgendaEventForm) { _state.update { it.copy(form = form) } }

    fun submitEvent() {
        val s = _state.value
        val form = s.form
        if (form.title.isBlank()) { _state.update { it.copy(error = "请填写要做什么") }; return }
        if (form.repeat == "weekly" && form.weekdays.isEmpty()) {
            _state.update { it.copy(error = "每周重复需至少选择一天") }; return
        }
        val whenText = "${form.dateKey} ${form.timeText}"
        viewModelScope.launch {
            _state.update { it.copy(isSaving = true) }
            try {
                val editingId = s.editingId
                if (editingId != null) {
                    repository.patchAgenda(
                        editingId,
                        AgendaPatchRequest(
                            title = form.title.trim(), whenText = whenText,
                            repeat = form.repeat, weekdays = form.weekdays.sorted(), note = form.note,
                        ),
                    )
                } else {
                    repository.createAgenda(
                        AgendaCreateRequest(
                            title = form.title.trim(), whenText = whenText,
                            repeat = form.repeat, weekdays = form.weekdays.sorted(), note = form.note,
                        ),
                    )
                }
                _state.update { it.copy(isSaving = false, showEditSheet = false, editingId = null) }
                load(silent = true)
            } catch (e: Exception) {
                _state.update { it.copy(isSaving = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun completeEvent(ev: AgendaEvent) {
        viewModelScope.launch {
            _state.update { it.copy(completingIds = it.completingIds + ev.id) }
            try {
                repository.completeAgenda(ev.id)
                load(silent = true)
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            } finally {
                _state.update { it.copy(completingIds = it.completingIds - ev.id) }
            }
        }
    }

    fun requestDelete(id: String) { _state.update { it.copy(pendingDeleteId = id) } }
    fun cancelDelete() { _state.update { it.copy(pendingDeleteId = null) } }

    fun confirmDelete() {
        val id = _state.value.pendingDeleteId ?: return
        _state.update { it.copy(pendingDeleteId = null) }
        viewModelScope.launch {
            try {
                repository.deleteAgenda(id)
                load(silent = true)
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun clearError() { _state.update { it.copy(error = null) } }
}
