package com.ethan.agent.shared

import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.Json
import okio.FileSystem
import okio.Path.Companion.toPath

/**
 * 轻量本地文件缓存：按 key 存 JSON 文件到 cacheDirPath()/<key>.json。
 * SWR 模式的基础设施。读缓存失败返回 null，写缓存失败静默忽略。
 */
class LocalCache(
    private val json: Json = Json { ignoreUnknownKeys = true; encodeDefaults = false },
) {
    private val fs = FileSystem.SYSTEM

    private fun sanitizeKey(key: String): String = key.replace("/", "_").replace("\\", "_")

    private fun filePath(key: String) = "${cacheDirPath()}/${sanitizeKey(key)}.json".toPath()

    suspend fun <T> read(key: String, serializer: KSerializer<T>): T? = withContext(ioDispatcher) {
        runCatching {
            val path = filePath(key)
            if (!fs.exists(path)) return@runCatching null
            json.decodeFromString(serializer, fs.read(path) { readUtf8() })
        }.getOrNull()
    }

    suspend fun <T> write(key: String, value: T, serializer: KSerializer<T>) = withContext(ioDispatcher) {
        runCatching {
            fs.write(filePath(key)) { write(json.encodeToString(serializer, value).encodeToByteArray()) }
        }
    }

    suspend fun remove(key: String) = withContext(ioDispatcher) {
        runCatching { fs.delete(filePath(key)) }
    }

    suspend fun clear() = withContext(ioDispatcher) {
        runCatching {
            val dir = cacheDirPath().toPath()
            fs.list(dir).forEach { fs.delete(dir.resolve(it)) }
        }
    }
}
