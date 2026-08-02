package com.ethan.agent.shared

import android.content.Context
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import org.koin.android.ext.koin.androidContext
import org.koin.core.context.startKoin
import java.io.File

/** Android 平台上下文，由 :app 的 Application.onCreate 赋值。 */
lateinit var appContext: Context

actual val ioDispatcher: CoroutineDispatcher = Dispatchers.IO

actual fun cacheDirPath(): String {
    return File(appContext.cacheDir, "ethan_cache").apply { mkdirs() }.absolutePath
}

/**
 * Android 启动 Koin：注册 SharedModule + :app 提供的 platformModule。
 *
 * platformModule 必须在调用 initKoin 前通过 [setupAndroidPlatformModule] 注入，
 * 因为它引用 :app 的 AndroidAppUpdater（:shared 不能反向依赖 :app）。
 */
private var androidPlatformModuleProvider: (() -> org.koin.core.module.Module)? = null

fun setupAndroidPlatformModule(provider: () -> org.koin.core.module.Module) {
    androidPlatformModuleProvider = provider
}

actual fun initKoin() {
    val provider = androidPlatformModuleProvider
        ?: error("必须先调用 setupAndroidPlatformModule { platformModule() } 提供 Android 平台模块")
    startKoin {
        androidContext(appContext)
        modules(com.ethan.agent.shared.di.sharedModule(), provider())
    }
}
