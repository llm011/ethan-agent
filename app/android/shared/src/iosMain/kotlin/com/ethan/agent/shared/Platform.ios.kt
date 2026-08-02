package com.ethan.agent.shared

import com.ethan.agent.core.datastore.createAppConfigStore
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.cinterop.ExperimentalForeignApi
import org.koin.core.context.startKoin
import org.koin.core.module.Module
import org.koin.dsl.module
import platform.Foundation.NSCachesDirectory
import platform.Foundation.NSFileManager
import platform.Foundation.NSSearchPathForDirectoriesInDomains
import platform.Foundation.NSUserDomainMask

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

/**
 * iOS 平台 DI 模块：AppConfigStore（Documents 目录）+ IosAppUpdater（no-op，走 App Store）。
 * iOS 工程接入时无需自己写 DI，直接调 [initKoin] 即可。
 */
fun iosPlatformModule(): Module = module {
    single { createAppConfigStore() }
    single<AppUpdater> { IosAppUpdater }
}

actual fun initKoin() {
    startKoin {
        modules(com.ethan.agent.shared.di.sharedModule(), iosPlatformModule())
    }
}
