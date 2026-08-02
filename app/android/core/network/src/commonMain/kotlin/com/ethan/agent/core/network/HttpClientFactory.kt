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
     *
     * @param streaming 为 SSE 流式 client 置 true：禁用 requestTimeout（否则会强制
     *                  中断 >120s 的长生成，是原 OkHttp 只设 readTimeout 的回归），
     *                  并跳过 BODY 级日志（Logging 会 buffer/干扰流式 body 读取）。
     *                  socketTimeout 保留——它只卡「无数据读取」场景，持续有数据流不触发。
     */
    fun createHttpClient(tokenProvider: () -> String, streaming: Boolean = false): HttpClient {
        return HttpClient(httpClientEngine()) {
            expectSuccess = true

            install(ContentNegotiation) {
                json(NetworkJson.instance)
            }

            install(HttpTimeout) {
                connectTimeoutMillis = 30_000
                // requestTimeout 限制整个请求（含流式 body）：流式场景必须禁用，否则
                // 长生成会被 HttpRequestTimeoutException 中断。0 表示不超时。
                requestTimeoutMillis = if (streaming) 0L else 120_000L
                socketTimeoutMillis = 120_000
            }

            if (!streaming && isDebugBuild()) {
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
        return ChatSseClient(createHttpClient(tokenProvider, streaming = true), baseUrlProvider, NetworkJson.instance)
    }
}
