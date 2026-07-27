package com.ethan.agent.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class Annotation(
    val id: Int = 0,
    val type: String = "",
    val color: String? = null,
    val start: Int = 0,
    val end: Int = 0,
    val quote: String? = null,
    val note: String? = null,
    @SerialName("created_at") @Serializable(with = EpochSecondsSerializer::class) val createdAt: Long = 0,
)

@Serializable
data class AnnotationsResponse(val annotations: List<Annotation> = emptyList())

/** batch 端点直接返回 Map<messageId, List<Annotation>>，无外层 wrapper */
typealias BatchAnnotationsResponse = Map<String, List<Annotation>>

@Serializable
data class AnnotationCreateRequest(
    @SerialName("message_id") val messageId: Long,
    val type: String,
    val color: String? = null,
    val start: Int,
    val end: Int,
    val quote: String? = null,
    val note: String? = null,
)

@Serializable
data class AnnotationCreateResponse(
    val id: Int = 0,
    val ok: Boolean = false,
)

@Serializable
data class DeleteAnnotationResponse(val ok: Boolean = false)
