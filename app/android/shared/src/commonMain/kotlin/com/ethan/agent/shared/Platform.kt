package com.ethan.agent.shared

import kotlinx.coroutines.CoroutineDispatcher

/**
 * 平台抽象：提供 IO dispatcher 和缓存目录路径。
 * Android 用 Dispatchers.IO + context.cacheDir；iOS 用 Dispatchers.Default + NSCachesDirectory。
 */
expect val ioDispatcher: CoroutineDispatcher

/** 返回平台缓存目录的绝对路径（用于 LocalCache 存 JSON 文件）。 */
expect fun cacheDirPath(): String
