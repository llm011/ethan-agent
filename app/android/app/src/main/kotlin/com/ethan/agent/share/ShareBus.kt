package com.ethan.agent.share

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 进程级「分享到 Ethan」中转站。
 *
 * MainActivity 收到 ACTION_SEND intent 后把内容写进来；ChatViewModel 在初始化时
 * 消费一次（consume 后清空，避免旋转屏幕 / 重进重复注入）。
 *
 * 用简单单例而非 DI，是因为 intent 在 Activity 层最先到达，且分享内容是「一次性事件」，
 * StateFlow + consume 的组合最直接。
 */
object ShareBus {
    /** 分享进来的纯文本（text/plain）。 */
    private val _pendingText = MutableStateFlow<String?>(null)
    val pendingText: StateFlow<String?> = _pendingText.asStateFlow()

    /** 分享进来的文件/图片 URI 字符串。 */
    private val _pendingUri = MutableStateFlow<String?>(null)
    val pendingUri: StateFlow<String?> = _pendingUri.asStateFlow()

    fun postText(text: String?) {
        if (!text.isNullOrBlank()) _pendingText.value = text
    }

    fun postUri(uri: String?) {
        if (!uri.isNullOrBlank()) _pendingUri.value = uri
    }

    /** 取出并清空文本；无内容返回 null。 */
    fun consumeText(): String? {
        val v = _pendingText.value
        _pendingText.value = null
        return v
    }

    /** 取出并清空 URI；无内容返回 null。 */
    fun consumeUri(): String? {
        val v = _pendingUri.value
        _pendingUri.value = null
        return v
    }

    fun hasPending(): Boolean = _pendingText.value != null || _pendingUri.value != null
}
