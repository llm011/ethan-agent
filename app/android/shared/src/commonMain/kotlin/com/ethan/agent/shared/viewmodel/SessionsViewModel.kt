package com.ethan.agent.shared.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ethan.agent.core.model.SessionInfo
import com.ethan.agent.core.model.SummaryResponse
import com.ethan.agent.shared.EthanRepository
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * 定时/心跳会话判定，与 web（all-sessions-view / schedule-view）同口径：
 * 「source 或标题前缀」双条件。后端定时会话的 source 是 "schedule"（不是
 * "scheduled"），心跳是 "heartbeat"；老数据可能只有 [定时]/[心跳] 前缀。
 */
fun isScheduledSession(s: SessionInfo): Boolean =
    s.source == "schedule" || s.title.startsWith("[定时]")

fun isHeartbeatSession(s: SessionInfo): Boolean =
    s.source == "heartbeat" || s.title.startsWith("[心跳]")

/**
 * 后台任务会话（background_task 工具创建的独立会话）：标题带 [后台] 前缀，
 * 完成后是 "✅ [后台]"（与服务端 hide_background 的排除列表一致）。
 * 它们的入口在任务中心，不该混进常规会话列表。
 */
fun isBackgroundSession(s: SessionInfo): Boolean =
    s.title.startsWith("[后台]") || s.title.startsWith("✅ [后台]")

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
    // 类别筛选（对齐 web all-sessions-view 的排他 categoryFilter）：
    // "" = 全部对话（排除定时/心跳），"scheduled" = 定时任务对话，"heartbeat" = 心跳对话
    val categoryFilter: String = "",
    // 空集合表示"全部"，避免 source 为 null 或非已知来源的 session 被永久隐藏
    val selectedSources: Set<String> = emptySet(),
    val unreadSessionIds: Set<String> = emptySet(),
    /**
     * 抽屉数据源：**未过滤**的全量列表。主列表（sessions）默认视图已在服务端
     * 排除定时/心跳/后台会话，而抽屉恰恰要展示这三类的专属分组 —— 两者必须分开喂。
     */
    val drawerSessions: List<SessionInfo> = emptyList(),
) {
    /** 按类别筛选：默认「全部对话」不显示定时/心跳/后台（对齐 web —— 它们有专属入口） */
    private val categoryFiltered: List<SessionInfo>
        get() = when (categoryFilter) {
            "scheduled" -> sessions.filter(::isScheduledSession)
            "heartbeat" -> sessions.filter(::isHeartbeatSession)
            else -> sessions.filter { !isScheduledSession(it) && !isHeartbeatSession(it) && !isBackgroundSession(it) }
        }

    /** 按来源筛选后的全集（空集合表示全部），置顶与普通列表共用，保证筛选行为一致 */
    private val sourceFiltered: List<SessionInfo>
        get() {
            val base = categoryFiltered
            return if (selectedSources.isEmpty()) base
            else base.filter { s -> selectedSources.contains(s.source ?: "") }
        }

    /** 置顶分组：pinned_at > 0，按置顶时间倒序（同样套用来源筛选） */
    val pinnedSessions: List<SessionInfo>
        get() = sourceFiltered.filter { it.pinnedAt > 0 }.sortedByDescending { it.pinnedAt }

    /** 普通列表：排除置顶（置顶在顶部独立分组展示） */
    val filteredSessions: List<SessionInfo>
        get() = sourceFiltered.filter { it.pinnedAt == 0L }
}

