package com.ethan.agent.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class ScheduleCreateRequest(
    @SerialName("job_id") val jobId: String,
    val title: String = "",
    val prompt: String,
    val cron: String = "",
    @SerialName("interval_minutes") val intervalMinutes: Int = 0,
    @SerialName("end_date") val endDate: String = "",
    @SerialName("session_id") val sessionId: String,
    val channel: String = "web",
    @SerialName("channel_context") val channelContext: String = "{}",
    @SerialName("user_id") val userId: String = "",
    val category: String = "",
    val scene: String = "work",
)

// ── Timeline 时间线 ───────────────────────────────────────────────────────────

@Serializable
data class TimelineStatusResponse(val timelines: List<JsonElement> = emptyList())

@Serializable
data class TimelineActionResponse(
    val ok: Boolean = false,
    val message: String = "",
    val error: String? = null,
)

@Serializable
data class TimelineExportRequest(
    val format: String = "yaml",
    val scene: String = "work",
)

@Serializable
data class TimelineExportResponse(
    val ok: Boolean = false,
    val path: String = "",
    val scene: String = "",
)

@Serializable
data class TimelineImportRequest(
    val path: String,
    @SerialName("restore_state") val restoreState: Boolean = false,
    @SerialName("dry_run") val dryRun: Boolean = false,
    val mode: String = "overwrite",
    @SerialName("sync_after") val syncAfter: Boolean = false,
    val scene: String? = null,
)

@Serializable
data class TimelineValidateRequest(val path: String)
