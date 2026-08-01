package com.ethan.agent.core.model

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