class SessionsViewModel(
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
        // 定时/心跳类别激活时 load 走类别专用加载：重命名/删除等操作完成后的刷新
        // 也要留在当前类别视图里，否则默认列表（服务端已排除该类）一灌进来视图就空了
        val cat = _state.value.categoryFilter
        val query = _state.value.query
        if (query.isBlank() && (cat == "scheduled" || cat == "heartbeat")) {
            fetchCategory(cat)
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            // 抽屉要的未过滤列表单独拉一次：不能复用 cachedSessions（那里的缓存
            // 现在带 hide_* 过滤参数，读出来会缺定时/心跳，抽屉分组就空了）
            launch {
                try {
                    _state.update { it.copy(drawerSessions = repository.poll()) }
                } catch (_: Exception) {}
            }
            if (query.isBlank()) {
                // 非搜索：用 cached flow，先秒出缓存再网络刷新。
                // 服务端过滤对齐 web：默认视图就不含定时/心跳/后台会话（各有专属入口），
                // 否则这三类会刷屏 —— 之前 50 条窗口里大半是定时任务，普通对话反而看不到。
                // 客户端的 categoryFiltered 仍做一道兜底（缓存里的旧数据未过滤）。
                try {
                    repository.cachedSessions(limit = 50, hideHeartbeat = true, hideScheduled = true, hideBackground = true).collect { sessions ->
                        if (knownUpdatedAt.isEmpty()) {
                            sessions.forEach { s -> knownUpdatedAt[s.id] = s.updatedAt }
                        } else {
                            detectUnread(sessions)
                        }
                        _state.update { it.copy(sessions = sessions, isLoading = false) }
                    }
                } catch (e: Exception) {
                    if (_state.value.sessions.isEmpty()) {
                        _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
                    } else {
                        _state.update { it.copy(isLoading = false) }
                    }
                }
            } else {
                // 搜索：直接请求网络，不缓存。搜索与类别筛选 AND 合成（对齐 web）：
                // 在定时/心跳类别下搜索，只搜该类会话
                try {
                    val prefixes = when (_state.value.categoryFilter) {
                        "scheduled" -> "[定时]"
                        "heartbeat" -> "[心跳]"
                        else -> null
                    }
                    val sessions = repository.getSessions(limit = 50, query = query, titlePrefixes = prefixes)
                    _state.update { it.copy(sessions = sessions, isLoading = false) }
                } catch (e: Exception) {
                    _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
                }
            }
        }
    }

    private suspend fun refreshQuietly() {
        try {
            val sessions = repository.poll()
            if (_state.value.query.isBlank()) {
                detectUnread(sessions)
                _state.update { st ->
                    st.copy(
                        // 抽屉始终吃未过滤全量列表（它要展示定时/心跳分组）
                        drawerSessions = sessions,
                        // 类别视图是 fetchCategory 按前缀专属拉的，轮询的全量列表不能冲掉它
                        sessions = if (st.categoryFilter.isEmpty()) sessions else st.sessions,
                    )
                }
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

    /** 置顶/取消置顶的 in-flight 会话 ID：防快速双击时两个反向操作交错（viewModelScope 在主线程，无需同步）。 */
    private val pinInFlight = mutableSetOf<String>()

    /** 置顶/取消置顶：本地乐观更新（与 Web 端一致），失败回滚并提示；下次轮询自动对齐服务端。 */
    fun togglePin(session: SessionInfo) {
        if (!pinInFlight.add(session.id)) return
        val nowSec = kotlinx.datetime.Clock.System.now().toEpochMilliseconds() / 1000
        // 乐观更新：先改本地，UI 即时反馈
        _state.update { s ->
            s.copy(
                sessions = s.sessions.map {
                    if (it.id == session.id) {
                        it.copy(pinnedAt = if (session.pinnedAt > 0) 0L else nowSec)
                    } else {
                        it
                    }
                },
            )
        }
        viewModelScope.launch {
            try {
                if (session.pinnedAt > 0) {
                    repository.unpinSession(session.id)
                } else {
                    repository.pinSession(session.id)
                }
            } catch (e: Exception) {
                // 失败回滚到操作前的状态
                _state.update { s ->
                    s.copy(
                        sessions = s.sessions.map {
                            if (it.id == session.id) it.copy(pinnedAt = session.pinnedAt) else it
                        },
                        error = repository.friendlyError(e),
                    )
                }
            } finally {
                pinInFlight.remove(session.id)
            }
        }
    }

    fun deleteSession(id: String) {
        viewModelScope.launch {
            try { repository.deleteSessionCached(id); load() }
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

    /** 类别切换（排他，对齐 web：点已选中的类别取消，回到「全部对话」）。
     *  定时/心跳类别走服务端 title_prefixes 单独拉取；回「全部对话」重新走默认 cached 加载。 */
    fun toggleCategory(category: String) {
        val next = if (_state.value.categoryFilter == category) "" else category
        _state.update { it.copy(categoryFilter = next) }
        when (next) {
            "scheduled", "heartbeat" -> fetchCategory(next)
            else -> load()
        }
    }

    /** 按类别单独拉列表（对齐 web 的 title_prefixes 请求）：只取该前缀的会话 */
    private fun fetchCategory(category: String) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val prefixes = if (category == "scheduled") "[定时]" else "[心跳]"
                val sessions = repository.getSessions(limit = 50, titlePrefixes = prefixes, hideBackground = true)
                _state.update { it.copy(sessions = sessions, isLoading = false) }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = repository.friendlyError(e)) }
            }
        }
    }
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
