package com.ethan.agent.core.network

import com.ethan.agent.core.model.ServerUrlUtils
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.util.concurrent.TimeUnit

object NetworkFactory {
    val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        encodeDefaults = true
        explicitNulls = false
    }

    fun createOkHttpClient(tokenProvider: () -> String): OkHttpClient {
        return OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                val token = tokenProvider()
                val request = chain.request().newBuilder().apply {
                    if (token.isNotBlank()) {
                        header("Authorization", "Bearer $token")
                    }
                    header("Content-Type", "application/json")
                }.build()
                chain.proceed(request)
            }
            .apply {
                if (BuildConfig.DEBUG) {
                    addInterceptor(
                        HttpLoggingInterceptor().apply {
                            level = HttpLoggingInterceptor.Level.BODY
                        },
                    )
                }
            }
            .build()
    }

    fun createRetrofit(baseUrl: String, client: OkHttpClient): Retrofit {
        val contentType = "application/json".toMediaType()
        return Retrofit.Builder()
            .baseUrl(ServerUrlUtils.toRetrofitBaseUrl(baseUrl))
            .client(client)
            .addConverterFactory(json.asConverterFactory(contentType))
            .build()
    }

    fun createApiService(baseUrl: String, tokenProvider: () -> String): EthanApiService {
        val client = createOkHttpClient(tokenProvider)
        return createRetrofit(baseUrl, client).create(EthanApiService::class.java)
    }

    fun createSseClient(tokenProvider: () -> String): ChatSseClient {
        return ChatSseClient(createOkHttpClient(tokenProvider), json)
    }
}
