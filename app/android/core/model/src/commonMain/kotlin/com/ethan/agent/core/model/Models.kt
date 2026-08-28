package com.ethan.agent.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class AuthRequest(val token: String)

@Serializable
data class AuthResponse(
    val ok: Boolean = false,
    @SerialName("user_id") val userId: String? = null,
    @SerialName("user_name") val userName: String? = null,
    @SerialName("is_admin") val isAdmin: Boolean = false,
)

@Serializable
data class HealthResponse(val version: String? = null)

@Serializable
data class ModelEntry(
    val id: String,
    val provider: String,
    val description: String = "",
    val alias: List<String> = emptyList(),
)

@Serializable
data class ModelsResponse(val models: List<ModelEntry> = emptyList())

@Serializable
data class ModeEntry(
    val key: String,
    val label: String,
    val icon: String = "",
    val accent: String = "",
    val blurb: String = "",
)

@Serializable
data class ModesResponse(val modes: List<ModeEntry> = emptyList())

@Serializable
data class SessionInfo(
    val id: String,
    val title: String,
    val model: String,
    @SerialName("created_at") @Serializable(with = EpochSecondsSerializer::class) val createdAt: Long = 0,
    @SerialName("updated_at") @Serializable(with = EpochSecondsSerializer::class) val updatedAt: Long = 0,
    val snippet: String? = null,
    val source: String? = null,
    val mode: String? = null,
    /** 置顶时间戳（epoch 秒）；0/null 表示未置顶 */
    @SerialName("pinned_at") @Serializable(with = EpochSecondsSerializer::class) val pinnedAt: Long = 0,
)

@Serializable
data class SessionsResponse(val sessions: List<SessionInfo> = emptyList())

@Serializable
data class PinnedSessionsResponse(val sessions: List<SessionInfo> = emptyList())

@Serializable
data class CreateSessionResponse(
    val id: String,
    val title: String,
    val model: String,
    val mode: String? = null,
)

@Serializable
data class Quote(
    val role: String,
    val content: String,
)

@Serializable
data class Usage(
    val input: Int = 0,
    val output: Int = 0,
    val cache: Int = 0,
)

@Serializable
data class SubToolStep(
    val tool: String,
    val args: String = "",
    val state: String = "",
    @SerialName("duration_ms") val durationMs: Long? = null,
    @SerialName("result_preview") val resultPreview: String? = null,
)

@Serializable
data class ToolStep(
    val tool: String,
    val args: String = "",
    val state: String = "",
    @SerialName("duration_ms") val durationMs: Long? = null,
    @SerialName("result_preview") val resultPreview: String? = null,
    @SerialName("result_detail") val resultDetail: String? = null,
    val thought: String? = null,
    val intent: String? = null,
    val id: String? = null,
    @SerialName("sub_steps") val subSteps: List<SubToolStep>? = null,
)

@Serializable
data class FileCard(
    val type: String = "file",
    val filename: String = "",
    val title: String? = null,
    val path: String = "",
    @SerialName("size_kb") val sizeKb: Float? = null,
    val kind: String = "",
    @SerialName("project_dir") val projectDir: String? = null,
    @SerialName("page_count") val pageCount: Int? = null,
)

@Serializable
data class Message(
    val role: String,
    val content: String,
    @SerialName("created_at") @Serializable(with = NullableEpochSecondsSerializer::class) val createdAt: Long? = null,
    val quote: Quote? = null,
    val usage: Usage? = null,
    @SerialName("tool_steps") val toolSteps: List<ToolStep>? = null,
    val images: List<MessageImage>? = null,
    val cards: List<FileCard>? = null,
)

@Serializable
data class SessionDetail(
    val id: String,
    val title: String,
    val model: String,
    val source: String? = null,
    val mode: String? = null,
    val messages: List<Message> = emptyList(),
)

@Serializable
data class RenameSessionRequest(val title: String)

