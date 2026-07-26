package com.ethan.agent.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class RegenTitleResponse(
    val ok: Boolean = false,
    val title: String = "",
    val error: String? = null,
)

@Serializable
data class SummaryResponse(
    val ok: Boolean = false,
    val summary: String = "",
)

@Serializable
data class DeleteMessageResponse(val ok: Boolean = false)
