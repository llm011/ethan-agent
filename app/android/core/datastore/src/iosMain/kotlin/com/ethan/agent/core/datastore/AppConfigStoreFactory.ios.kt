package com.ethan.agent.core.datastore

import kotlinx.cinterop.ExperimentalForeignApi
import platform.Foundation.NSDocumentDirectory
import platform.Foundation.NSFileManager
import platform.Foundation.NSUserDomainMask

/**
 * iOS 侧构造 [AppConfigStore]：DataStore 文件放在 app 的 Documents 目录下。
 */
@OptIn(ExperimentalForeignApi::class)
fun createAppConfigStore(): AppConfigStore {
    val documents = NSFileManager.defaultManager.URLForDirectory(
        directory = NSDocumentDirectory,
        inDomain = NSUserDomainMask,
        appropriateForURL = null,
        create = false,
        error = null,
    )
    val path = requireNotNull(documents?.path) { "无法获取 iOS Documents 目录" } + "/$APP_CONFIG_STORE_FILE"
    return AppConfigStore(createAppConfigDataStore(path))
}
