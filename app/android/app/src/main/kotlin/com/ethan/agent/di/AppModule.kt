package com.ethan.agent.di

import android.content.Context
import com.ethan.agent.core.datastore.AppConfigStore
import com.ethan.agent.core.datastore.DEFAULT_SERVER_URL
import com.ethan.agent.core.model.ServerUrlUtils
import com.ethan.agent.core.network.ChatSseClient
import com.ethan.agent.core.network.EthanApiService
import com.ethan.agent.core.network.NetworkFactory
import com.ethan.agent.data.EthanRepository
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    @Provides
    @Singleton
    fun provideAppConfigStore(@ApplicationContext context: Context): AppConfigStore =
        AppConfigStore(context)

    @Provides
    @Singleton
    fun provideTokenProvider(configStore: AppConfigStore): () -> String = {
        runBlocking { configStore.config.first().authToken }
    }

    @Provides
    @Singleton
    fun provideApiService(
        configStore: AppConfigStore,
        tokenProvider: () -> String,
    ): EthanApiService {
        val config = runBlocking { configStore.config.first() }
        val apiBase = ServerUrlUtils.toApiBaseUrl(config.serverUrl)
        return try {
            NetworkFactory.createApiService(apiBase, tokenProvider)
        } catch (_: IllegalArgumentException) {
            NetworkFactory.createApiService(
                ServerUrlUtils.toApiBaseUrl(DEFAULT_SERVER_URL),
                tokenProvider,
            )
        }
    }

    @Provides
    @Singleton
    fun provideSseClient(tokenProvider: () -> String): ChatSseClient {
        return NetworkFactory.createSseClient(tokenProvider)
    }

    @Provides
    @Singleton
    fun provideRepository(
        configStore: AppConfigStore,
        api: EthanApiService,
        sseClient: ChatSseClient,
        tokenProvider: () -> String,
    ): EthanRepository = EthanRepository(configStore, api, sseClient, tokenProvider)
}
