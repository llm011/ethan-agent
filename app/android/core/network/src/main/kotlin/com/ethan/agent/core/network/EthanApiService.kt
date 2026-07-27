package com.ethan.agent.core.network

import com.ethan.agent.core.model.AgentSettings
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
import com.ethan.agent.core.model.KnowledgeValidateRequest
import com.ethan.agent.core.model.KnowledgeValidateResponse
import com.ethan.agent.core.model.LarkDepsStatus
import com.ethan.agent.core.model.RecordDetailResponse
import com.ethan.agent.core.model.RecordEvidenceResponse
import com.ethan.agent.core.model.RecordListResponse
import com.ethan.agent.core.model.RegenTitleResponse
import com.ethan.agent.core.model.ScheduleCreateRequest
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
import okhttp3.MultipartBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.QueryMap

interface EthanApiService {
    @POST("auth")
    suspend fun auth(@Body body: AuthRequest): AuthResponse

    @GET("health")
    suspend fun health(): HealthResponse

    @GET("models")
    suspend fun getModels(): ModelsResponse

    @POST("models")
    suspend fun addModel(@Body model: ModelEntry): OkResponse

    @DELETE("models/{provider}/{modelId}")
    suspend fun deleteModel(
        @Path("provider") provider: String,
        @Path("modelId") modelId: String,
    ): OkResponse

    @POST("models/discover")
    suspend fun discoverModels(@Body body: DiscoverModelsRequest): DiscoverModelsResponse

    @GET("modes")
    suspend fun getModes(): ModesResponse

    @GET("sessions")
    suspend fun getSessions(
        @Query("limit") limit: Int = 50,
        @Query("offset") offset: Int = 0,
        @Query("q") query: String? = null,
    ): SessionsResponse

    @POST("sessions")
    suspend fun createSession(
        @Query("model") model: String? = null,
        @Query("mode") mode: String? = null,
    ): CreateSessionResponse

    @GET("sessions/{id}")
    suspend fun getSession(@Path("id") id: String): SessionDetail

    @PATCH("sessions/{id}")
    suspend fun renameSession(@Path("id") id: String, @Body body: RenameSessionRequest)

    @DELETE("sessions/{id}")
    suspend fun deleteSession(@Path("id") id: String)

    @POST("sessions/{id}/compact")
    suspend fun compactSession(@Path("id") id: String): CompactResponse

    @Multipart
    @POST("upload")
    suspend fun uploadFile(@Part file: MultipartBody.Part): UploadResponse

    @POST("consent/{requestId}")
    suspend fun respondConsent(
        @Path("requestId") requestId: String,
        @Body body: ConsentRequest,
    ): OkResponse

    @GET("poll")
    suspend fun poll(): PollData

    @GET("settings/agent")
    suspend fun getAgentSettings(): AgentSettings

    @PATCH("settings/agent")
    suspend fun updateAgentSettings(@Body patch: AgentSettings)

    @GET("settings/providers")
    suspend fun getProviderSettings(): Map<String, ProviderConfig>

    @PATCH("settings/providers")
    suspend fun updateProviderSettings(@Body patch: Map<String, ProviderConfig>)

    @GET("settings/system")
    suspend fun getSystemSettings(): SystemSettings

    @PATCH("settings/system")
    suspend fun updateSystemSettings(@Body patch: SystemSettings)

    @GET("settings/profile")
    suspend fun getUserProfile(): ProfileResponse

    @PATCH("settings/profile")
    suspend fun updateUserProfile(@Body body: ProfileRequest)

    @GET("system-prompt-preview")
    suspend fun getSystemPromptPreview(): SystemPromptPreview

    @GET("memory/facts")
    suspend fun getFacts(): FactsResponse

    @PATCH("memory/facts/{id}")
    suspend fun updateFact(@Path("id") id: String, @Body body: FactUpdateRequest)

    @DELETE("memory/facts/{id}")
    suspend fun deleteFact(@Path("id") id: String)

    @GET("memory/episodes")
    suspend fun getEpisodes(): EpisodesResponse

    @DELETE("memory/episodes/{id}")
    suspend fun deleteEpisode(@Path("id") id: String)

    @GET("memory/procedures")
    suspend fun getProcedures(): ProceduresResponse

    @DELETE("memory/procedures/{id}")
    suspend fun deleteProcedure(@Path("id") id: String)

    @GET("schedule")
    suspend fun getSchedules(): ScheduleResponse

    @PATCH("schedule/{jobId}")
    suspend fun patchSchedule(@Path("jobId") jobId: String, @Body body: SchedulePatchRequest)

    @DELETE("schedule/{jobId}")
    suspend fun deleteSchedule(@Path("jobId") jobId: String)

    @GET("knowledge")
    suspend fun getKnowledge(
        @Query("q") query: String? = null,
        @Query("mode") mode: String? = null,
    ): KnowledgeListResponse

