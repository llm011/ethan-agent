package com.ethan.agent.core.network

import io.ktor.client.engine.HttpClientEngine
import io.ktor.client.engine.okhttp.OkHttp

actual fun httpClientEngine(): HttpClientEngine = OkHttp.create()

actual fun isDebugBuild(): Boolean = BuildConfig.DEBUG
