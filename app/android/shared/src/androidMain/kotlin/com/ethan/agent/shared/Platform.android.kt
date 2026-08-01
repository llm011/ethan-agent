package com.ethan.agent.shared

import android.content.Context
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import java.io.File

lateinit var appContext: Context

actual val ioDispatcher: CoroutineDispatcher = Dispatchers.IO

actual fun cacheDirPath(): String {
    return File(appContext.cacheDir, "ethan_cache").apply { mkdirs() }.absolutePath
}
