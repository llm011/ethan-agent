package com.ethan.agent.shared

/**
 * 进程级「带 prompt 打开新对话」中转站（如 Agenda 的「拆解该安排」）。
 *
 * 与 [ShareBus]（ACTION_SEND 分享进文本，预填输入框）不同：这里是**跨页面跳转并自动发送**。
 * - 页面 A（如 Agenda）调 [post] 后导航到 `chat`（新会话）；
 * - 新 chat 目的地在**首次组合**时调 [take] 原子取走并自动发送——旧 chat 入口虽存活于返回栈，
 *   但不在组合中、不会调用 take，天然规避重复消费；
 * - take 后即清空：旋转/进程重建后取到 null，不会重复发送（代价是进程死亡丢 prompt，可接受，
 *   Web 端 sessionStorage 方案同理）。
 */
object ChatLauncherBus {
    @Volatile
    private var pending: String? = null

    fun post(prompt: String) {
        if (prompt.isNotBlank()) pending = prompt
    }

    /** 原子取走并清空：仅第一个调用者拿到值。 */
    fun take(): String? = synchronized(this) {
        val v = pending
        pending = null
        v
    }
}
