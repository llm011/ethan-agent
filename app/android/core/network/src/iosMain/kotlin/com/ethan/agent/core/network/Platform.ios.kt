package com.ethan.agent.core.network

import io.ktor.client.engine.HttpClientEngine
import io.ktor.client.engine.darwin.Darwin

actual fun httpClientEngine(): HttpClientEngine = Darwin.create()

// iOS 侧暂不区分 debug/release；如需可后续用 Platform.isDebugBinary。
actual fun isDebugBuild(): Boolean = false
