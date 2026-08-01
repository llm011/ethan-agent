package com.ethan.agent.shared

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 进程级「分享到 Ethan」中转站。
 *
 * MainActivity 收到 ACTION_SEND intent 后 post 进来；Chat 层**响应式订阅** pending 值消费。
 *
 * 为什么是 StateFlow<String?> + 消费时置 null，而不是一次性事件流：
 * - 冷启动：onCreate 先 post，ChatViewModel 后创建；StateFlow 保留最新值，订阅者就绪后仍能拿到。
 * - 前台再分享（onNewIntent）：值变化会让**已存在**的订阅者重新触发——只要消费端 collect /
 *   `LaunchedEffect(pending)` 跟着值走，而不是 `LaunchedEffect(Unit)` 只跑一次。
 * - 不重放已消费事件：消费后置 null，新建的 ChatViewModel 订阅到的是 null，不会重复注入
 *   （若用 SharedFlow(replay=1) 会在每个新订阅者上重放旧值，反而重复注入）。
 * - 消费用 [MutableStateFlow.compareAndSet] 原子完成：只清掉「正好观察到的那个值」，
 *   并发 / 新值到达时不会误清，规避「读 value + 手动置 null」的竞态。
 *
 * 用简单单例而非 DI，是因为 intent 在 Activity 层最先到达。
 */
object ShareBus {
    /** 分享进来的纯文本（text/plain）；消费后置 null。 */
    private val _pendingText = MutableStateFlow<String?>(null)
    val pendingText: StateFlow<String?> = _pendingText.asStateFlow()

    /** 分享进来的文件/图片 URI 字符串；消费后置 null。 */
    private val _pendingUri = MutableStateFlow<String?>(null)
    val pendingUri: StateFlow<String?> = _pendingUri.asStateFlow()

    fun postText(text: String?) {
        if (!text.isNullOrBlank()) _pendingText.value = text
    }

    fun postUri(uri: String?) {
        if (!uri.isNullOrBlank()) _pendingUri.value = uri
    }

    /** 原子消费文本：仅当当前值仍等于 [value] 时清空，避免误清后到的新分享。 */
    fun consumeText(value: String) {
        _pendingText.compareAndSet(value, null)
    }

    /** 原子消费 URI：仅当当前值仍等于 [value] 时清空。 */
    fun consumeUri(value: String) {
        _pendingUri.compareAndSet(value, null)
    }
}
