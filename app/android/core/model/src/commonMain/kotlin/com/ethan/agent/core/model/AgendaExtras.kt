package com.ethan.agent.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 日程事件（对应后端 ethan/scheduler/agenda.py 的 AgendaStore）。
 *
 * - when: 'YYYY-MM-DD HH:MM'（服务器本地时区）；repeat=daily/weekly 时取其时分，日期为起始日
 * - repeat: none / daily / weekly
 * - weekdays: ISO 1=周一 … 7=周日（仅 weekly）
 * - status: pending / fired / missed / done
 * - next_run_time: ISO 8601（含时区偏移），仅 pending 时由 GET /agenda 附加
 */
@Serializable
data class AgendaEvent(
    val id: String,
    val title: String = "",
    val note: String = "",
    @SerialName("when") val whenText: String = "",
    val repeat: String = "none",
    val weekdays: List<Int> = emptyList(),
    val status: String = "pending",
    @SerialName("next_run_time") val nextRunTime: String? = null,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
)

@Serializable
data class AgendaResponse(
    val enabled: Boolean = false,
    val events: List<AgendaEvent> = emptyList(),
)

@Serializable
data class AgendaCreateRequest(
    val title: String,
    @SerialName("when") val whenText: String,
    val repeat: String = "none",
    val weekdays: List<Int> = emptyList(),
    val note: String = "",
)

@Serializable
data class AgendaPatchRequest(
    val title: String? = null,
    @SerialName("when") val whenText: String? = null,
    val repeat: String? = null,
    val weekdays: List<Int>? = null,
    val note: String? = null,
)

@Serializable
data class AgendaEventResponse(
    val ok: Boolean = false,
    val event: AgendaEvent? = null,
)

@Serializable
data class AgendaEnabledRequest(val enabled: Boolean)

@Serializable
data class AgendaEnabledResponse(
    val ok: Boolean = false,
    val enabled: Boolean = false,
)
