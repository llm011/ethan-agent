package com.ethan.agent.core.repository

import com.ethan.agent.core.model.Message
import com.ethan.agent.core.network.EthanApiService
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/**
 * 聊天数据仓库 - 负责聊天相关的数据操作
 * 职责：
 * 1. 管理消息列表
 * 2. 处理会话状态
 * 3. 与 API 服务交互
 */
class ChatRepository(
    private val apiService: EthanApiService,
) {
    private val _messages = mutableListOf<Message>()
    private var _currentSessionId: String? = null
    
    // 公开的消息流（只读）
    val messagesFlow: Flow<List<Message>> = _messages.asFlow()
    
    // 当前会话 ID
    var currentSessionId: String?
        get() = _currentSessionId
        set(value) {
            _currentSessionId = value
            if (value == null) {
                _messages.clear()
            }
        }
    
    /**
     * 发送消息到服务器
     */
    suspend fun sendMessage(content: String): Result<Message> {
        return try {
            val response = apiService.sendMessage(
                sessionId = _currentSessionId,
                content = content,
            )
            
            response.onSuccess { message ->
                _messages.add(message)
            }
            
            Result.success(response.getOrNull() ?: error("发送失败"))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    /**
     * 停止流式响应
     */
    suspend fun stopStreaming(): Result<Unit> {
        return try {
            apiService.stopStreaming(_currentSessionId)
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    /**
     * 获取历史消息
     */
    suspend fun loadHistory(sessionId: String): Result<List<Message>> {
        return try {
            val messages = apiService.getMessages(sessionId)
            _messages.clear()
            _messages.addAll(messages)
            Result.success(messages)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    /**
     * 创建新会话
     */
    suspend fun createNewSession(title: String? = null): Result<String> {
        return try {
            val response = apiService.createSession(title)
            response.onSuccess { session ->
                _currentSessionId = session.id
                _messages.clear()
            }
            Result.success(response.getOrNull() ?: error("创建会话失败"))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
    
    /**
     * 清除错误状态
     */
    fun clearError() {
        // TODO: 实现错误清除逻辑
    }
}