    @GET("knowledge/search")
    suspend fun searchKnowledge(
        @Query("q") query: String,
        @Query("limit") limit: Int = 10,
        @Query("semantic") semantic: Boolean = true,
    ): KnowledgeSearchResponse

    @POST("knowledge")
    suspend fun addKnowledge(@Body body: KnowledgeCreateRequest)

    @PUT("knowledge/{source}")
    suspend fun updateKnowledge(
        @Path("source") source: String,
        @Body body: KnowledgeUpdateRequest,
    )

    @DELETE("knowledge/{source}")
    suspend fun deleteKnowledge(@Path("source") source: String)

    @GET("skills")
    suspend fun getSkills(): SkillsResponse

    @GET("skills/{name}")
    suspend fun getSkill(@Path("name") name: String): SkillInfo

    @POST("skills")
    suspend fun saveSkill(@Body skill: SkillInfo): SaveSkillResponse

    @DELETE("skills/{name}")
    suspend fun deleteSkill(@Path("name") name: String): OkResponse

    @GET("onboarding/status")
    suspend fun getOnboardingStatus(): OnboardingStatus

    @POST("onboarding/complete")
    suspend fun completeOnboarding(@Body body: OnboardingCompleteRequest): OnboardingCompleteResponse

    @GET("channels")
    suspend fun getChannels(): ChannelsResponse

    @PATCH("channels")
    suspend fun patchChannel(@Body body: ChannelPatchRequest)

    @GET("docs")
    suspend fun getDocsList(): DocsListResponse

    @GET("docs/{slug}")
    suspend fun getDoc(@Path("slug") slug: String): DocContent

    @GET("api-keys")
    suspend fun getApiKeys(): ApiKeysResponse

    @POST("api-keys")
    suspend fun createApiKey(@Body body: ApiKeyCreateRequest): ApiKeyCreated

    @DELETE("api-keys/{id}")
    suspend fun deleteApiKey(@Path("id") id: String)

    @GET("logs")
    suspend fun getLogs(
        @Query("type") type: String = "backend",
        @Query("lines") lines: Int = 500,
        @Query("q") query: String? = null,
    ): LogsResponse

    // ── Sessions 扩展 ──────────────────────────────────────────────────────

    @POST("sessions/{id}/regen-title")
    suspend fun regenTitle(@Path("id") id: String): RegenTitleResponse

    @POST("sessions/{id}/summary")
    suspend fun summarySession(@Path("id") id: String): SummaryResponse

    @DELETE("sessions/{id}/messages/{msgId}")
    suspend fun deleteMessage(
        @Path("id") id: String,
        @Path("msgId") msgId: Long,
    ): DeleteMessageResponse

    // ── Chat 扩展（非 SSE） ────────────────────────────────────────────────
    // 注意：GET /chat/{id}/stream 是 SSE，不走 Retrofit，由 ChatSseClient.resumeStream 处理

    @POST("chat/{id}/stop")
    suspend fun stopChat(@Path("id") id: String): StopChatResponse

    @POST("chat/{id}/inject")
    suspend fun injectMessage(
        @Path("id") id: String,
        @Body body: InjectRequest,
    ): InjectResponse

    // ── Models 扩展 ────────────────────────────────────────────────────────

    @PUT("models/{provider}/{modelId}")
    suspend fun updateModel(
        @Path("provider") provider: String,
        @Path("modelId") modelId: String,
        @Body model: ModelEntry,
    ): OkResponse

    // ── Memory: Insights 永久记忆 ─────────────────────────────────────────

    @GET("memory/insights")
    suspend fun getInsights(
        @Query("limit") limit: Int = 20,
        @Query("offset") offset: Int = 0,
    ): InsightsListResponse

    @GET("memory/insights/date/{dateStr}")
    suspend fun getInsightsByDate(@Path("dateStr") dateStr: String): InsightsByDateResponse

    @POST("memory/consolidate")
    suspend fun consolidateMemory(): ConsolidateResponse

    // ── Memory: Structured records 结构化记忆 ─────────────────────────────

    @GET("memory/records")
    suspend fun getRecords(
        @Query("type") type: String? = null,
        @Query("status") status: String? = null,
        @Query("domain") domain: String? = null,
        @Query("limit") limit: Int = 50,
        @Query("offset") offset: Int = 0,
    ): RecordListResponse

    @GET("memory/records/search")
    suspend fun searchRecords(
        @Query("q") query: String,
        @Query("type") type: String? = null,
        @Query("domain") domain: String? = null,
        @Query("status") status: String? = null,
        @Query("limit") limit: Int = 20,
    ): RecordListResponse

    @GET("memory/records/{id}")
    suspend fun getRecord(@Path("id") id: String): RecordDetailResponse

    @GET("memory/records/{id}/evidence")
    suspend fun getRecordEvidence(@Path("id") id: String): RecordEvidenceResponse

    @PATCH("memory/records/{id}")
    suspend fun updateRecord(
        @Path("id") id: String,
        @Body body: UpdateRecordRequest,
    ): UpdateRecordResponse