@Serializable
data class MessageImage(
    val data: String? = null,        // base64 raw（无 data: 前缀），发送给后端时用
    @SerialName("media_type") val mediaType: String? = null,
    val url: String? = null,         // 后端历史消息返回的相对路径，如 "assets/images/session_id/xxx.png"
)

@Serializable
data class ChatMessage(
    val role: String,
    val content: String,
    @SerialName("created_at") @Serializable(with = NullableEpochSecondsSerializer::class) val createdAt: Long? = null,
    val images: List<MessageImage>? = null,
)

@Serializable
data class ChatRequest(
    val messages: List<ChatMessage>,
    val model: String? = null,
    val stream: Boolean = true,
    @SerialName("session_id") val sessionId: String? = null,
    val quote: Quote? = null,
    val mode: String? = null,
    @SerialName("auto_consent") val autoConsent: Boolean = false,
)

@Serializable
data class ConsentRequest(val allowed: Boolean)

@Serializable
data class CompactResponse(val ok: Boolean = false, val summary: String = "")

@Serializable
data class UploadResponse(val path: String, val filename: String)

@Serializable
data class AgentSettings(
    val workspace: String = "",
    @SerialName("agent_name") val agentName: String = "",
    val language: String = "zh",
    @SerialName("default_model") val defaultModel: String = "",
    @SerialName("lite_model") val liteModel: String = "",
    @SerialName("heartbeat_enabled") val heartbeatEnabled: Boolean = false,
    @SerialName("heartbeat_interval_minutes") val heartbeatIntervalMinutes: Int = 30,
    val proxy: String = "",
    @SerialName("max_tokens") val maxTokens: Int = 8192,
    @SerialName("max_tool_iterations") val maxToolIterations: Int = 20,
    @SerialName("fast_keywords") val fastKeywords: List<String> = emptyList(),
    @SerialName("fast_max_length") val fastMaxLength: Int = 0,
    @SerialName("fast_skill_triggers") val fastSkillTriggers: List<String> = emptyList(),
)

@Serializable
data class ProviderConfig(
    @SerialName("api_key") val apiKey: String = "",
    @SerialName("base_url") val baseUrl: String? = null,
)

@Serializable
data class SystemSettings(
    val identity: String = "",
    val soul: String = "",
    val agent: String = "",
    val tools: String = "",
    val heartbeat: String = "",
)

@Serializable
data class ProfileResponse(val content: String = "")

@Serializable
data class ProfileRequest(val content: String)

@Serializable
data class Fact(
    val content: String,
    val confidence: Double = 0.0,
    val category: String = "",
    val source: String = "",
    @SerialName("created_at") @Serializable(with = EpochSecondsSerializer::class) val createdAt: Long = 0,
    @SerialName("last_accessed") @Serializable(with = EpochSecondsSerializer::class) val lastAccessed: Long = 0,
    val superseded: Boolean = false,
)

@Serializable
data class FactsResponse(val facts: List<Fact> = emptyList())

@Serializable
data class FactUpdateRequest(val content: String)

@Deprecated("episodes endpoint is retired on the backend; kept for UI compatibility")
@Serializable
data class Episode(
    @SerialName("session_id") val sessionId: String,
    val summary: String = "",
    @Serializable(with = EpochSecondsSerializer::class) val timestamp: Long = 0,
    @SerialName("turn_count") val turnCount: Int = 0,
    val keywords: List<String> = emptyList(),
    val model: String = "",
)

@Deprecated("episodes endpoint is retired on the backend; kept for UI compatibility")
@Serializable
data class EpisodesResponse(val episodes: List<Episode> = emptyList())

@Serializable
data class Procedure(
    val id: String,
    val rule: String,
    val context: String = "",
    @SerialName("hit_count") val hitCount: Int = 0,
    @SerialName("created_at") @Serializable(with = EpochSecondsSerializer::class) val createdAt: Long = 0,
)

