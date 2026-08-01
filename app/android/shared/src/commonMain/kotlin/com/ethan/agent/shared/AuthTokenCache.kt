package com.ethan.agent.shared

import com.ethan.agent.core.datastore.AppConfigStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking

class AuthTokenCache(
    configStore: AppConfigStore,
) {
    // @Volatile 是 JVM-only；KMP 下用 MutableStateFlow.value 做线程安全的同步读写。
    // 构造时 runBlocking 同步 seed 持久化 token，避免冷启动竞态（同 ServerUrlCache）。
    private val token = MutableStateFlow(
        runBlocking { configStore.config.first().authToken }
    )

    init {
        CoroutineScope(SupervisorJob() + ioDispatcher).launch {
            configStore.config.collect { token.value = it.authToken }
        }
    }

    fun get(): String = token.value
}
