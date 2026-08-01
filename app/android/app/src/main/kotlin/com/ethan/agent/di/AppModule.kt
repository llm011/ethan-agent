package com.ethan.agent.di

import android.content.Context
import com.ethan.agent.core.datastore.AppConfigStore
import com.ethan.agent.core.network.ChatSseClient
import com.ethan.agent.core.network.EthanApiService
import com.ethan.agent.core.network.NetworkFactory
import com.ethan.agent.data.EthanRepository
import com.ethan.agent.data.LocalCache
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
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
    fun provideTokenProvider(tokenCache: AuthTokenCache): () -> String = tokenCache::get

    // Ktor client 是单例：baseUrl 不再固化在构造期，而是每次请求经 baseUrlProvider 实时取，
    // 天然支持登录后/切服务器变更，省掉了原 refreshApi 重建 client 的逻辑。
    @Provides
    @Singleton
    fun provideApiService(
        serverUrlCache: ServerUrlCache,
        tokenProvider: () -> String,
    ): EthanApiService =
        NetworkFactory.createApiService(serverUrlCache::get, tokenProvider)

    @Provides
    @Singleton
    fun provideSseClient(
        serverUrlCache: ServerUrlCache,
        tokenProvider: () -> String,
    ): ChatSseClient =
        NetworkFactory.createSseClient(serverUrlCache::get, tokenProvider)

    @Provides
    @Singleton
    fun provideLocalCache(@ApplicationContext context: Context): LocalCache = LocalCache(context)

    @Provides
    @Singleton
    fun provideRepository(
        configStore: AppConfigStore,
        api: EthanApiService,
        sseClient: ChatSseClient,
        serverUrlCache: ServerUrlCache,
        localCache: LocalCache,
    ): EthanRepository = EthanRepository(configStore, api, sseClient, serverUrlCache, localCache)
}
