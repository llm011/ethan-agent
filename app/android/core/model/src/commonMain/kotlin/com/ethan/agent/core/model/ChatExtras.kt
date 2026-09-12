package com.ethan.agent.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class StopChatResponse(
    val ok: Boolean = false,
    val stopped: Boolean = false,
)

@Serializable
data class InjectRequest(val content: String)

@Serializable
data class InjectResponse(
    val ok: Boolean = false,
    val queued: Boolean = false,
)

/** 运行中切换超级权限的请求体（POST /api/chat/auto-consent）。 */
@Serializable
data class AutoConsentRequest(
    @SerialName("session_id") val sessionId: String,
    val enabled: Boolean,
)

/**
 * 运行中切换超级权限的响应。
 *
 * `applied=false` 表示当前 session 没有活跃 run（开关已记在本地，下一次发消息
 * 的请求体里带上 auto_consent 即可生效），不是错误。
 */
@Serializable
data class AutoConsentResponse(
    val ok: Boolean = false,
    val enabled: Boolean = false,
    val applied: Boolean = false,
    val reason: String? = null,
)
