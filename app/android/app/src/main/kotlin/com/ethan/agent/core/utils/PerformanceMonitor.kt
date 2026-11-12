package com.ethan.agent.core.utils

import android.util.Log
import kotlinx.coroutines.delay
import kotlin.system.measureTimeMillis

/**
 * 性能监控工具 - 用于追踪应用性能
 */
object PerformanceMonitor {
    private const val TAG = "PerfMonitor"
    
    /**
     * 测量函数执行时间
     */
    inline fun <T> measure(tag: String, block: () -> T): Pair<T, Long> {
        val startTime = System.currentTimeMillis()
        val result = block()
        val duration = System.currentTimeMillis() - startTime
        
        if (duration > 100) { // 超过 100ms 记录警告
            Log.w(TAG, "$tag 耗时：${duration}ms")
        }
        
        return Pair(result, duration)
    }
    
    /**
     * 异步性能追踪
     */
    suspend inline fun <T> asyncMeasure(tag: String, block: suspend () -> T): Pair<T, Long> {
        val startTime = System.currentTimeMillis()
        val result = block()
        val duration = System.currentTimeMillis() - startTime
        
        if (duration > 100) {
            Log.w(TAG, "[$tag] 异步操作耗时：${duration}ms")
        }
        
        return Pair(result, duration)
    }
    
    /**
     * 检查主线程阻塞
     */
    fun checkMainThreadBlocking(operationName: String, timeoutMs: Long = 500) {
        val handler = android.os.Handler(android.os.Looper.getMainLooper())
        val blockingFlag = BooleanArray(1)
        
        handler.postDelayed({
            if (blockingFlag[0]) {
                Log.e(TAG, "$operationName 在主线程阻塞超过 ${timeoutMs}ms!")
            }
        }, timeoutMs)
        
        try {
            blockingFlag[0] = true
            // TODO: 这里应该包装实际的操作
        } finally {
            blockingFlag[0] = false
        }
    }
    
    /**
     * 内存使用检查
     */
    fun checkMemoryUsage(): String {
        val runtime = Runtime.getRuntime()
        val usedMemory = runtime.totalMemory() - runtime.freeMemory()
        val maxMemory = runtime.maxMemory()
        val availableMemory = runtime.availableProcessors()
        
        return "内存使用：${usedMemory / 1024 / 1024}MB / ${maxMemory / 1024 / 1024}MB, CPU 核心数：$availableMemory"
    }
    
    /**
     * 启动性能报告
     */
    fun logStartupPerformance(initTime: Long) {
        if (initTime > 2000) {
            Log.w(TAG, "应用初始化耗时过长：${initTime}ms")
        } else {
            Log.i(TAG, "应用初始化完成：${initTime}ms")
        }
    }
}

/**
 * 性能优化注解 - 标记需要特别关注的函数
 */
@Target(AnnotationTarget.FUNCTION)
@Retention(AnnotationRetention.RUNTIME)
annotation class PerfCritical

/**
 * 性能测试辅助函数
 */
suspend fun simulateNetworkCall(delayMs: Int = 1000): String {
    delay(delayMs.toLong())
    return "模拟网络响应"
}
