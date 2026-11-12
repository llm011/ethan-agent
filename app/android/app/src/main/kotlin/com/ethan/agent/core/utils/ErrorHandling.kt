package com.ethan.agent.core.utils

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/**
 * 全局错误处理 - 统一错误管理
 */
object ErrorManager {
    private val _errorFlow = MutableSharedFlow<String>(extraBufferCapacity = 10)
    val errorFlow = _errorFlow.asSharedFlow()
    
    /**
     * 抛出错误
     */
    suspend fun showError(message: String) {
        _errorFlow.emit(message)
    }
    
    /**
     * 显示成功提示
     */
    suspend fun showSuccess(message: String) {
        // TODO: 实现 Toast 或 Snackbar
    }
}

/**
 * 网络异常处理扩展函数
 */
inline fun <T> Result<T>.onSuccessOrThrow(
    onError: (Throwable) -> Unit = { throw it },
): T {
    return fold(
        onSuccess = { this },
        onFailure = { exception ->
            onError(exception)
            throw exception
        }
    )
}

/**
 * 安全的可空类型转换
 */
fun <T, R> T?.mapOrNull(transform: (T) -> R): R? = this?.let(transform)

/**
 * 安全的字符串操作
 */
fun String?.isNullOrBlank(): Boolean = this == null || this.isBlank()

/**
 * 安全的集合操作
 */
fun <T> List<T>?.orEmpty(): List<T> = this ?: emptyList()

/**
 * 安全的 Map 操作
 */
fun <K, V> Map<K, V>?.orEmpty(): Map<K, V> = this ?: emptyMap()
