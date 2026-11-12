package com.ethan.agent.domain.model

/**
 * 领域模型 - 与 UI 无关的业务数据
 */
data class ChatSession(
    val id: String,
    val title: String?,
    val createdAt: Long,
    val updatedAt: Long,
    val messageCount: Int,
)

/**
 * 消息领域模型（与 Repository 层解耦）
 */
data class DomainMessage(
    val id: String,
    val sessionId: String,
    val role: String, // "user" | "assistant"
    val content: String,
    val timestamp: Long,
    val isStreaming: Boolean = false,
)

/**
 * 聊天状态枚举
 */
enum class ChatState {
    IDLE,           // 空闲
    LOADING,        // 加载中
    STREAMING,      // 流式传输中
    ERROR,          // 错误状态
    STOPPED,        // 已停止
}

/**
 * 连接状态
 */
enum class ConnectionStatus {
    CONNECTED,
    CONNECTING,
    DISCONNECTED,
    RECONNECTING,
}
