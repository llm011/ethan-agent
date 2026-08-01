package com.ethan.agent.shared

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.cinterop.ExperimentalForeignApi
import platform.Foundation.NSCachesDirectory
import platform.Foundation.NSSearchPathForDirectoriesInDomains
import platform.Foundation.NSUserDomainMask
import platform.Foundation.NSFileManager

actual val ioDispatcher: CoroutineDispatcher = Dispatchers.Default

@OptIn(ExperimentalForeignApi::class)
actual fun cacheDirPath(): String {
    val cachesDir = NSSearchPathForDirectoriesInDomains(
        NSCachesDirectory, NSUserDomainMask, true
    ).firstOrNull() as? String ?: ""
    val cacheDir = "$cachesDir/ethan_cache"
    NSFileManager.defaultManager.createDirectoryAtPath(cacheDir, withIntermediateDirectories = true, attributes = null, error = null)
    return cacheDir
}
