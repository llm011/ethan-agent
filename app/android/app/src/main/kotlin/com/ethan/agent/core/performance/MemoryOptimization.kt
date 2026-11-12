package com.ethan.agent.core.performance

import android.app.Activity
import android.content.Context
import android.util.LruCache
import androidx.compose.runtime.*
import coil.ImageLoader
import coil.decode.GifDecoder
import coil.decode.WebpDecoder
import coil.disk.DiskCache
import coil.memory.MemoryCache
import java.lang.ref.WeakReference

/**
 * 内存优化工具类
 * 
 * 优化点：
 * 1. LruCache 缓存图片
 * 2. 弱引用避免内存泄漏
 * 3. 内存使用监控
 */

/**
 * 图片缓存 - 自动管理内存
 */
class ImageCache(context: Context) {
    private val memoryCache = object : LruCache<String, Any>(maxMemory().toInt() / 8) {
        override fun sizeOf(key: String, value: Any): Int {
            return when (value) {
                is ByteArray -> value.size
                else -> 1
            }
        }
    }
    
    fun get(key: String): Any? = memoryCache.get(key)
    
    fun put(key: String, value: Any) {
        memoryCache.put(key, value)
    }
    
    fun clear() {
        memoryCache.evictAll()
    }
    
    companion object {
        private var instance: ImageCache? = null
        
        fun getInstance(context: Context): ImageCache {
            return instance ?: synchronized(this) {
                instance ?: ImageCache(context).also { instance = it }
            }
        }
    }
}

/**
 * 内存使用监控
 */
object MemoryMonitor {
    private var lastReportTime = 0L
    private const val REPORT_INTERVAL_MS = 5 * 60 * 1000 // 5 分钟
    
    fun checkMemoryUsage(): String {
        val runtime = Runtime.getRuntime()
        val usedMemory = runtime.totalMemory() - runtime.freeMemory()
        val maxMemory = runtime.maxMemory()
        val availableMemory = runtime.availableProcessors()
        
        val usagePercent = (usedMemory.toFloat() / maxMemory * 100).toInt()
        
        return "内存使用：${formatBytes(usedMemory)} / ${formatBytes(maxMemory)} (${usagePercent}%), CPU 核心数：$availableMemory"
    }
    
    fun shouldReport(): Boolean {
        val currentTime = System.currentTimeMillis()
        if (currentTime - lastReportTime > REPORT_INTERVAL_MS) {
            lastReportTime = currentTime
            return true
        }
        return false
    }
    
    private fun formatBytes(bytes: Long): String {
        return when {
            bytes < 1024 -> "$bytes B"
            bytes < 1024 * 1024 -> "${bytes / 1024} KB"
            else -> "${bytes / (1024 * 1024)} MB"
        }
    }
}

/**
 * 创建优化的 Coil ImageLoader
 */
fun createOptimizedImageLoader(context: Context): ImageLoader {
    return ImageLoader.Builder(context)
        .memoryCache {
            MemoryCache.Builder(context)
                .maxSizePercent(0.25) // 使用 25% 可用内存
                .build()
        }
        .diskCache {
            DiskCache.Builder()
                .maxSizeBytes(50 * 1024 * 1024) // 50MB
                .build()
        }
        .components {
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                add(GifDecoder())
                add(WebpDecoder())
            }
        }
        .build()
}

/**
 * 避免内存泄漏的 ViewModelScope 扩展
 */
fun LifecycleOwner.safeViewModelScope(): LifecycleCoroutineScope {
    return lifecycleScope
}

/**
 * 弱引用包装器 - 避免内存泄漏
 */
class WeakReferenceWrapper<T>(private val reference: WeakReference<T>) {
    fun getOrNull(): T? = reference.get()
    
    companion object {
        fun <T> of(value: T): WeakReferenceWrapper<T> {
            return WeakReferenceWrapper(WeakReference(value))
        }
    }
}
