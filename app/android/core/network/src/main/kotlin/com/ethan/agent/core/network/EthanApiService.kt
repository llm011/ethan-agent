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

    @GET("/api-keys")
    suspend fun getApiKeys(): ApiKeysResponse

    @POST("/api-keys")
    suspend fun createApiKey(@Body body: ApiKeyCreateRequest): ApiKeyCreated

    @DELETE("/api-keys/{id}")
    suspend fun deleteApiKey(@Path("id") id: String)

    @GET("logs")
    suspend fun getLogs(
        @Query("type") type: String = "backend",
        @Query("lines") lines: Int = 500,
        @Query("q") query: String? = null,
    ): LogsResponse
}
