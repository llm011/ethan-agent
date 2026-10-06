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

/**
 * 交付文件签名的保鲜判断。
 *
 * 服务端 TTL 是 600s（ethan/core/services/signed_url.py），客户端必须留安全余量：
 * 卡片在组合期签一次名，用户很可能十几分钟后才点「播放/下载」——那时签名早过期，
 * 直链只会 401，而外部浏览器 / 系统播放器拿到 401 的表现是静默失败（白页或一直转圈），
 * App 里看不出任何原因。留 60s 余量：快过期的签名当过期处理，重新签一张。
 */
object FileSignatureFreshness {
    const val TTL_MS = 600_000L
    const val SAFETY_MARGIN_MS = 60_000L

    /**
     * @param signedAtMs 本地签下这张签名的时间（0 = 还没签过）。
     * @param nowMs 当前时间。
     * 时间倒流（用户改了系统时间/时区）也当过期：宁可多签一次，不要拿一张可能已失效的直链去撞 401。
     */
    fun isStale(signedAtMs: Long, nowMs: Long): Boolean =
        signedAtMs <= 0L || nowMs < signedAtMs || nowMs - signedAtMs >= TTL_MS - SAFETY_MARGIN_MS
}

@Serializable
data class DeckResponse(
    val name: String = "",
    val dir: String = "",
    val deck: JsonElement? = null,
    val pages: List<JsonElement> = emptyList(),
    @SerialName("page_count") val pageCount: Int = 0,
    @SerialName("pptx_path") val pptxPath: String? = null,
)
