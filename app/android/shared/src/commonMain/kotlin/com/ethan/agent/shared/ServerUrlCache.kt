package com.ethan.agent.shared

import com.ethan.agent.core.datastore.AppConfigStore
import com.ethan.agent.core.datastore.DEFAULT_SERVER_URL
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking

/**
 * 进程级缓存当前 server url（origin），供 Ktor 的 baseUrlProvider 同步读取。
 *
 * 与 [AuthTokenCache] 同理：Ktor client 是单例，baseUrlProvider 每次请求同步取值，
 * 不能 suspend 读 DataStore，所以用 MutableStateFlow 缓存 + 后台 collect config 更新。
 *
 * 构造时用 runBlocking 同步 seed 一次持久化值，避免冷启动竞态：否则 collect 尚未
 * 首次发射时 baseUrlProvider() 返回 DEFAULT_SERVER_URL（localhost），远程用户的首次
 * 请求会打到错误地址。后台 collect 随后接管后续更新；saveServerUrl 时同步 set()。
 */
class ServerUrlCache(
    configStore: AppConfigStore,
) {
    private val url = MutableStateFlow(
        runBlocking { configStore.config.first().serverUrl }
    )

    init {
        CoroutineScope(SupervisorJob() + ioDispatcher).launch {
            configStore.config.collect { url.value = it.serverUrl }
        }
    }

    fun get(): String = url.value

    fun set(newUrl: String) {
        url.value = newUrl
    }
}
