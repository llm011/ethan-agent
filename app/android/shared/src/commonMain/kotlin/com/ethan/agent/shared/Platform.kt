package com.ethan.agent.shared

import kotlinx.coroutines.CoroutineDispatcher

/**
 * 平台抽象：提供 IO dispatcher 和缓存目录路径。
 * Android 用 Dispatchers.IO + context.cacheDir；iOS 用 Dispatchers.Default + NSCachesDirectory。
 */
expect val ioDispatcher: CoroutineDispatcher

/** 返回平台缓存目录的绝对路径（用于 LocalCache 存 JSON 文件）。 */
expect fun cacheDirPath(): String

/**
 * 启动 Koin：注册 [com.ethan.agent.shared.di.sharedModule] + 平台 module。
 *
 * 平台 module（提供 AppConfigStore / AppUpdater 的 actual）由各端自行注册：
 * - Android：在 :app 的 EthanApplication 里用 platformModule()（引用 AndroidAppUpdater）
 * - iOS：在 iosMain 的 initKoin actual 里用 iosPlatformModule()（IosAppUpdater no-op）
 *
 * Android 在 Application.onCreate 调；iOS 在 AppDelegate 启动时调。
 */
expect fun initKoin()
