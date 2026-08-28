package com.ethan.agent.shared

import com.ethan.agent.core.datastore.AppConfig
import com.ethan.agent.core.datastore.AppConfigStore
import com.ethan.agent.core.model.AgendaCreateRequest
import com.ethan.agent.core.model.AgendaEnabledRequest
import com.ethan.agent.core.model.AgendaPatchRequest
import com.ethan.agent.core.model.AgendaResponse
import com.ethan.agent.core.model.AgentSettings
import com.ethan.agent.core.model.ApiKeyCreated
import com.ethan.agent.core.model.ApiKeyInfo
import com.ethan.agent.core.model.AuthResponse
import com.ethan.agent.core.model.ChannelInfo
import com.ethan.agent.core.model.ChatMessage
import com.ethan.agent.core.model.ChatRequest
import com.ethan.agent.core.model.ChatStreamEvent
import com.ethan.agent.core.model.CompactResponse
import com.ethan.agent.core.model.ConsentInfo
import com.ethan.agent.core.model.CreateSessionResponse
import com.ethan.agent.core.model.DocContent
import com.ethan.agent.core.model.DocMeta
import com.ethan.agent.core.model.Episode
import com.ethan.agent.core.model.Fact
import com.ethan.agent.core.model.FactUpdateRequest
import com.ethan.agent.core.model.KnowledgeCreateRequest
import com.ethan.agent.core.model.KnowledgeItem
import com.ethan.agent.core.model.KnowledgeUpdateRequest
import com.ethan.agent.core.model.ModeEntry
import com.ethan.agent.core.model.ModelEntry
import com.ethan.agent.core.model.OnboardingCompleteRequest
import com.ethan.agent.core.model.OnboardingStatus
import com.ethan.agent.core.model.Procedure
import com.ethan.agent.core.model.ProviderConfig
import com.ethan.agent.core.model.Quote
import com.ethan.agent.core.model.RenameSessionRequest
import com.ethan.agent.core.model.ScheduleJob
import com.ethan.agent.core.model.SchedulePatchRequest
import com.ethan.agent.core.model.SessionDetail
import com.ethan.agent.core.model.SessionInfo
import com.ethan.agent.core.model.SkillInfo
import com.ethan.agent.core.model.SystemPromptPreview
import com.ethan.agent.core.model.SystemSettings
import com.ethan.agent.core.model.Annotation
import com.ethan.agent.core.model.AnnotationCreateRequest
import com.ethan.agent.core.model.AnnotationCreateResponse
import com.ethan.agent.core.model.AnnotationsResponse
import com.ethan.agent.core.model.BatchAnnotationsResponse
import com.ethan.agent.core.model.BackgroundTask
import com.ethan.agent.core.model.BackgroundTasksResponse
import com.ethan.agent.core.model.StopBackgroundTaskResponse
import com.ethan.agent.core.model.ConfirmRecordResponse
import com.ethan.agent.core.model.ConsolidateResponse
import com.ethan.agent.core.model.DailySummariesResponse
import com.ethan.agent.core.model.DeckResponse
import com.ethan.agent.core.model.DeleteAnnotationResponse
import com.ethan.agent.core.model.DeleteMessageResponse
import com.ethan.agent.core.model.FastRulesPatch
import com.ethan.agent.core.model.FastRulesResponse
import com.ethan.agent.core.model.FastRuleOptionsResponse
import com.ethan.agent.core.model.InsightItem
import com.ethan.agent.core.model.InsightsByDateResponse
import com.ethan.agent.core.model.InsightsListResponse
import com.ethan.agent.core.model.InjectRequest
import com.ethan.agent.core.model.InjectResponse
import com.ethan.agent.core.model.KnowledgeValidateRequest
import com.ethan.agent.core.model.KnowledgeValidateResponse
import com.ethan.agent.core.model.LarkDepsStatus
import com.ethan.agent.core.model.RegenTitleResponse
import com.ethan.agent.core.model.RecordDetailResponse
import com.ethan.agent.core.model.RecordEvidenceResponse
import com.ethan.agent.core.model.RecordListResponse
import com.ethan.agent.core.model.ScheduleCreateRequest
import com.ethan.agent.core.model.SignRequest
import com.ethan.agent.core.model.SignResponse
import com.ethan.agent.core.model.StopChatResponse
import com.ethan.agent.core.model.StructuredRecord
import com.ethan.agent.core.model.SummaryResponse
import com.ethan.agent.core.model.TimelineActionResponse
import com.ethan.agent.core.model.TimelineExportRequest
import com.ethan.agent.core.model.TimelineExportResponse
import com.ethan.agent.core.model.TimelineImportRequest
import com.ethan.agent.core.model.TimelineStatusResponse
import com.ethan.agent.core.model.TimelineValidateRequest
import com.ethan.agent.core.model.ToolTiersResponse
import com.ethan.agent.core.model.UpdateRecordRequest
import com.ethan.agent.core.model.UpdateRecordResponse
import com.ethan.agent.core.network.ApiException
import com.ethan.agent.core.network.ChatSseClient
import com.ethan.agent.core.network.EthanApiService
import kotlinx.serialization.SerializationException
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.map

