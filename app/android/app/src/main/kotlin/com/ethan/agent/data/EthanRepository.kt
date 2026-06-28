package com.ethan.agent.data

import com.ethan.agent.core.datastore.AppConfig
import com.ethan.agent.core.datastore.AppConfigStore
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
import com.ethan.agent.core.network.ApiException
import com.ethan.agent.core.network.ChatSseClient
import com.ethan.agent.core.network.EthanApiService
import com.ethan.agent.core.network.NetworkFactory
import kotlinx.serialization.SerializationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import retrofit2.HttpException
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class EthanRepository @Inject constructor(
    private val configStore: AppConfigStore,
    private var api: EthanApiService,
    private val sseClient: ChatSseClient,
    private val tokenProvider: () -> String,
) {
    val config: Flow<AppConfig> = configStore.config

    val isLoggedIn: Flow<Boolean> = config.map { it.authToken.isNotBlank() }

    private suspend fun refreshApi() {
        val cfg = configStore.config.first()
        api = NetworkFactory.createApiService(cfg.apiBaseUrl, tokenProvider)
    }

    suspend fun repairStoredUrlIfNeeded() {
        configStore.repairStoredUrlIfNeeded()
    }

    suspend fun saveServerUrl(url: String) {
        val normalized = com.ethan.agent.core.model.ServerUrlUtils.normalize(url)
            ?: throw IllegalArgumentException("无效的服务器地址，请填写如 https://chat.example.com:29999")
        configStore.saveServerUrl(normalized)
        refreshApi()
    }

    suspend fun login(token: String, serverUrl: String? = null): Result<AuthResponse> = runCatching {
        if (!serverUrl.isNullOrBlank()) {
            saveServerUrl(serverUrl)
        } else {
            refreshApi()
        }
        val response = api.auth(com.ethan.agent.core.model.AuthRequest(token))
        if (response.ok) {
            configStore.saveAuth(token, response.userId, response.userName, response.isAdmin)
        } else {
            error("Invalid token")
        }
        response
    }.recoverCatching { e ->
        if (e is HttpException && e.code() == 401) error("认证失败，请检查 Token")
        throw e
    }

    suspend fun logout() {
        configStore.clearAuth()
    }

    suspend fun checkHealth(): String? = runCatching {
        refreshApi()
        api.health().version
    }.getOrNull()

    suspend fun getModels(): List<ModelEntry> {
        refreshApi()
        return api.getModels().models
    }

    suspend fun getModes(): List<ModeEntry> {
        refreshApi()
        return api.getModes().modes
    }

    suspend fun getSessions(limit: Int = 50, offset: Int = 0, query: String? = null): List<SessionInfo> {
        refreshApi()
        return api.getSessions(limit, offset, query).sessions
    }

    suspend fun poll(): List<SessionInfo> {
        refreshApi()
        return api.poll().sessions
    }

    suspend fun createSession(model: String? = null, mode: String? = null): CreateSessionResponse {
        refreshApi()
        return api.createSession(model, mode)
    }

    suspend fun getSession(id: String): SessionDetail {
        refreshApi()
        return api.getSession(id)
    }

    suspend fun renameSession(id: String, title: String) {
        refreshApi()
        api.renameSession(id, RenameSessionRequest(title))
    }

    suspend fun deleteSession(id: String) {
        refreshApi()
        api.deleteSession(id)
    }

    suspend fun compactSession(id: String): CompactResponse {
        refreshApi()
        return api.compactSession(id)
    }

    fun streamChat(
        messages: List<ChatMessage>,
        model: String?,
        sessionId: String?,
        quote: Quote?,
        mode: String?,
    ): Flow<ChatStreamEvent> {
        val cfg = kotlinx.coroutines.runBlocking { configStore.config.first() }
        val request = ChatRequest(
            messages = messages,
            model = model,
            stream = true,
            sessionId = sessionId,
            quote = quote,
            mode = mode?.ifBlank { null },
        )
        return sseClient.streamChat(cfg.apiBaseUrl, cfg.authToken, request)
    }

    suspend fun respondConsent(requestId: String, allowed: Boolean) {
        refreshApi()
        api.respondConsent(requestId, com.ethan.agent.core.model.ConsentRequest(allowed))
    }

    suspend fun uploadFile(file: File, filename: String): String {
        refreshApi()
        val body = file.asRequestBody("application/octet-stream".toMediaType())
        val part = MultipartBody.Part.createFormData("file", filename, body)
        return api.uploadFile(part).path
    }

    suspend fun getAgentSettings(): AgentSettings {
        refreshApi()
        return api.getAgentSettings()
    }

    suspend fun updateAgentSettings(patch: AgentSettings) {
        refreshApi()
        api.updateAgentSettings(patch)
    }

    suspend fun getProviderSettings(): Map<String, ProviderConfig> {
        refreshApi()
        return api.getProviderSettings()
    }

    suspend fun updateProviderSettings(patch: Map<String, ProviderConfig>) {
        refreshApi()
        api.updateProviderSettings(patch)
    }

    suspend fun getSystemSettings(): SystemSettings {
        refreshApi()
        return api.getSystemSettings()
    }

    suspend fun updateSystemSettings(patch: SystemSettings) {
        refreshApi()
        api.updateSystemSettings(patch)
    }

    suspend fun getUserProfile(): String {
        refreshApi()
        return api.getUserProfile().content
    }

    suspend fun updateUserProfile(content: String) {
        refreshApi()
        api.updateUserProfile(com.ethan.agent.core.model.ProfileRequest(content))
    }

    suspend fun getSystemPromptPreview(): SystemPromptPreview {
        refreshApi()
        return api.getSystemPromptPreview()
    }

    suspend fun getFacts(): List<Fact> {
        refreshApi()
        return api.getFacts().facts
    }

    suspend fun updateFact(id: String, content: String) {
        refreshApi()
        api.updateFact(id, FactUpdateRequest(content))
    }

    suspend fun deleteFact(id: String) {
        refreshApi()
        api.deleteFact(id)
    }

    suspend fun getEpisodes(): List<Episode> {
        refreshApi()
        return api.getEpisodes().episodes
    }

    suspend fun deleteEpisode(id: String) {
        refreshApi()
        api.deleteEpisode(id)
    }

    suspend fun getProcedures(): List<Procedure> {
        refreshApi()
        return api.getProcedures().procedures
    }

    suspend fun deleteProcedure(id: String) {
        refreshApi()
        api.deleteProcedure(id)
    }

    suspend fun getSchedules(): List<ScheduleJob> {
        refreshApi()
        return api.getSchedules().jobs
    }

    suspend fun patchSchedule(jobId: String, state: String) {
        refreshApi()
        api.patchSchedule(jobId, SchedulePatchRequest(state))
    }

    suspend fun deleteSchedule(jobId: String) {
        refreshApi()
        api.deleteSchedule(jobId)
    }

    suspend fun getKnowledge(query: String? = null, mode: String? = null): List<KnowledgeItem> {
        refreshApi()
        return api.getKnowledge(query, mode).items
    }

    suspend fun searchKnowledge(query: String, semantic: Boolean = true): List<KnowledgeItem> {
        refreshApi()
        return api.searchKnowledge(query, semantic = semantic).results
    }

    suspend fun addKnowledge(title: String, content: String, tags: List<String>) {
        refreshApi()
        api.addKnowledge(KnowledgeCreateRequest(title, content, tags))
    }

    suspend fun updateKnowledge(source: String, title: String, content: String, tags: List<String>) {
        refreshApi()
        api.updateKnowledge(source, KnowledgeUpdateRequest(title, content, tags))
    }

    suspend fun deleteKnowledge(source: String) {
        refreshApi()
        api.deleteKnowledge(source)
    }

    suspend fun getSkills(): List<SkillInfo> {
        refreshApi()
        return api.getSkills().skills
    }

    suspend fun getSkill(name: String): SkillInfo {
        refreshApi()
        return api.getSkill(name)
    }

    suspend fun saveSkill(skill: SkillInfo) {
        refreshApi()
        api.saveSkill(skill)
    }

    suspend fun deleteSkill(name: String) {
        refreshApi()
        api.deleteSkill(name)
    }

    suspend fun getOnboardingStatus(): OnboardingStatus {
        refreshApi()
        return api.getOnboardingStatus()
    }

    suspend fun completeOnboarding(agentName: String, userInfo: String) {
        refreshApi()
        api.completeOnboarding(OnboardingCompleteRequest(agentName, userInfo))
    }

    suspend fun getChannels(): List<ChannelInfo> {
        refreshApi()
        return api.getChannels().channels
    }

    suspend fun patchChannel(channelId: String, config: Map<String, String>) {
        refreshApi()
        api.patchChannel(com.ethan.agent.core.model.ChannelPatchRequest(channelId, config))
    }

    suspend fun getDocsList(): List<DocMeta> {
        refreshApi()
        return api.getDocsList().docs
    }

    suspend fun getDoc(slug: String): DocContent {
        refreshApi()
        return api.getDoc(slug)
    }

    suspend fun getApiKeys(): List<ApiKeyInfo> {
        refreshApi()
        return api.getApiKeys().keys
    }

    suspend fun createApiKey(name: String): ApiKeyCreated {
        refreshApi()
        return api.createApiKey(com.ethan.agent.core.model.ApiKeyCreateRequest(name))
    }

    suspend fun deleteApiKey(id: String) {
        refreshApi()
        api.deleteApiKey(id)
    }

    suspend fun getLogs(type: String = "backend", lines: Int = 500, query: String? = null): String {
        refreshApi()
        return api.getLogs(type, lines, query).content
    }

    suspend fun setDarkTheme(dark: Boolean) {
        configStore.setDarkTheme(dark)
    }

    fun friendlyError(e: Throwable): String = when (e) {
        is ApiException -> e.message
        is HttpException -> when (e.code()) {
            401 -> "未授权，请重新登录"
            404 -> "资源不存在"
            else -> "请求失败 (${e.code()})"
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

data class UiMessage(
    val role: String,
    val content: String,
    val toolSteps: List<com.ethan.agent.core.model.ToolStep> = emptyList(),
    val usage: com.ethan.agent.core.model.Usage? = null,
    val quote: Quote? = null,
    val isStreaming: Boolean = false,
)
