package com.ethan.agent.shared

import com.ethan.agent.core.datastore.AppConfigStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking

class AuthTokenCache(
    private val configStore: AppConfigStore,
) {
    // @Volatile 是 JVM-only；KMP 下用 MutableStateFlow.value 做线程安全的同步读写。
    private val token = MutableStateFlow("")
    private var seeded = false

    init {
        // async collect：后台读 DataStore，首次发射后标记 seeded。
        // 构造器不阻塞，避免 Koin single 懒加载时在主线程 runBlocking（同 ServerUrlCache）。
        CoroutineScope(SupervisorJob() + ioDispatcher).launch {
            configStore.config.collect {
                token.value = it.authToken
                seeded = true
            }
        }
    }

    fun get(): String {
        // 冷启动竞态兜底：若 async collect 尚未首次发射，同步读一次。
        // get() 由 Ktor tokenProvider 在请求时调用，请求跑在后台线程，不阻塞主线程。
        if (!seeded) {
            runBlocking { token.value = configStore.config.first().authToken }
            seeded = true
        }
        return token.value
    }
}
