package com.ethan.agent.domain.usecase

import com.ethan.agent.core.repository.ChatRepository
import com.ethan.agent.core.model.Message
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/**
 * 发送消息用例 - Domain 层
 * 
 * Clean Architecture 原则：
 * - 只依赖 Repository 接口，不依赖具体实现
 * - 不包含 UI 逻辑
 * - 返回 Flow 支持响应式编程
 */
class SendMessageUseCase(
    private val chatRepository: ChatRepository,
) {
    suspend operator fun invoke(content: String): Flow<Result<Message>> {
        return try {
            chatRepository.sendMessage(content)
                .let { flow -> flow.map { Result.success(it) } }
        } catch (e: Exception) {
            // Domain 层处理业务异常
            flow { emit(Result.failure(e)) }
        }
    }
}

/**
 * 加载历史消息用例
 */
class LoadHistoryUseCase(
    private val chatRepository: ChatRepository,
) {
    suspend operator fun invoke(sessionId: String): Flow<Result<List<Message>>> {
        return try {
            chatRepository.loadHistory(sessionId)
                .let { flow -> flow.map { Result.success(it) } }
        } catch (e: Exception) {
            flow { emit(Result.failure(e)) }
        }
    }
}

/**
 * 创建新会话用例
 */
class CreateNewSessionUseCase(
    private val chatRepository: ChatRepository,
) {
    suspend operator fun invoke(title: String? = null): Flow<Result<String>> {
        return try {
            chatRepository.createNewSession(title)
                .let { flow -> flow.map { Result.success(it) } }
        } catch (e: Exception) {
            flow { emit(Result.failure(e)) }
        }
    }
}