@Serializable
data class ProceduresResponse(val procedures: List<Procedure> = emptyList())

@Serializable
data class ScheduleJob(
    val id: String,
    @SerialName("title") val name: String,
    @SerialName("next_run_time") val nextRunTime: String? = null,
    val trigger: String = "",
    val status: String = "active",
    val prompt: String = "",
    @SerialName("session_id") val sessionId: String = "",
    val category: String = "",
    val scene: String = "",
)

@Serializable
data class ScheduleResponse(val jobs: List<ScheduleJob> = emptyList())

@Serializable
data class SchedulePatchRequest(
    val state: String? = null,
    val title: String? = null,
    val prompt: String? = null,
)

@Serializable
data class KnowledgeItem(
    val source: String,
    val title: String,
    val content: String? = null,
    val tags: List<String>? = null,
    val score: Double? = null,
)

@Serializable
data class KnowledgeListResponse(val items: List<KnowledgeItem> = emptyList())

@Serializable
data class KnowledgeSearchResponse(val results: List<KnowledgeItem> = emptyList())

@Serializable
data class KnowledgeCreateRequest(
    val title: String,
    val content: String,
    val tags: List<String> = emptyList(),
    @SerialName("created_at") @Serializable(with = NullableEpochSecondsSerializer::class) val createdAt: Long? = null,
)

@Serializable
data class KnowledgeUpdateRequest(
    val title: String,
    val content: String,
    val tags: List<String> = emptyList(),
)

@Serializable
data class SkillInfo(
    val name: String,
    val description: String = "",
    val trigger: List<String> = emptyList(),
    val content: String = "",
)

@Serializable
data class SkillsResponse(val skills: List<SkillInfo> = emptyList())

@Serializable
data class SaveSkillResponse(val name: String)

@Serializable
data class PollData(
    val sessions: List<SessionInfo> = emptyList(),
)

@Serializable
data class OnboardingStatus(
    @SerialName("first_time") val firstTime: Boolean = false,
    val message: String = "",
)

@Serializable
data class OnboardingCompleteRequest(
    @SerialName("agent_name") val agentName: String,
    @SerialName("user_info") val userInfo: String,
)

@Serializable
data class OnboardingCompleteResponse(
    val ok: Boolean = false,
    @SerialName("agent_name") val agentName: String = "",
)

@Serializable
data class ChannelInfo(
    val id: String,
    val name: String,
    val enabled: Boolean = false,
    val config: Map<String, String> = emptyMap(),
)

@Serializable
data class ChannelsResponse(val channels: List<ChannelInfo> = emptyList())

@Serializable
data class ChannelPatchRequest(
    @SerialName("channel_id") val channelId: String,
    val config: Map<String, String>,
)

@Serializable
data class DocMeta(
    val slug: String,
    val title: String,
    val filename: String = "",
)

@Serializable
data class DocsListResponse(val docs: List<DocMeta> = emptyList())

@Serializable
data class DocContent(val slug: String, val content: String)

@Serializable
data class ApiKeyInfo(
    val id: String,
    val name: String,
    @SerialName("key_preview") val keyPreview: String = "",
    @SerialName("created_at") @Serializable(with = EpochSecondsSerializer::class) val createdAt: Long = 0,
    @SerialName("last_used_at") @Serializable(with = NullableEpochSecondsSerializer::class) val lastUsedAt: Long? = null,
)

@Serializable
data class ApiKeyCreated(
    val id: String,
    val name: String,
    @SerialName("key_preview") val keyPreview: String = "",
    @SerialName("created_at") @Serializable(with = EpochSecondsSerializer::class) val createdAt: Long = 0,
    @SerialName("last_used_at") @Serializable(with = NullableEpochSecondsSerializer::class) val lastUsedAt: Long? = null,
    val key: String = "",
)

@Serializable
data class ApiKeysResponse(val keys: List<ApiKeyInfo> = emptyList())

@Serializable
data class ApiKeyCreateRequest(val name: String)

