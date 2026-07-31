package com.ethan.agent.di

import com.ethan.agent.core.datastore.AppConfigStore
import com.ethan.agent.core.datastore.DEFAULT_SERVER_URL
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 进程级缓存当前 server url（origin），供 Ktor 的 baseUrlProvider 同步读取。
 *
 * 与 [AuthTokenCache] 同理：Ktor client 是单例，baseUrlProvider 每次请求同步取值，
 * 不能 suspend 读 DataStore，所以用 volatile 缓存 + 后台 collect config 更新。
 * saveServerUrl 时另外同步 set()，避免登录/切服务器后仍指向旧地址的竞态。
 */
@Singleton
class ServerUrlCache @Inject constructor(
    configStore: AppConfigStore,
) {
    @Volatile
    private var url: String = DEFAULT_SERVER_URL

    init {
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            configStore.config.collect { url = it.serverUrl }
        }
    }

    fun get(): String = url

    fun set(newUrl: String) {
        url = newUrl
    }
}
