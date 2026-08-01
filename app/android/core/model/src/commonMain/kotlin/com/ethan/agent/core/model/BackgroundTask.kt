package com.ethan.agent.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class BackgroundTask(
    val id: String = "",
    val title: String = "",
    val status: String = "",
)

@Serializable
data class BackgroundTasksResponse(val tasks: List<BackgroundTask> = emptyList())

@Serializable
data class StopBackgroundTaskResponse(
    val ok: Boolean = false,
    val message: String = "",
)