    @DELETE("memory/records/{id}")
    suspend fun deleteRecord(@Path("id") id: String): OkResponse

    @POST("memory/records/{id}/confirm")
    suspend fun confirmRecord(@Path("id") id: String): ConfirmRecordResponse

    @POST("memory/records/consolidate")
    suspend fun consolidateRecords(
        @Query("target_date") targetDate: String? = null,
    ): ConsolidateResponse

    @GET("memory/records/summaries")
    suspend fun getDailySummaries(
        @Query("domain") domain: String? = null,
        @Query("limit") limit: Int = 30,
    ): DailySummariesResponse

    @GET("memory/records/summaries/{dateStr}")
    suspend fun getDailySummaryByDate(
        @Path("dateStr") dateStr: String,
        @Query("domain") domain: String? = null,
    ): DailySummariesResponse

    // ── Schedule 扩展 ─────────────────────────────────────────────────────

    @POST("schedule")
    suspend fun createSchedule(@Body body: ScheduleCreateRequest): OkResponse

    @POST("schedule/{jobId}/trigger")
    suspend fun triggerSchedule(@Path("jobId") jobId: String): OkResponse

    // ── Schedule: Timeline 时间线 ─────────────────────────────────────────

    @GET("schedule/timeline-status")
    suspend fun getTimelineStatus(): TimelineStatusResponse

    @POST("schedule/sync-timelines")
    suspend fun syncTimelines(): OkResponse

    @POST("schedule/timeline/{timelineId}/{action}")
    suspend fun timelineLifecycle(
        @Path("timelineId") timelineId: String,
        @Path("action") action: String,
    ): TimelineActionResponse

    @POST("schedule/timeline-export")
    suspend fun exportTimeline(@Body body: TimelineExportRequest): TimelineExportResponse

    @POST("schedule/timeline-import")
    suspend fun importTimeline(@Body body: TimelineImportRequest): TimelineActionResponse

    @POST("schedule/timeline-validate")
    suspend fun validateTimeline(@Body body: TimelineValidateRequest): TimelineActionResponse

    @POST("schedule/timeline/{timelineId}/sync-lark")
    suspend fun syncTimelineToLark(@Path("timelineId") timelineId: String): TimelineActionResponse

    @POST("schedule/timeline/{timelineId}/cleanup-lark")
    suspend fun cleanupTimelineLark(@Path("timelineId") timelineId: String): TimelineActionResponse

    // ── Settings 扩展 ─────────────────────────────────────────────────────

    @GET("tool-tiers")
    suspend fun getToolTiers(@Query("model") model: String? = null): ToolTiersResponse

    @GET("fast-rules")
    suspend fun getFastRules(): FastRulesResponse

    @GET("fast-rules/options")
    suspend fun getFastRuleOptions(@Query("model") model: String? = null): FastRuleOptionsResponse

    @PATCH("fast-rules")
    suspend fun updateFastRules(@Body body: FastRulesPatch): OkResponse

    @POST("settings/knowledge/validate")
    suspend fun validateKnowledgeBackend(@Body body: KnowledgeValidateRequest): KnowledgeValidateResponse

    @GET("channels/lark/deps-status")
    suspend fun getLarkDepsStatus(): LarkDepsStatus

    @POST("channels/lark/install-deps")
    suspend fun installLarkDeps(): OkResponse

    // ── Background Tasks ──────────────────────────────────────────────────

    @GET("background-tasks")
    suspend fun getBackgroundTasks(): BackgroundTasksResponse

    @POST("background-tasks/{taskId}/stop")
    suspend fun stopBackgroundTask(@Path("taskId") taskId: String): StopBackgroundTaskResponse

    // ── Annotations 标注 ──────────────────────────────────────────────────
    // 注意：batch 端点必须声明在 {message_id} 之前，避免被路径参数路由截胡（与后端一致）

    @GET("annotations/batch")
    suspend fun batchGetAnnotations(@Query("ids") ids: String): BatchAnnotationsResponse

    @GET("annotations/{messageId}")
    suspend fun getAnnotations(@Path("messageId") messageId: Long): AnnotationsResponse

    @POST("annotations")
    suspend fun createAnnotation(@Body body: AnnotationCreateRequest): AnnotationCreateResponse

    @DELETE("annotations/{annoId}")
    suspend fun deleteAnnotation(@Path("annoId") annoId: Long): DeleteAnnotationResponse

    // ── Files / 资产 ──────────────────────────────────────────────────────
    // download/asset 走 cookie/签名 URL 双通道；Android 端走签名 URL（先 POST /files/sign 换发）

    @POST("files/sign")
    suspend fun signFiles(@Body body: SignRequest): SignResponse

    @GET("files/deck")
    suspend fun getDeck(
        @Query("path") path: String,
        @Query("session_id") sessionId: String = "",
    ): DeckResponse

}
