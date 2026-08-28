package com.ethan.agent.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class SignRequest(val paths: List<String>)

@Serializable
data class SignResponse(
    val user: String = "",
    val signatures: Map<String, String> = emptyMap(),
)

/** files/sign 换来的 path 级短期签名（10 分钟有效），拼进 view/download URL 的 ?user=&sig= */
@Serializable
data class FileSignature(val user: String, val sig: String)

@Serializable
data class DeckResponse(
    val name: String = "",
    val dir: String = "",
    val deck: JsonElement? = null,
    val pages: List<JsonElement> = emptyList(),
    @SerialName("page_count") val pageCount: Int = 0,
    @SerialName("pptx_path") val pptxPath: String? = null,
)
