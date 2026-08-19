package com.ethan.agent.core.network

import com.ethan.agent.core.model.AgentSettings
import com.ethan.agent.core.model.AgendaCreateRequest
import com.ethan.agent.core.model.AgendaEnabledRequest
import com.ethan.agent.core.model.AgendaEnabledResponse
import com.ethan.agent.core.model.AgendaEventResponse
import com.ethan.agent.core.model.AgendaPatchRequest
import com.ethan.agent.core.model.AgendaResponse
import com.ethan.agent.core.model.ApiKeyCreateRequest
import com.ethan.agent.core.model.ApiKeyCreated
import com.ethan.agent.core.model.ApiKeysResponse
import com.ethan.agent.core.model.AuthRequest
import com.ethan.agent.core.model.AuthResponse
import com.ethan.agent.core.model.ChannelPatchRequest
import com.ethan.agent.core.model.ChannelsResponse
import com.ethan.agent.core.model.CompactResponse
import com.ethan.agent.core.model.ConsentRequest
import com.ethan.agent.core.model.CreateSessionResponse
import com.ethan.agent.core.model.DiscoverModelsRequest
import com.ethan.agent.core.model.DiscoverModelsResponse
import com.ethan.agent.core.model.DocContent
import com.ethan.agent.core.model.DocsListResponse
import com.ethan.agent.core.model.EpisodesResponse
import com.ethan.agent.core.model.FactUpdateRequest
import com.ethan.agent.core.model.FactsResponse
import com.ethan.agent.core.model.HealthResponse
import com.ethan.agent.core.model.KnowledgeCreateRequest
import com.ethan.agent.core.model.KnowledgeListResponse
import com.ethan.agent.core.model.KnowledgeSearchResponse
import com.ethan.agent.core.model.KnowledgeUpdateRequest
import com.ethan.agent.core.model.LogsResponse
import com.ethan.agent.core.model.ModelEntry
import com.ethan.agent.core.model.ModelsResponse
import com.ethan.agent.core.model.ModesResponse
import com.ethan.agent.core.model.OkResponse
import com.ethan.agent.core.model.OnboardingCompleteRequest
import com.ethan.agent.core.model.OnboardingCompleteResponse
import com.ethan.agent.core.model.OnboardingStatus
import com.ethan.agent.core.model.PollData
import com.ethan.agent.core.model.PinnedSessionsResponse
import com.ethan.agent.core.model.ProceduresResponse
import com.ethan.agent.core.model.ProfileRequest
import com.ethan.agent.core.model.ProfileResponse
import com.ethan.agent.core.model.ProviderConfig
import com.ethan.agent.core.model.RenameSessionRequest
import com.ethan.agent.core.model.SaveSkillResponse
import com.ethan.agent.core.model.SchedulePatchRequest
import com.ethan.agent.core.model.ScheduleResponse
import com.ethan.agent.core.model.SessionDetail
import com.ethan.agent.core.model.SessionsResponse
import com.ethan.agent.core.model.SkillInfo
import com.ethan.agent.core.model.SkillsResponse
import com.ethan.agent.core.model.SystemPromptPreview
import com.ethan.agent.core.model.SystemSettings
import com.ethan.agent.core.model.UploadResponse
import com.ethan.agent.core.model.AnnotationCreateRequest
import com.ethan.agent.core.model.AnnotationCreateResponse
import com.ethan.agent.core.model.AnnotationsResponse
import com.ethan.agent.core.model.BackgroundTasksResponse
import com.ethan.agent.core.model.BatchAnnotationsResponse
import com.ethan.agent.core.model.ConfirmRecordResponse
import com.ethan.agent.core.model.ConsolidateResponse
import com.ethan.agent.core.model.DailySummariesResponse
import com.ethan.agent.core.model.DeckResponse
import com.ethan.agent.core.model.DeleteAnnotationResponse
import com.ethan.agent.core.model.DeleteMessageResponse
import com.ethan.agent.core.model.FastRuleOptionsResponse
import com.ethan.agent.core.model.FastRulesPatch
import com.ethan.agent.core.model.FastRulesResponse
import com.ethan.agent.core.model.InjectRequest
import com.ethan.agent.core.model.InjectResponse
import com.ethan.agent.core.model.InsightsByDateResponse
import com.ethan.agent.core.model.InsightsListResponse
import com.ethan.agent.core.model.InteractionValueRequest
import com.ethan.agent.core.model.KnowledgeValidateRequest
import com.ethan.agent.core.model.KnowledgeValidateResponse
import com.ethan.agent.core.model.LarkDepsStatus
import com.ethan.agent.core.model.RecordDetailResponse
import com.ethan.agent.core.model.RecordEvidenceResponse
import com.ethan.agent.core.model.RecordListResponse
import com.ethan.agent.core.model.RegenTitleResponse
import com.ethan.agent.core.model.ScheduleCreateRequest
import com.ethan.agent.core.model.ServerUrlUtils
import com.ethan.agent.core.model.SignRequest
import com.ethan.agent.core.model.SignResponse
import com.ethan.agent.core.model.StopBackgroundTaskResponse
import com.ethan.agent.core.model.StopChatResponse
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
import io.ktor.client.HttpClient
import io.ktor.client.request.delete
import io.ktor.client.request.forms.MultiPartFormDataContent
import io.ktor.client.request.forms.formData
import io.ktor.client.request.get
import io.ktor.client.request.parameter
import io.ktor.client.request.patch
import io.ktor.client.request.post
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.client.call.body
import io.ktor.http.Headers
import io.ktor.http.HttpHeaders