class EthanRepository(
    private val configStore: AppConfigStore,
    private val api: EthanApiService,
    private val sseClient: ChatSseClient,
    private val serverUrlCache: ServerUrlCache,
    private val localCache: LocalCache,
) {
    val config: Flow<AppConfig> = configStore.config

    val isLoggedIn: Flow<Boolean> = config.map { it.authToken.isNotBlank() }

    /** 超级权限开关（持久化偏好，跨会话/重启保留） */
    val autoConsent: Flow<Boolean> = config.map { it.autoConsentEnabled }

    suspend fun setAutoConsent(enabled: Boolean) {
        configStore.setAutoConsentEnabled(enabled)
    }

    suspend fun repairStoredUrlIfNeeded() {
        configStore.repairStoredUrlIfNeeded()
    }

    suspend fun saveServerUrl(url: String) {
        val normalized = com.ethan.agent.core.model.ServerUrlUtils.normalize(url)
            ?: throw IllegalArgumentException("无效的服务器地址，请填写如 https://chat.example.com:29999")
        // 先同步更新缓存，让紧随其后的请求立即命中新地址（不等 DataStore collect 回来）
        serverUrlCache.set(normalized)
        configStore.saveServerUrl(normalized)
    }

    suspend fun login(token: String, serverUrl: String? = null): Result<AuthResponse> = runCatching {
        if (!serverUrl.isNullOrBlank()) {
            saveServerUrl(serverUrl)
        }
        val response = api.auth(com.ethan.agent.core.model.AuthRequest(token))
        if (response.ok) {
            configStore.saveAuth(token, response.userId, response.userName, response.isAdmin)
        } else {
            error("Invalid token")
        }
        response
    }.recoverCatching { e ->
        if (e is ApiException && e.code == 401) error("认证失败，请检查 Token")
        throw e
    }

    suspend fun logout() {
        configStore.clearAuth()
    }

    suspend fun checkHealth(): String? = runCatching {
        api.health().version
    }.getOrNull()

    suspend fun getModels(): List<ModelEntry> {
        return api.getModels().models
    }

    suspend fun getModes(): List<ModeEntry> {
        return api.getModes().modes
    }

    suspend fun getSessions(limit: Int = 50, offset: Int = 0, query: String? = null): List<SessionInfo> {
        return api.getSessions(limit, offset, query).sessions
    }

    suspend fun poll(): List<SessionInfo> {
        return api.poll().sessions
    }

    // ---------- Stale-while-revalidate cached Flows ----------
    // 每个 cachedXxx() 先 emit 本地缓存（如有），再请求网络 emit 最新数据并写缓存。
    // 网络失败时，如果有缓存数据，调用方已经拿到了缓存；如果没有缓存，异常会传播给调用方。

    fun cachedSessions(limit: Int = 50, offset: Int = 0, query: String? = null): Flow<List<SessionInfo>> = flow {
        val cacheKey = "sessions_list"
        localCache.read(cacheKey, ListSerializer(SessionInfo.serializer()))?.let { emit(it) }
        val fresh = getSessions(limit, offset, query)
        localCache.write(cacheKey, fresh, ListSerializer(SessionInfo.serializer()))
        emit(fresh)
    }.flowOn(ioDispatcher)

    fun cachedSession(id: String): Flow<SessionDetail> = flow {
        val cacheKey = "session_$id"
        localCache.read(cacheKey, SessionDetail.serializer())?.let { emit(it) }
        val fresh = getSession(id)
        localCache.write(cacheKey, fresh, SessionDetail.serializer())
        emit(fresh)
    }.flowOn(ioDispatcher)

    fun cachedModels(): Flow<List<ModelEntry>> = flow {
        val cacheKey = "models"
        localCache.read(cacheKey, ListSerializer(ModelEntry.serializer()))?.let { emit(it) }
        val fresh = getModels()
        localCache.write(cacheKey, fresh, ListSerializer(ModelEntry.serializer()))
        emit(fresh)
    }.flowOn(ioDispatcher)

    fun cachedModes(): Flow<List<ModeEntry>> = flow {
        val cacheKey = "modes"
        localCache.read(cacheKey, ListSerializer(ModeEntry.serializer()))?.let { emit(it) }
        val fresh = getModes()
        localCache.write(cacheKey, fresh, ListSerializer(ModeEntry.serializer()))
        emit(fresh)
    }.flowOn(ioDispatcher)

    fun cachedAgentSettings(): Flow<AgentSettings> = flow {
        val cacheKey = "agent_settings"
        localCache.read(cacheKey, AgentSettings.serializer())?.let { emit(it) }
        val fresh = getAgentSettings()
        localCache.write(cacheKey, fresh, AgentSettings.serializer())
        emit(fresh)
    }.flowOn(ioDispatcher)

    fun cachedSystemSettings(): Flow<SystemSettings> = flow {
        val cacheKey = "system_settings"
        localCache.read(cacheKey, SystemSettings.serializer())?.let { emit(it) }
        val fresh = getSystemSettings()
        localCache.write(cacheKey, fresh, SystemSettings.serializer())
        emit(fresh)
    }.flowOn(ioDispatcher)

    fun cachedFacts(): Flow<List<Fact>> = flow {
        val cacheKey = "facts"
        localCache.read(cacheKey, ListSerializer(Fact.serializer()))?.let { emit(it) }
        val fresh = getFacts()
        localCache.write(cacheKey, fresh, ListSerializer(Fact.serializer()))
        emit(fresh)
    }.flowOn(ioDispatcher)

    fun cachedProcedures(): Flow<List<Procedure>> = flow {
        val cacheKey = "procedures"
        localCache.read(cacheKey, ListSerializer(Procedure.serializer()))?.let { emit(it) }
        val fresh = getProcedures()
        localCache.write(cacheKey, fresh, ListSerializer(Procedure.serializer()))
        emit(fresh)
    }.flowOn(ioDispatcher)

    fun cachedSkills(): Flow<List<SkillInfo>> = flow {
        val cacheKey = "skills"
        localCache.read(cacheKey, ListSerializer(SkillInfo.serializer()))?.let { emit(it) }
        val fresh = getSkills()
        localCache.write(cacheKey, fresh, ListSerializer(SkillInfo.serializer()))
        emit(fresh)
    }.flowOn(ioDispatcher)

    fun cachedKnowledge(query: String? = null, mode: String? = null): Flow<List<KnowledgeItem>> = flow {
        val cacheKey = "knowledge_${query ?: "all"}_${mode ?: "default"}"
        localCache.read(cacheKey, ListSerializer(KnowledgeItem.serializer()))?.let { emit(it) }
        val fresh = getKnowledge(query, mode)
        localCache.write(cacheKey, fresh, ListSerializer(KnowledgeItem.serializer()))
        emit(fresh)
    }.flowOn(ioDispatcher)

    /** 删除 session 时同步清除该 session 的缓存。 */
    suspend fun deleteSessionCached(id: String) {
        deleteSession(id)
        localCache.remove("session_$id")
    }

    suspend fun createSession(model: String? = null, mode: String? = null): CreateSessionResponse {
        return api.createSession(model, mode)
    }

    suspend fun getSession(id: String): SessionDetail {
        return api.getSession(id)
    }

    suspend fun renameSession(id: String, title: String) {
        api.renameSession(id, RenameSessionRequest(title))
    }

    suspend fun deleteSession(id: String) {
        api.deleteSession(id)
    }

    suspend fun compactSession(id: String): CompactResponse {
        return api.compactSession(id)
    }

    fun streamChat(
        messages: List<ChatMessage>,
        model: String?,
        sessionId: String?,
        quote: Quote?,
        mode: String?,
        autoConsent: Boolean = false,
    ): Flow<ChatStreamEvent> = flow {
        val cfg = configStore.config.first()
        val request = ChatRequest(
            messages = messages,
            model = model,
            stream = true,
            sessionId = sessionId,
            quote = quote,
            mode = mode?.ifBlank { null },
            autoConsent = autoConsent,
        )
        sseClient.streamChat(request).collect { emit(it) }
    }.flowOn(ioDispatcher)

    suspend fun respondConsent(requestId: String, allowed: Boolean) {
        api.respondConsent(requestId, com.ethan.agent.core.model.ConsentRequest(allowed))
    }

    /** ask_user / wait_for_user 卡片回传用户的选择/确认。失败抛异常，调用方保留卡片可重试。 */
    suspend fun respondAskUser(requestId: String, value: String) {
        api.respondAskUser(requestId, com.ethan.agent.core.model.InteractionValueRequest(value))
    }

    suspend fun respondWaitForUser(requestId: String, value: String) {
        api.respondWaitForUser(requestId, com.ethan.agent.core.model.InteractionValueRequest(value))
    }

    // ── 会话置顶 ────────────────────────────────────────────────────────────

    suspend fun pinSession(id: String) {
        api.pinSession(id)
    }

    suspend fun unpinSession(id: String) {
        api.unpinSession(id)
    }

    suspend fun getPinnedSessions(): List<SessionInfo> {
        return api.getPinnedSessions().sessions
    }

    suspend fun uploadAttachment(data: ByteArray, filename: String): String {
        return api.uploadFile(data, filename, "application/octet-stream").path
    }

    suspend fun getAgentSettings(): AgentSettings {
        return api.getAgentSettings()
    }

    suspend fun updateAgentSettings(patch: AgentSettings) {
        api.updateAgentSettings(patch)
    }

    suspend fun getProviderSettings(): Map<String, ProviderConfig> {
        return api.getProviderSettings()
    }

    suspend fun updateProviderSettings(patch: Map<String, ProviderConfig>) {
        api.updateProviderSettings(patch)
    }

    suspend fun getSystemSettings(): SystemSettings {
        return api.getSystemSettings()
    }

    suspend fun updateSystemSettings(patch: SystemSettings) {
        api.updateSystemSettings(patch)
    }

    suspend fun getUserProfile(): String {
        return api.getUserProfile().content
    }

    suspend fun updateUserProfile(content: String) {
        api.updateUserProfile(com.ethan.agent.core.model.ProfileRequest(content))
    }

    suspend fun getSystemPromptPreview(): SystemPromptPreview {
        return api.getSystemPromptPreview()
    }

    suspend fun getFacts(): List<Fact> {
        return api.getFacts().facts
    }

    suspend fun updateFact(id: String, content: String) {
        api.updateFact(id, FactUpdateRequest(content))
    }

    suspend fun deleteFact(id: String) {
        api.deleteFact(id)
    }

    suspend fun getEpisodes(): List<Episode> {
        return api.getEpisodes().episodes
    }

    suspend fun deleteEpisode(id: String) {
        api.deleteEpisode(id)
    }

    suspend fun getProcedures(): List<Procedure> {
        return api.getProcedures().procedures
    }

    suspend fun deleteProcedure(id: String) {
        api.deleteProcedure(id)
    }

    suspend fun getSchedules(): List<ScheduleJob> {
        return api.getSchedules().jobs
    }

    suspend fun patchSchedule(jobId: String, state: String) {
        api.patchSchedule(jobId, SchedulePatchRequest(state))
    }

    suspend fun deleteSchedule(jobId: String) {
        api.deleteSchedule(jobId)
    }

    suspend fun getKnowledge(query: String? = null, mode: String? = null): List<KnowledgeItem> {
        return api.getKnowledge(query, mode).items
    }

    suspend fun searchKnowledge(query: String, semantic: Boolean = true): List<KnowledgeItem> {
        return api.searchKnowledge(query, semantic = semantic).results
    }

    suspend fun addKnowledge(title: String, content: String, tags: List<String>) {
        api.addKnowledge(KnowledgeCreateRequest(title, content, tags))
    }

    suspend fun updateKnowledge(source: String, title: String, content: String, tags: List<String>) {
        api.updateKnowledge(source, KnowledgeUpdateRequest(title, content, tags))
    }

    suspend fun deleteKnowledge(source: String) {
        api.deleteKnowledge(source)
    }

    suspend fun getSkills(): List<SkillInfo> {
        return api.getSkills().skills
    }

    suspend fun getSkill(name: String): SkillInfo {
        return api.getSkill(name)
    }

    suspend fun saveSkill(skill: SkillInfo) {
        api.saveSkill(skill)
    }

    suspend fun deleteSkill(name: String) {
        api.deleteSkill(name)
    }

    suspend fun getOnboardingStatus(): OnboardingStatus {
        return api.getOnboardingStatus()
    }

    suspend fun completeOnboarding(agentName: String, userInfo: String) {
        api.completeOnboarding(OnboardingCompleteRequest(agentName, userInfo))
    }

    suspend fun getChannels(): List<ChannelInfo> {
        return api.getChannels().channels
    }

    suspend fun patchChannel(channelId: String, config: Map<String, String>) {
        api.patchChannel(com.ethan.agent.core.model.ChannelPatchRequest(channelId, config))
    }

    suspend fun getDocsList(): List<DocMeta> {
        return api.getDocsList().docs
    }

    suspend fun getDoc(slug: String): DocContent {
        return api.getDoc(slug)
    }

    suspend fun getApiKeys(): List<ApiKeyInfo> {
        return api.getApiKeys().keys
    }

    suspend fun createApiKey(name: String): ApiKeyCreated {
        return api.createApiKey(com.ethan.agent.core.model.ApiKeyCreateRequest(name))
    }

    suspend fun deleteApiKey(id: String) {
        api.deleteApiKey(id)
    }

    suspend fun getLogs(type: String = "backend", lines: Int = 500, query: String? = null): String {
        return api.getLogs(type, lines, query).content
    }

    // ── Sessions 扩展 ──────────────────────────────────────────────────────

    suspend fun regenTitle(id: String): RegenTitleResponse {
        return api.regenTitle(id)
    }

    suspend fun summarySession(id: String): SummaryResponse {
        return api.summarySession(id)
    }

    suspend fun deleteMessage(sessionId: String, messageId: Long): DeleteMessageResponse {
        return api.deleteMessage(sessionId, messageId)
    }

    // ── Chat 扩展（非 SSE） ────────────────────────────────────────────────

    /** 重连进行中的生成：返回 SSE Flow，204（无活跃 run）时返回空流。 */
    fun resumeStream(sessionId: String): Flow<ChatStreamEvent> = flow {
        sseClient.resumeStream(sessionId).collect { emit(it) }
    }.flowOn(ioDispatcher)

    suspend fun stopChat(sessionId: String): StopChatResponse {
        return api.stopChat(sessionId)
    }

    suspend fun injectMessage(sessionId: String, content: String): InjectResponse {
        return api.injectMessage(sessionId, InjectRequest(content))
    }

    // ── Models 扩展 ────────────────────────────────────────────────────────

    suspend fun updateModel(provider: String, modelId: String, model: ModelEntry) {
        api.updateModel(provider, modelId, model)
    }

    // ── Memory: Insights 永久记忆 ─────────────────────────────────────────

    suspend fun getInsights(limit: Int = 20, offset: Int = 0): InsightsListResponse {
        return api.getInsights(limit, offset)
    }

    suspend fun getInsightsByDate(dateStr: String): InsightsByDateResponse {
        return api.getInsightsByDate(dateStr)
    }

    suspend fun consolidateMemory(): ConsolidateResponse {
        return api.consolidateMemory()
    }

    // ── Memory: Structured records 结构化记忆 ─────────────────────────────

    suspend fun getRecords(
        type: String? = null,
        status: String? = null,
        domain: String? = null,
        limit: Int = 50,
        offset: Int = 0,
    ): RecordListResponse {
        return api.getRecords(type, status, domain, limit, offset)
    }

    suspend fun searchRecords(
        query: String,
        type: String? = null,
        domain: String? = null,
        status: String? = null,
        limit: Int = 20,
    ): RecordListResponse {
        return api.searchRecords(query, type, domain, status, limit)
    }

    suspend fun getRecord(id: String): RecordDetailResponse {
        return api.getRecord(id)
    }

    suspend fun getRecordEvidence(id: String): RecordEvidenceResponse {
        return api.getRecordEvidence(id)
    }

    suspend fun updateRecord(id: String, body: UpdateRecordRequest): UpdateRecordResponse {
        return api.updateRecord(id, body)
    }

    suspend fun deleteRecord(id: String) {
        api.deleteRecord(id)
    }

    suspend fun confirmRecord(id: String): ConfirmRecordResponse {
        return api.confirmRecord(id)
    }

    suspend fun consolidateRecords(targetDate: String? = null): ConsolidateResponse {
        return api.consolidateRecords(targetDate)
    }

    suspend fun getDailySummaries(domain: String? = null, limit: Int = 30): DailySummariesResponse {
        return api.getDailySummaries(domain, limit)
    }

    suspend fun getDailySummaryByDate(dateStr: String, domain: String? = null): DailySummariesResponse {
        return api.getDailySummaryByDate(dateStr, domain)
    }

    // ── Schedule 扩展 ─────────────────────────────────────────────────────

    suspend fun createSchedule(body: ScheduleCreateRequest) {
        api.createSchedule(body)
    }

    suspend fun triggerSchedule(jobId: String) {
        api.triggerSchedule(jobId)
    }

    // ── Schedule: Timeline 时间线 ─────────────────────────────────────────

    suspend fun getTimelineStatus(): TimelineStatusResponse {
        return api.getTimelineStatus()
    }

    suspend fun syncTimelines() {
        api.syncTimelines()
    }

    suspend fun timelineLifecycle(timelineId: String, action: String): TimelineActionResponse {
        return api.timelineLifecycle(timelineId, action)
    }

    suspend fun exportTimeline(body: TimelineExportRequest): TimelineExportResponse {
        return api.exportTimeline(body)
    }

    suspend fun importTimeline(body: TimelineImportRequest): TimelineActionResponse {
        return api.importTimeline(body)
    }

    suspend fun validateTimeline(body: TimelineValidateRequest): TimelineActionResponse {
        return api.validateTimeline(body)
    }

    suspend fun syncTimelineToLark(timelineId: String): TimelineActionResponse {
        return api.syncTimelineToLark(timelineId)
    }

    suspend fun cleanupTimelineLark(timelineId: String): TimelineActionResponse {
        return api.cleanupTimelineLark(timelineId)
    }

    // ── Settings 扩展 ─────────────────────────────────────────────────────

    suspend fun getToolTiers(model: String? = null): ToolTiersResponse {
        return api.getToolTiers(model)
    }

    suspend fun getFastRules(): FastRulesResponse {
        return api.getFastRules()
    }

    suspend fun getFastRuleOptions(model: String? = null): FastRuleOptionsResponse {
        return api.getFastRuleOptions(model)
    }

    suspend fun updateFastRules(body: FastRulesPatch) {
        api.updateFastRules(body)
    }

    suspend fun validateKnowledgeBackend(body: KnowledgeValidateRequest): KnowledgeValidateResponse {
        return api.validateKnowledgeBackend(body)
    }

    suspend fun getLarkDepsStatus(): LarkDepsStatus {
        return api.getLarkDepsStatus()
    }

    suspend fun installLarkDeps() {
        api.installLarkDeps()
    }

    // ── Background Tasks ──────────────────────────────────────────────────

    suspend fun getBackgroundTasks(): List<BackgroundTask> {
        return api.getBackgroundTasks().tasks
    }

    suspend fun stopBackgroundTask(taskId: String): StopBackgroundTaskResponse {
        return api.stopBackgroundTask(taskId)
    }

    // ── Annotations 标注 ──────────────────────────────────────────────────

    suspend fun getAnnotations(messageId: Long): AnnotationsResponse {
        return api.getAnnotations(messageId)
    }

    suspend fun batchGetAnnotations(ids: List<Long>): BatchAnnotationsResponse {
        return api.batchGetAnnotations(ids.joinToString(","))
    }

    suspend fun createAnnotation(body: AnnotationCreateRequest): AnnotationCreateResponse {
        return api.createAnnotation(body)
    }

    suspend fun deleteAnnotation(annoId: Long): DeleteAnnotationResponse {
        return api.deleteAnnotation(annoId)
    }

    // ── Files / 资产 ──────────────────────────────────────────────────────

    suspend fun signFiles(paths: List<String>): SignResponse {
        return api.signFiles(SignRequest(paths))
    }

    suspend fun getDeck(path: String, sessionId: String = ""): DeckResponse {
        return api.getDeck(path, sessionId)
    }

    suspend fun setDarkTheme(dark: Boolean) {
        configStore.setDarkTheme(dark)
    }

    suspend fun setThemeId(themeId: String) {
        configStore.setThemeId(themeId)
    }

    suspend fun setAppLockEnabled(enabled: Boolean) {
        configStore.setAppLockEnabled(enabled)
    }

    /** 清空本地文件缓存（Settings 「清空缓存」入口用）。 */
    suspend fun clearLocalCache() {
        localCache.clear()
    }

    // ── Agenda 日程 ─────────────────────────────────────────────────────────

    suspend fun getAgenda(): AgendaResponse = api.getAgenda()

    suspend fun createAgenda(body: AgendaCreateRequest) {
        api.createAgenda(body)
    }

    suspend fun patchAgenda(eventId: String, body: AgendaPatchRequest) {
        api.patchAgenda(eventId, body)
    }

    suspend fun deleteAgenda(eventId: String) {
        api.deleteAgenda(eventId)
    }

    suspend fun setAgendaEnabled(enabled: Boolean) {
        api.setAgendaEnabled(AgendaEnabledRequest(enabled))
    }

    fun friendlyError(e: Throwable): String = when (e) {
        is ApiException -> when (e.code) {
            401 -> "未授权，请重新登录"
            404 -> "资源不存在"
            else -> e.message.ifBlank { "请求失败 (${e.code})" }
        }
        is SerializationException -> {
            val msg = e.message.orEmpty()
            if (msg.contains("<") || msg.contains("<!DOCTYPE", ignoreCase = true)) {
                "服务器返回了网页而非 API 数据，请检查服务器地址"
            } else {
                msg.ifBlank { "数据解析失败" }
            }
        }
        else -> e.message ?: "未知错误"
    }
}

/** 渲染用图片：displayUrl 是 dataUrl（新发送）或完整远程 URL（历史消息）。 */
data class UiMessageImage(
    val displayUrl: String,
)

data class UiMessage(
    val role: String,
    val content: String,
    val toolSteps: List<com.ethan.agent.core.model.ToolStep> = emptyList(),
    val usage: com.ethan.agent.core.model.Usage? = null,
    val quote: Quote? = null,
    val isStreaming: Boolean = false,
    val createdAt: Long? = null,
    val ttfbMs: Long? = null,
    val totalDurationMs: Long? = null,
    val generationDurationMs: Long? = null,
    val images: List<UiMessageImage> = emptyList(),
    val cards: List<com.ethan.agent.core.model.FileCard> = emptyList(),
)