@Serializable
data class LogsResponse(val content: String = "")

@Serializable
data class ToolSchema(
    val name: String,
    val description: String = "",
    val parameters: Map<String, JsonElement> = emptyMap(),
    @SerialName("fast_path") val fastPath: Boolean = false,
)

@Serializable
data class SystemPromptPreview(
    @SerialName("system_prompt") val systemPrompt: String = "",
    val tools: List<ToolSchema> = emptyList(),
    @SerialName("approx_tokens") val approxTokens: Int = 0,
    @SerialName("approx_tools_tokens") val approxToolsTokens: Int = 0,
    @SerialName("tool_count") val toolCount: Int = 0,
    @SerialName("approx_total_tokens") val approxTotalTokens: Int = 0,
    val chars: Int = 0,
)

@Serializable
data class DiscoverModelsRequest(val provider: String)

@Serializable
data class DiscoverModelsResponse(
    val ok: Boolean = false,
    val models: List<ModelEntry> = emptyList(),
    val error: String? = null,
    val url: String? = null,
)

@Serializable
data class OkResponse(val ok: Boolean = false, val error: String? = null)

/** SSE stream event from POST /api/chat */
@Serializable
data class ChatStreamEvent(
    val content: String? = null,
    val done: Boolean? = null,
    val error: String? = null,
    val model: String? = null,
    val usage: Usage? = null,
    val tool: String? = null,
    val args: String? = null,
    val state: String? = null,
    val id: String? = null,
    @SerialName("duration_ms") val durationMs: Long? = null,
    @SerialName("result_preview") val resultPreview: String? = null,
    @SerialName("result_detail") val resultDetail: String? = null,
    @SerialName("sub_steps") val subSteps: List<SubToolStep>? = null,
    val thought: String? = null,
    val intent: String? = null,
    @SerialName("consent_request") val consentRequest: Boolean? = null,
    @SerialName("ask_user_request") val askUserRequest: Boolean? = null,
    @SerialName("wait_for_user_request") val waitForUserRequest: Boolean? = null,
    @SerialName("request_id") val requestId: String? = null,
    val description: String? = null,
    val detail: String? = null,
    // ask_user 事件负载
    val question: String? = null,
    val options: List<AskUserOption>? = null,
    val default: String? = null,
    val timeout: Int? = null,
    // wait_for_user 事件负载
    val prompt: String? = null,
    @SerialName("input_type") val inputType: String? = null,
    val placeholder: String? = null,
    @SerialName("confirm_label") val confirmLabel: String? = null,
    @SerialName("cancel_label") val cancelLabel: String? = null,
    // file cards 事件负载
    val cards: List<FileCard>? = null,
    // 服务端检测到 auto_consent 来自公网、被安全约束降级为逐项弹窗时下发
    @SerialName("auto_consent_degraded") val autoConsentDegraded: Boolean? = null,
)

@Serializable
data class ConsentInfo(
    val requestId: String,
    val tool: String,
    val description: String,
    val detail: String? = null,
)

@Serializable
data class AskUserOption(
    val label: String = "",
    val value: String = "",
)

/** ask_user 弹卡片：问题 + 选项 + 倒计时（超时走 default） */
@Serializable
data class AskUserInfo(
    val requestId: String,
    val question: String,
    val options: List<AskUserOption> = emptyList(),
    val default: String = "",
    val timeout: Int = 20,
)

/** wait_for_user 弹卡片：等待用户确认/输入（confirm / text 两种形态） */
@Serializable
data class WaitForUserInfo(
    val requestId: String,
    val prompt: String,
    val inputType: String = "confirm", // confirm | text
    val placeholder: String = "",
    val confirmLabel: String = "已完成",
    val cancelLabel: String = "取消",
    val timeout: Int = 300,
)

/** ask-user / wait-for-user 回传请求体：{"value": "..."} */
@Serializable
data class InteractionValueRequest(val value: String)
