package com.ethan.agent.shared.viewmodel

/**
 * 聊天气泡的说话方分类，用于**按角色着色**。
 *
 * 移动端隐藏头像后，颜色成了区分「谁在说话」的**主要**视觉线索（与角色名文字并用，
 * 不是唯一线索）—— 所以这个分类必须覆盖所有真实出现的说话方，而不是只有 user/assistant 两档：
 *   - 工具结果卡片、系统提示（如 `/help` 输出）与助手正式回复在语义上不同，
 *     共用一种颜色会让长会话变成一坨同色气泡；
 *   - 这些 role 确实会出现在数据里：会话历史来自服务端的 `msg.role`，
 *     而服务端会写入 `tool` / `system`（不只是 user/assistant）；
 *   - 会话/角色数量是可扩展的（未来可能有多 agent），所以颜色**按角色稳定推导**，
 *     而不是硬编码两个分支。
 *
 * 只做分类，不碰颜色：具体色值由各端的设计系统给（Android 走 MaterialTheme、
 * iOS 走自身的 Color 体系），这样主题切换时颜色自动跟随。
 */
enum class MessageRoleKind {
    /** 用户发言。 */
    User,

    /** 助手（Ethan 本体）发言。 */
    Assistant,

    /** 工具调用 / 工具结果的展示。 */
    Tool,

    /** 系统/本地生成的内容（slash command 回显、错误提示等）。 */
    System,
    ;

    companion object {
        /**
         * 从消息的 role 字符串推断分类。
         *
         * 宽容处理未知值：服务端未来加了新 role（或历史数据里有脏值）时，
         * 未知 role 一律落到 [Assistant] —— 气泡至少有颜色，不会因为查不到而渲染异常。
         * 这比抛异常或返回 null 更符合「展示层要能扛住脏数据」的要求。
         */
        fun of(role: String?): MessageRoleKind = when (role?.trim()?.lowercase()) {
            "user" -> User
            "assistant" -> Assistant
            "tool", "function", "tool_result" -> Tool
            "system" -> System
            else -> Assistant
        }
    }
}
