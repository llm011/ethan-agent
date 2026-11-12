package com.ethan.agent.core.network

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.retry

/**
 * 优化的网络管理器
 * 
 * 改进点：
 * 1. 响应式编程（Flow）
 * 2. 自动重试机制
 * 3. 错误降级处理
 * 4. 离线支持
 */

/**
 * 带重试的网络请求
 */
suspend inline fun <T> networkRequestWithRetry(
    maxRetries: Int = 3,
    crossinline request: suspend () -> T,
): Result<T> {
    return try {
        retry(maxRetries) {
            request()
                .let { Result.success(it) }
        }
    } catch (e: Exception) {
        Result.failure(e)
    }
}

/**
 * 流式网络请求
 */
fun flowWithRetry(
    maxRetries: Int = 3,
    crossinline request: suspend () -> Flow<Result<*>>,
): Flow<Result<*>> {
    return flow {
        var lastError: Exception? = null
        
        for (attempt in 1..maxRetries) {
            try {
                emit(request().first())
                break
            } catch (e: Exception) {
                lastError = e
                if (attempt == maxRetries) {
                    emit(Result.failure(e))
                }
            }
        }
    }.catch { e ->
        emit(Result.failure(e))
    }
}

/**
 * 网络状态管理
 */
class NetworkStateManager {
    private val _isConnected = MutableStateFlow(true)
    val isConnected: StateFlow<Boolean> = _isConnected.asStateFlow()
    
    fun updateStatus(isConnected: Boolean) {
        _isConnected.value = isConnected
    }
    
    fun isOnline(): Boolean = _isConnected.value
}
