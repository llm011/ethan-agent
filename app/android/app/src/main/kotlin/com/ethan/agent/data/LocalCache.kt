package com.ethan.agent.data

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.Json
import java.io.File

/**
 * 轻量本地文件缓存：按 key 存 JSON 文件到 cacheDir/ethan_cache/<key>.json。
 *
 * 设计目标：stale-while-revalidate 模式的基础设施。
 * - 按 key 分文件，天然支持按 id 缓存（如 session_<id>）。
 * - 读缓存失败不影响调用方（返回 null）。
 * - 写缓存失败静默忽略（网络数据已拿到，缓存只是优化）。
 * - 不做过期/清理逻辑（cacheDir 由系统在低存储时自动清理）。
 */
class LocalCache(
    context: Context,
    private val json: Json = Json { ignoreUnknownKeys = true; encodeDefaults = false },
) {
    private val cacheDir = File(context.cacheDir, "ethan_cache").apply { mkdirs() }

    /** 将 key 中的路径分隔符替换为下划线，防止路径穿越。 */
    private fun sanitizeKey(key: String): String = key.replace("/", "_").replace("\\", "_")

    /** 读缓存；文件不存在或反序列化失败返回 null。 */
    suspend fun <T> read(key: String, serializer: KSerializer<T>): T? = withContext(Dispatchers.IO) {
        runCatching {
            val file = File(cacheDir, "${sanitizeKey(key)}.json")
            if (!file.exists()) return@runCatching null
            json.decodeFromString(serializer, file.readText())
        }.getOrNull()
    }

    /** 写缓存；失败静默忽略。 */
    suspend fun <T> write(key: String, value: T, serializer: KSerializer<T>) = withContext(Dispatchers.IO) {
        runCatching {
            val file = File(cacheDir, "${sanitizeKey(key)}.json")
            file.writeText(json.encodeToString(serializer, value))
        }
    }

    /** 删除指定 key 的缓存。 */
    suspend fun remove(key: String) = withContext(Dispatchers.IO) {
        runCatching { File(cacheDir, "${sanitizeKey(key)}.json").delete() }
    }

    /** 清空所有缓存。 */
    suspend fun clear() = withContext(Dispatchers.IO) {
        runCatching { cacheDir.listFiles()?.forEach { it.delete() } }
    }
}
