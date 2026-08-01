package com.ethan.agent.core.network

import io.ktor.client.HttpClient
import io.ktor.client.engine.HttpClientEngine
import io.ktor.client.plugins.HttpResponseValidator
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.ResponseException
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.plugins.defaultRequest
import io.ktor.client.plugins.logging.LogLevel
import io.ktor.client.plugins.logging.Logging
import io.ktor.client.request.header
import io.ktor.http.HttpHeaders
import io.ktor.serialization.kotlinx.json.json
import kotlinx.serialization.json.Json

/**
 * 平台提供的 Ktor engine：Android=OkHttp，iOS=Darwin。
 * 用 expect/actual 隔离唯一的平台差异，其余配置（超时/JSON/日志）全在 commonMain 共享。
 */
expect fun httpClientEngine(): HttpClientEngine

/** 是否 debug 构建，控制是否打印 body 级日志。平台各自提供。 */
expect fun isDebugBuild(): Boolean

object NetworkJson {
    val instance: Json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        encodeDefaults = true
        explicitNulls = false
    }
}

object NetworkFactory {
    val json: Json get() = NetworkJson.instance

    /**
     * 创建共享 HttpClient：注入鉴权头 + JSON 反序列化 + 超时 + 可选日志。
     * tokenProvider 每次请求实时取 token，兼容登录后 token 变化。
     */
    fun createHttpClient(tokenProvider: () -> String): HttpClient {
        return HttpClient(httpClientEngine()) {
            expectSuccess = true

            install(ContentNegotiation) {
                json(NetworkJson.instance)
            }

            install(HttpTimeout) {
                connectTimeoutMillis = 30_000
                requestTimeoutMillis = 120_000
                socketTimeoutMillis = 120_000
            }

            if (isDebugBuild()) {
                install(Logging) {
                    level = LogLevel.BODY
                }
            }

            // 把 Ktor 的 4xx/5xx 异常统一映射成领域内 ApiException(code, message)，
            // 让上层只需处理一种异常类型（替换原 retrofit2.HttpException）。
            HttpResponseValidator {
                handleResponseExceptionWithRequest { cause, _ ->
                    if (cause is ResponseException) {
                        throw ApiException(
                            cause.response.status.value,
                            cause.message ?: "HTTP ${cause.response.status.value}",
                        )
                    }
                }
            }

            // 每个请求实时注入 Authorization（token 可能在登录后变化）
            defaultRequest {
                val token = tokenProvider()
                if (token.isNotBlank()) {
                    header(HttpHeaders.Authorization, "Bearer $token")
                }
            }
        }
    }

    fun createApiService(baseUrlProvider: () -> String, tokenProvider: () -> String): EthanApiService {
        return EthanApiService(createHttpClient(tokenProvider), baseUrlProvider)
    }

    fun createSseClient(baseUrlProvider: () -> String, tokenProvider: () -> String): ChatSseClient {
        return ChatSseClient(createHttpClient(tokenProvider), baseUrlProvider, NetworkJson.instance)
    }
}