/**
 * Ktor 版 Ethan API 客户端（替换原 Retrofit interface）。
 *
 * - baseUrlProvider 每次取当前 server url（登录后/切服务器可变），内部换算成 `${origin}/api`。
 * - 所有 body 走 kotlinx.serialization（ContentNegotiation 已装 JSON）。
 * - 查询参数用 Ktor 的 parameter DSL：值为 null 时自动跳过，语义与 Retrofit 可空 @Query 一致。
 */
class EthanApiService(
    private val client: HttpClient,
    private val baseUrlProvider: () -> String,
) {
    private fun url(path: String): String {
        val apiBase = ServerUrlUtils.toApiBaseUrl(baseUrlProvider())
        return "${apiBase.trimEnd('/')}/$path"
    }

    // ── Auth / Health / Models ─────────────────────────────────────────────

    suspend fun auth(body: AuthRequest): AuthResponse =
        client.post(url("auth")) { jsonBody(body) }.body()

    suspend fun health(): HealthResponse = client.get(url("health")).body()

    suspend fun getModels(): ModelsResponse = client.get(url("models")).body()

    suspend fun addModel(model: ModelEntry): OkResponse =
        client.post(url("models")) { jsonBody(model) }.body()

    suspend fun deleteModel(provider: String, modelId: String): OkResponse =
        client.delete(url("models/$provider/$modelId")).body()

    suspend fun discoverModels(body: DiscoverModelsRequest): DiscoverModelsResponse =
        client.post(url("models/discover")) { jsonBody(body) }.body()

    suspend fun updateModel(provider: String, modelId: String, model: ModelEntry): OkResponse =
        client.put(url("models/$provider/$modelId")) { jsonBody(model) }.body()

    suspend fun getModes(): ModesResponse = client.get(url("modes")).body()

    // ── Sessions ────────────────────────────────────────────────────────────

    suspend fun getSessions(limit: Int = 50, offset: Int = 0, query: String? = null): SessionsResponse =
        client.get(url("sessions")) {
            parameter("limit", limit)
            parameter("offset", offset)
            parameter("q", query)
        }.body()

    suspend fun createSession(model: String? = null, mode: String? = null): CreateSessionResponse =
        client.post(url("sessions")) {
            parameter("model", model)
            parameter("mode", mode)
        }.body()

    suspend fun getSession(id: String): SessionDetail = client.get(url("sessions/$id")).body()

    suspend fun renameSession(id: String, body: RenameSessionRequest) {
        client.patch(url("sessions/$id")) { jsonBody(body) }
    }

    suspend fun deleteSession(id: String) {
        client.delete(url("sessions/$id"))
    }

    suspend fun compactSession(id: String): CompactResponse =
        client.post(url("sessions/$id/compact")).body()

    suspend fun regenTitle(id: String): RegenTitleResponse =
        client.post(url("sessions/$id/regen-title")).body()

    suspend fun summarySession(id: String): SummaryResponse =
        client.post(url("sessions/$id/summary")).body()

    suspend fun deleteMessage(id: String, msgId: Long): DeleteMessageResponse =
        client.delete(url("sessions/$id/messages/$msgId")).body()

    // ── Upload ────────────────────────────────────────────────────────────

    /**
     * 上传文件：平台无关，传字节 + 文件名 + MIME（原 Retrofit 用 okhttp MultipartBody.Part）。
     */
    suspend fun uploadFile(bytes: ByteArray, fileName: String, mimeType: String): UploadResponse =
        client.post(url("upload")) {
            setBody(
                MultiPartFormDataContent(
                    formData {
                        append(
                            "file",
                            bytes,
                            Headers.build {
                                append(HttpHeaders.ContentType, mimeType)
                                append(HttpHeaders.ContentDisposition, "filename=\"$fileName\"")
                            },
                        )
                    },
                ),
            )
        }.body()

    // ── Consent / Poll ──────────────────────────────────────────────────────

    suspend fun respondConsent(requestId: String, body: ConsentRequest): OkResponse =
        client.post(url("consent/$requestId")) { jsonBody(body) }.body()

    suspend fun poll(): PollData = client.get(url("poll")).body()

    // ── Pin / 交互回传（ask_user / wait_for_user） ─────────────────────────

    suspend fun pinSession(id: String): OkResponse =
        client.post(url("sessions/$id/pin")).body()

    suspend fun unpinSession(id: String): OkResponse =
        client.delete(url("sessions/$id/pin")).body()

    suspend fun getPinnedSessions(): PinnedSessionsResponse =
        client.get(url("sessions/pinned")).body()

    suspend fun respondAskUser(requestId: String, body: InteractionValueRequest): OkResponse =
        client.post(url("ask-user/$requestId")) { jsonBody(body) }.body()

    suspend fun respondWaitForUser(requestId: String, body: InteractionValueRequest): OkResponse =
        client.post(url("wait-for-user/$requestId")) { jsonBody(body) }.body()

    // ── Settings ──────────────────────────────────────────────────────────

    suspend fun getAgentSettings(): AgentSettings = client.get(url("settings/agent")).body()

    suspend fun updateAgentSettings(patch: AgentSettings) {
        client.patch(url("settings/agent")) { jsonBody(patch) }
    }

    suspend fun getProviderSettings(): Map<String, ProviderConfig> =
        client.get(url("settings/providers")).body()

    suspend fun updateProviderSettings(patch: Map<String, ProviderConfig>) {
        client.patch(url("settings/providers")) { jsonBody(patch) }
    }

    suspend fun getSystemSettings(): SystemSettings = client.get(url("settings/system")).body()

    suspend fun updateSystemSettings(patch: SystemSettings) {
        client.patch(url("settings/system")) { jsonBody(patch) }
    }

    suspend fun getUserProfile(): ProfileResponse = client.get(url("settings/profile")).body()

    suspend fun updateUserProfile(body: ProfileRequest) {
        client.patch(url("settings/profile")) { jsonBody(body) }
    }

    suspend fun getSystemPromptPreview(): SystemPromptPreview =
        client.get(url("system-prompt-preview")).body()

    // ── Memory: facts / episodes / procedures ───────────────────────────────

    suspend fun getFacts(): FactsResponse = client.get(url("memory/facts")).body()

    suspend fun updateFact(id: String, body: FactUpdateRequest) {
        client.patch(url("memory/facts/$id")) { jsonBody(body) }
    }

    suspend fun deleteFact(id: String) {
        client.delete(url("memory/facts/$id"))
    }

    suspend fun getEpisodes(): EpisodesResponse = client.get(url("memory/episodes")).body()

    suspend fun deleteEpisode(id: String) {
        client.delete(url("memory/episodes/$id"))
    }

    suspend fun getProcedures(): ProceduresResponse = client.get(url("memory/procedures")).body()

    suspend fun deleteProcedure(id: String) {
        client.delete(url("memory/procedures/$id"))
    }

    // ── Memory: insights ──────────────────────────────────────────────────

    suspend fun getInsights(limit: Int = 20, offset: Int = 0): InsightsListResponse =
        client.get(url("memory/insights")) {
            parameter("limit", limit)
            parameter("offset", offset)
        }.body()

    suspend fun getInsightsByDate(dateStr: String): InsightsByDateResponse =
        client.get(url("memory/insights/date/$dateStr")).body()

    suspend fun consolidateMemory(): ConsolidateResponse =
        client.post(url("memory/consolidate")).body()

    // ── Memory: structured records ──────────────────────────────────────────

    suspend fun getRecords(
        type: String? = null,
        status: String? = null,
        domain: String? = null,
        limit: Int = 50,
        offset: Int = 0,
    ): RecordListResponse = client.get(url("memory/records")) {
        parameter("type", type)
        parameter("status", status)
        parameter("domain", domain)
        parameter("limit", limit)
        parameter("offset", offset)
    }.body()

    suspend fun searchRecords(
        query: String,
        type: String? = null,
        domain: String? = null,
        status: String? = null,
        limit: Int = 20,
    ): RecordListResponse = client.get(url("memory/records/search")) {
        parameter("q", query)
        parameter("type", type)
        parameter("domain", domain)
        parameter("status", status)
        parameter("limit", limit)
    }.body()

    suspend fun getRecord(id: String): RecordDetailResponse =
        client.get(url("memory/records/$id")).body()

    suspend fun getRecordEvidence(id: String): RecordEvidenceResponse =
        client.get(url("memory/records/$id/evidence")).body()

    suspend fun updateRecord(id: String, body: UpdateRecordRequest): UpdateRecordResponse =
        client.patch(url("memory/records/$id")) { jsonBody(body) }.body()

    suspend fun deleteRecord(id: String): OkResponse =
        client.delete(url("memory/records/$id")).body()

    suspend fun confirmRecord(id: String): ConfirmRecordResponse =
        client.post(url("memory/records/$id/confirm")).body()

    suspend fun consolidateRecords(targetDate: String? = null): ConsolidateResponse =
        client.post(url("memory/records/consolidate")) {
            parameter("target_date", targetDate)
        }.body()

    suspend fun getDailySummaries(domain: String? = null, limit: Int = 30): DailySummariesResponse =
        client.get(url("memory/records/summaries")) {
            parameter("domain", domain)
            parameter("limit", limit)
        }.body()

    suspend fun getDailySummaryByDate(dateStr: String, domain: String? = null): DailySummariesResponse =
        client.get(url("memory/records/summaries/$dateStr")) {
            parameter("domain", domain)
        }.body()

    // ── Schedule ────────────────────────────────────────────────────────────

    suspend fun getSchedules(): ScheduleResponse = client.get(url("schedule")).body()

    suspend fun patchSchedule(jobId: String, body: SchedulePatchRequest) {
        client.patch(url("schedule/$jobId")) { jsonBody(body) }
    }

    suspend fun deleteSchedule(jobId: String) {
        client.delete(url("schedule/$jobId"))
    }

    suspend fun createSchedule(body: ScheduleCreateRequest): OkResponse =
        client.post(url("schedule")) { jsonBody(body) }.body()

    suspend fun triggerSchedule(jobId: String): OkResponse =
        client.post(url("schedule/$jobId/trigger")).body()

    // ── Schedule: timeline ──────────────────────────────────────────────────

    suspend fun getTimelineStatus(): TimelineStatusResponse =
        client.get(url("schedule/timeline-status")).body()

    suspend fun syncTimelines(): OkResponse = client.post(url("schedule/sync-timelines")).body()

    suspend fun timelineLifecycle(timelineId: String, action: String): TimelineActionResponse =
        client.post(url("schedule/timeline/$timelineId/$action")).body()

    suspend fun exportTimeline(body: TimelineExportRequest): TimelineExportResponse =
        client.post(url("schedule/timeline-export")) { jsonBody(body) }.body()

    suspend fun importTimeline(body: TimelineImportRequest): TimelineActionResponse =
        client.post(url("schedule/timeline-import")) { jsonBody(body) }.body()

    suspend fun validateTimeline(body: TimelineValidateRequest): TimelineActionResponse =
        client.post(url("schedule/timeline-validate")) { jsonBody(body) }.body()

    suspend fun syncTimelineToLark(timelineId: String): TimelineActionResponse =
        client.post(url("schedule/timeline/$timelineId/sync-lark")).body()

    suspend fun cleanupTimelineLark(timelineId: String): TimelineActionResponse =
        client.post(url("schedule/timeline/$timelineId/cleanup-lark")).body()

    // ── Agenda 日程 ─────────────────────────────────────────────────────────

    suspend fun getAgenda(): AgendaResponse = client.get(url("agenda")).body()

    suspend fun createAgenda(body: AgendaCreateRequest): AgendaEventResponse =
        client.post(url("agenda")) { jsonBody(body) }.body()

    suspend fun patchAgenda(eventId: String, body: AgendaPatchRequest): AgendaEventResponse =
        client.patch(url("agenda/$eventId")) { jsonBody(body) }.body()

    suspend fun deleteAgenda(eventId: String) {
        client.delete(url("agenda/$eventId"))
    }

    suspend fun setAgendaEnabled(body: AgendaEnabledRequest): AgendaEnabledResponse =
        client.put(url("agenda/enabled")) { jsonBody(body) }.body()

    // ── Knowledge ───────────────────────────────────────────────────────────

    suspend fun getKnowledge(query: String? = null, mode: String? = null): KnowledgeListResponse =
        client.get(url("knowledge")) {
            parameter("q", query)
            parameter("mode", mode)
        }.body()

    suspend fun searchKnowledge(query: String, limit: Int = 10, semantic: Boolean = true): KnowledgeSearchResponse =
        client.get(url("knowledge/search")) {
            parameter("q", query)
            parameter("limit", limit)
            parameter("semantic", semantic)
        }.body()

    suspend fun addKnowledge(body: KnowledgeCreateRequest) {
        client.post(url("knowledge")) { jsonBody(body) }
    }

    suspend fun updateKnowledge(source: String, body: KnowledgeUpdateRequest) {
        client.put(url("knowledge/$source")) { jsonBody(body) }
    }

    suspend fun deleteKnowledge(source: String) {
        client.delete(url("knowledge/$source"))
    }

    suspend fun validateKnowledgeBackend(body: KnowledgeValidateRequest): KnowledgeValidateResponse =
        client.post(url("settings/knowledge/validate")) { jsonBody(body) }.body()

    // ── Skills ──────────────────────────────────────────────────────────────

    suspend fun getSkills(): SkillsResponse = client.get(url("skills")).body()

    suspend fun getSkill(name: String): SkillInfo = client.get(url("skills/$name")).body()

    suspend fun saveSkill(skill: SkillInfo): SaveSkillResponse =
        client.post(url("skills")) { jsonBody(skill) }.body()

    suspend fun deleteSkill(name: String): OkResponse = client.delete(url("skills/$name")).body()

    // ── Onboarding ──────────────────────────────────────────────────────────

    suspend fun getOnboardingStatus(): OnboardingStatus = client.get(url("onboarding/status")).body()

    suspend fun completeOnboarding(body: OnboardingCompleteRequest): OnboardingCompleteResponse =
        client.post(url("onboarding/complete")) { jsonBody(body) }.body()

    // ── Channels ────────────────────────────────────────────────────────────

    suspend fun getChannels(): ChannelsResponse = client.get(url("channels")).body()

    suspend fun patchChannel(body: ChannelPatchRequest) {
        client.patch(url("channels")) { jsonBody(body) }
    }

    suspend fun getLarkDepsStatus(): LarkDepsStatus = client.get(url("channels/lark/deps-status")).body()

    suspend fun installLarkDeps(): OkResponse = client.post(url("channels/lark/install-deps")).body()

    // ── Docs ────────────────────────────────────────────────────────────────

    suspend fun getDocsList(): DocsListResponse = client.get(url("docs")).body()

    suspend fun getDoc(slug: String): DocContent = client.get(url("docs/$slug")).body()

    // ── API keys ────────────────────────────────────────────────────────────

    suspend fun getApiKeys(): ApiKeysResponse = client.get(url("api-keys")).body()

    suspend fun createApiKey(body: ApiKeyCreateRequest): ApiKeyCreated =
        client.post(url("api-keys")) { jsonBody(body) }.body()

    suspend fun deleteApiKey(id: String) {
        client.delete(url("api-keys/$id"))
    }

    // ── Logs ────────────────────────────────────────────────────────────────

    suspend fun getLogs(type: String = "backend", lines: Int = 500, query: String? = null): LogsResponse =
        client.get(url("logs")) {
            parameter("type", type)
            parameter("lines", lines)
            parameter("q", query)
        }.body()

    // ── Chat (非 SSE) ──────────────────────────────────────────────────────
    // 注意：GET /chat/{id}/stream 是 SSE，由 ChatSseClient 处理

    suspend fun stopChat(id: String): StopChatResponse = client.post(url("chat/$id/stop")).body()

    suspend fun injectMessage(id: String, body: InjectRequest): InjectResponse =
        client.post(url("chat/$id/inject")) { jsonBody(body) }.body()

    // ── Settings 扩展：tool tiers / fast rules ──────────────────────────────

    suspend fun getToolTiers(model: String? = null): ToolTiersResponse =
        client.get(url("tool-tiers")) {
            parameter("model", model)
        }.body()

    suspend fun getFastRules(): FastRulesResponse = client.get(url("fast-rules")).body()

    suspend fun getFastRuleOptions(model: String? = null): FastRuleOptionsResponse =
        client.get(url("fast-rules/options")) {
            parameter("model", model)
        }.body()

    suspend fun updateFastRules(body: FastRulesPatch): OkResponse =
        client.patch(url("fast-rules")) { jsonBody(body) }.body()

    // ── Background tasks ────────────────────────────────────────────────────

    suspend fun getBackgroundTasks(): BackgroundTasksResponse =
        client.get(url("background-tasks")).body()

    suspend fun stopBackgroundTask(taskId: String): StopBackgroundTaskResponse =
        client.post(url("background-tasks/$taskId/stop")).body()

    // ── Annotations ─────────────────────────────────────────────────────────

    suspend fun batchGetAnnotations(ids: String): BatchAnnotationsResponse =
        client.get(url("annotations/batch")) {
            parameter("ids", ids)
        }.body()

    suspend fun getAnnotations(messageId: Long): AnnotationsResponse =
        client.get(url("annotations/$messageId")).body()

    suspend fun createAnnotation(body: AnnotationCreateRequest): AnnotationCreateResponse =
        client.post(url("annotations")) { jsonBody(body) }.body()

    suspend fun deleteAnnotation(annoId: Long): DeleteAnnotationResponse =
        client.delete(url("annotations/$annoId")).body()

    // ── Files / 资产 ──────────────────────────────────────────────────────

    suspend fun signFiles(body: SignRequest): SignResponse =
        client.post(url("files/sign")) { jsonBody(body) }.body()

    suspend fun getDeck(path: String, sessionId: String = ""): DeckResponse =
        client.get(url("files/deck")) {
            parameter("path", path)
            parameter("session_id", sessionId)
        }.body()
}
