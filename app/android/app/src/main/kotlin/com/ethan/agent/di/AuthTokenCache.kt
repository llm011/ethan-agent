package com.ethan.agent.di

import com.ethan.agent.core.datastore.AppConfigStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AuthTokenCache @Inject constructor(
    configStore: AppConfigStore,
) {
    @Volatile
    private var token: String = ""

    init {
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            configStore.config.collect { token = it.authToken }
        }
    }

    fun get(): String = token
}
