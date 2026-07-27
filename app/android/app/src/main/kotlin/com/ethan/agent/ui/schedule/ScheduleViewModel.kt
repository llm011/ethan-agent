package com.ethan.agent.ui.schedule

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.ScheduleCreateRequest
import com.ethan.agent.core.model.ScheduleJob
import com.ethan.agent.data.EthanRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import javax.inject.Inject

enum class ScheduleTab(val title: String) {
    Jobs("任务"),
    Timelines("时间线"),
}

data class TimelineItem(
    val id: String = "",
    val name: String = "",
    val scene: String = "",
    val currentPhase: String? = null,
    val nextPhase: String? = null,
    val nextAnchor: String = "",
    val status: String = "active",
)

data class CreateScheduleForm(
    val name: String = "",
    val prompt: String = "",
    val triggerType: String = "cron",
    val cron: String = "",
    val intervalMinutes: String = "",
    val sessionId: String = "",
    val endDate: String = "",
    val category: String = "",
    val scene: String = "",
)

data class TriggerSuccess(val jobId: String, val sessionId: String)

data class ScheduleUiState(
    val tab: ScheduleTab = ScheduleTab.Jobs,
    val jobs: List<ScheduleJob> = emptyList(),
    val timelines: List<TimelineItem> = emptyList(),
    val triggeringIds: Set<String> = emptySet(),
    val showCreateSheet: Boolean = false,
    val createForm: CreateScheduleForm = CreateScheduleForm(),
    val isCreating: Boolean = false,
    val isSyncingTimelines: Boolean = false,
    val isLoading: Boolean = false,
    val error: String? = null,
    val triggerSuccess: TriggerSuccess? = null,
)

@HiltViewModel
class ScheduleViewModel @Inject constructor(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(ScheduleUiState())
    val state: StateFlow<ScheduleUiState> = _state.asStateFlow()

    init { load() }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val jobs = repository.getSchedules()
                _state.update { it.copy(jobs = jobs, isLoading = false) }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun setTab(tab: ScheduleTab) {
        _state.update { it.copy(tab = tab) }
        if (tab == ScheduleTab.Timelines && _state.value.timelines.isEmpty()) {
            loadTimelines()
        }
    }

    fun loadTimelines() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val resp = repository.getTimelineStatus()
                val items = resp.timelines.mapNotNull { el ->
                    runCatching {
                        val obj = el.jsonObject
                        TimelineItem(
                            id = obj["id"]?.jsonPrimitive?.content ?: return@mapNotNull null,
                            name = obj["name"]?.jsonPrimitive?.content ?: "",
                            scene = obj["scene"]?.jsonPrimitive?.content ?: "",
                            currentPhase = obj["current_phase"]?.jsonPrimitive?.contentOrNull,
                            nextPhase = obj["next_phase"]?.jsonPrimitive?.contentOrNull,
                            nextAnchor = obj["next_anchor"]?.jsonPrimitive?.content ?: "",
                            status = obj["status"]?.jsonPrimitive?.content ?: "active",
                        )
                    }.getOrNull()
                }
                _state.update { it.copy(timelines = items, isLoading = false) }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun syncTimelines() {
        viewModelScope.launch {
            _state.update { it.copy(isSyncingTimelines = true) }
            try {
                repository.syncTimelines()
                loadTimelines()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            } finally {
                _state.update { it.copy(isSyncingTimelines = false) }
            }
        }
    }

    fun timelineAction(timelineId: String, action: String) {
        viewModelScope.launch {
            try {
                repository.timelineLifecycle(timelineId, action)
                loadTimelines()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun triggerJob(job: ScheduleJob) {
        viewModelScope.launch {
            _state.update { it.copy(triggeringIds = it.triggeringIds + job.id) }
            try {
                repository.triggerSchedule(job.id)
                _state.update {
                    it.copy(
                        triggeringIds = it.triggeringIds - job.id,
                        triggerSuccess = TriggerSuccess(job.id, job.sessionId),
                    )
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(
                        triggeringIds = it.triggeringIds - job.id,
                        error = repository.friendlyError(e),
                    )
                }
            }
        }
    }

    fun clearTriggerSuccess() { _state.update { it.copy(triggerSuccess = null) } }

    fun toggleJob(job: ScheduleJob) {
        viewModelScope.launch {
            try {
                val newState = if (job.status == "active") "paused" else "active"
                repository.patchSchedule(job.id, newState)
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun deleteJob(id: String) {
        viewModelScope.launch {
            try {
                repository.deleteSchedule(id)
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun showCreateSheet() { _state.update { it.copy(showCreateSheet = true, createForm = CreateScheduleForm()) } }
    fun dismissCreateSheet() { _state.update { it.copy(showCreateSheet = false) } }

    fun updateForm(form: CreateScheduleForm) { _state.update { it.copy(createForm = form) } }

    fun submitCreate() {
        val form = _state.value.createForm
        if (form.name.isBlank() || form.prompt.isBlank()) {
            _state.update { it.copy(error = "任务名称和提示词不能为空") }
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(isCreating = true) }
            try {
                repository.createSchedule(
                    ScheduleCreateRequest(
                        jobId = "",
                        title = form.name,
                        prompt = form.prompt,
                        cron = if (form.triggerType == "cron") form.cron else "",
                        intervalMinutes = if (form.triggerType == "interval") form.intervalMinutes.toIntOrNull() ?: 0 else 0,
                        sessionId = form.sessionId,
                        endDate = form.endDate,
                        category = form.category,
                        scene = form.scene.ifBlank { "work" },
                    )
                )
                _state.update { it.copy(showCreateSheet = false, isCreating = false) }
                load()
            } catch (e: Exception) {
                _state.update { it.copy(isCreating = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun clearError() { _state.update { it.copy(error = null) } }
}
