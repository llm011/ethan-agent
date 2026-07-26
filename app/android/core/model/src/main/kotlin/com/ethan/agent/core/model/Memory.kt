package com.ethan.agent.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

// ── Insights 永久记忆 ─────────────────────────────────────────────────────────

@Serializable
data class InsightItem(
    val id: String = "",
    val text: String = "",
    val metadata: Map<String, JsonElement> = emptyMap(),
)

@Serializable
data class InsightsListResponse(
    val items: List<InsightItem> = emptyList(),
    val total: Int = 0,
    val limit: Int = 20,
    val offset: Int = 0,
)

@Serializable
data class InsightsByDateResponse(
    val date: String = "",
    val items: List<JsonElement> = emptyList(),
)

@Serializable
data class ConsolidateResponse(
    val ok: Boolean = false,
    val message: String = "",
)

// ── Structured Records 结构化记忆 ─────────────────────────────────────────────

@Serializable
data class StructuredRecord(
    val id: String = "",
    @SerialName("memory_type") val memoryType: String = "",
    val dimension: String = "",
    @SerialName("memory_key") val memoryKey: String = "",
    val content: String = "",
    @SerialName("structured_data") val structuredData: Map<String, JsonElement> = emptyMap(),
    @SerialName("scope_type") val scopeType: String = "",
    @SerialName("scope_id") val scopeId: String = "",
    @SerialName("memory_domain") val memoryDomain: String = "",
    val status: String = "",
    @SerialName("evidence_level") val evidenceLevel: String = "",
    val confidence: Double = 0.0,
    val importance: Double = 0.0,
    val sensitivity: String = "",
    @SerialName("valid_from") @Serializable(with = NullableEpochSecondsSerializer::class) val validFrom: Long? = null,
    @SerialName("valid_until") @Serializable(with = NullableEpochSecondsSerializer::class) val validUntil: Long? = null,
    @SerialName("source_session_id") val sourceSessionId: String = "",
    @SerialName("source_message_id") val sourceMessageId: String = "",
    @SerialName("created_at") @Serializable(with = EpochSecondsSerializer::class) val createdAt: Long = 0,
    @SerialName("updated_at") @Serializable(with = EpochSecondsSerializer::class) val updatedAt: Long = 0,
    @SerialName("last_recalled_at") @Serializable(with = NullableEpochSecondsSerializer::class) val lastRecalledAt: Long? = null,
    @SerialName("superseded_by") val supersededBy: String? = null,
)

@Serializable
data class RecordListResponse(val items: List<StructuredRecord> = emptyList())

@Serializable
data class RecordDetailResponse(
    val record: StructuredRecord? = null,
    val evidence: List<JsonElement> = emptyList(),
)

@Serializable
data class RecordEvidenceResponse(val evidence: List<JsonElement> = emptyList())

@Serializable
data class UpdateRecordRequest(
    val content: String? = null,
    @SerialName("structured_data") val structuredData: Map<String, JsonElement>? = null,
    val confidence: Double? = null,
    val importance: Double? = null,
    @SerialName("valid_from") val validFrom: Double? = null,
    @SerialName("valid_until") val validUntil: Double? = null,
    @SerialName("clear_valid_from") val clearValidFrom: Boolean = false,
    @SerialName("clear_valid_until") val clearValidUntil: Boolean = false,
)

@Serializable
data class UpdateRecordResponse(val record: StructuredRecord? = null)

@Serializable
data class ConfirmRecordResponse(
    val ok: Boolean = false,
    val record: StructuredRecord? = null,
)

@Serializable
data class DailySummariesResponse(val items: List<JsonElement> = emptyList())
