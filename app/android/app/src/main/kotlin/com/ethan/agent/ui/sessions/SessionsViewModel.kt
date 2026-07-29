package com.ethan.agent.ui.sessions

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.SessionInfo
import com.ethan.agent.core.model.SummaryResponse
import com.ethan.agent.data.EthanRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SessionsUiState(
    val sessions: List<SessionInfo> = emptyList(),
    val query: String = "",
    val isLoading: Boolean = false,
    val error: String? = null,
    val renameTarget: SessionInfo? = null,
    val renameText: String = "",
    val regeningIds: Set<String> = emptySet(),
    val summarySheet: SummaryResponse? = null,
    val sourceFilter: String = "All",
    val hideHeartbeat: Boolean = false,
    val hideScheduled: Boolean = false,
    // 空集合表示"全部"，避免 source 为 null 或非已知来源的 session 被永久隐藏
    val selectedSources: Set<String> = emptySet(),
    val unreadSessionIds: Set<String> = emptySet(),
) {
    val filteredSessions: List<SessionInfo>
        get() = if (selectedSources.isEmpty()) sessions
        else sessions.filter { s -> selectedSources.contains(s.source ?: "") }
}

@HiltViewModel
class SessionsViewModel @Inject constructor(
    private val repository: EthanRepository,
) : ViewModel() {
    private val _state = MutableStateFlow(SessionsUiState())
    val state: StateFlow<SessionsUiState> = _state.asStateFlow()
    private var pollJob: Job? = null

    // 记录每个 session 上次已知的 updatedAt，用于检测新消息
    private val knownUpdatedAt = mutableMapOf<String, Long>()

    init {
        load()
        startPolling()
    }

    private fun startPolling() {
        pollJob?.cancel()
        pollJob = viewModelScope.launch {
            while (isActive) {
                delay(3000)
                if (_state.value.query.isBlank()) refreshQuietly()
            }
        }
    }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            try {
                val query = _state.value.query
                val sessions = repository.getSessions(limit = 50, query = query.ifBlank { null })
                // 只在非搜索时检测未读，避免搜索匹配到的 session 被误标为未读
                if (query.isBlank()) {
                    if (knownUpdatedAt.isEmpty()) {
                        sessions.forEach { s -> knownUpdatedAt[s.id] = s.updatedAt }
                    } else {
                        detectUnread(sessions)
                    }
                }
                _state.update { it.copy(sessions = sessions, isLoading = false) }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    private suspend fun refreshQuietly() {
        try {
            val sessions = repository.poll()
            if (_state.value.query.isBlank()) {
                detectUnread(sessions)
                _state.update { it.copy(sessions = sessions) }
            }
        } catch (_: Exception) {}
    }

    private fun detectUnread(sessions: List<SessionInfo>) {
        val newUnread = mutableSetOf<String>()
        for (s in sessions) {
            val known = knownUpdatedAt[s.id]
            if (known != null && s.updatedAt > known) {
                // session 有更新 → 标记为未读
                newUnread.add(s.id)
            } else if (known == null) {
                // 全新 session → 标记为未读
                newUnread.add(s.id)
                knownUpdatedAt[s.id] = s.updatedAt
            }
        }
        if (newUnread.isNotEmpty()) {
            _state.update { it.copy(unreadSessionIds = it.unreadSessionIds + newUnread) }
        }
    }

    /** 用户打开了某个 session，清除其未读标记 */
    fun markRead(sessionId: String) {
        val session = _state.value.sessions.find { it.id == sessionId }
        if (session != null) {
            knownUpdatedAt[sessionId] = session.updatedAt
        }
        _state.update { it.copy(unreadSessionIds = it.unreadSessionIds - sessionId) }
    }

    fun onQueryChange(query: String) {
        _state.update { it.copy(query = query) }
        viewModelScope.launch { delay(300); load() }
    }

    fun startRename(session: SessionInfo) {
        _state.update { it.copy(renameTarget = session, renameText = session.title) }
    }

    fun onRenameTextChange(text: String) { _state.update { it.copy(renameText = text) } }

    fun confirmRename() {
        val target = _state.value.renameTarget ?: return
        viewModelScope.launch {
            try {
                repository.renameSession(target.id, _state.value.renameText)
                _state.update { it.copy(renameTarget = null) }
                load()
            } catch (e: Exception) {
                _state.update { it.copy(error = repository.friendlyError(e)) }
            }
        }
    }

    fun cancelRename() { _state.update { it.copy(renameTarget = null) } }

    fun deleteSession(id: String) {
        viewModelScope.launch {
            try { repository.deleteSession(id); load() }
            catch (e: Exception) { _state.update { it.copy(error = repository.friendlyError(e)) } }
        }
    }

    fun regenTitle(id: String) {
        viewModelScope.launch {
            _state.update { it.copy(regeningIds = it.regeningIds + id) }
            try {
                val resp = repository.regenTitle(id)
                if (resp.ok) {
                    _state.update { s ->
                        s.copy(
                            sessions = s.sessions.map { if (it.id == id) it.copy(title = resp.title) else it },
                            regeningIds = s.regeningIds - id,
                        )
                    }
                } else {
                    _state.update { it.copy(regeningIds = it.regeningIds - id, error = resp.error ?: "重生成失败") }
                }
            } catch (e: Exception) {
                _state.update { it.copy(regeningIds = it.regeningIds - id, error = repository.friendlyError(e)) }
            }
        }
    }

    fun summarySession(id: String) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val resp = repository.summarySession(id)
                _state.update { it.copy(isLoading = false, summarySheet = resp) }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }

    fun dismissSummary() { _state.update { it.copy(summarySheet = null) } }
    fun setSourceFilter(source: String) { _state.update { it.copy(sourceFilter = source) } }
    fun toggleHideHeartbeat() { _state.update { it.copy(hideHeartbeat = !it.hideHeartbeat) } }
    fun toggleHideScheduled() { _state.update { it.copy(hideScheduled = !it.hideScheduled) } }
    fun toggleSource(source: String) {
        _state.update { st ->
            val current = st.selectedSources
            val next = if (current.contains(source)) current - source else current + source
            st.copy(selectedSources = next)
        }
    }
    /** 清空来源筛选，显示全部 session */
    fun selectAllSources() { _state.update { it.copy(selectedSources = emptySet()) } }
    fun clearError() { _state.update { it.copy(error = null) } }
}
