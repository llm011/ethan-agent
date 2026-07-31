package com.ethan.agent.core.network

import io.ktor.client.request.HttpRequestBuilder
import io.ktor.client.request.setBody
import io.ktor.http.ContentType
import io.ktor.http.contentType

/**
 * 设置 JSON 请求体：显式声明 Content-Type 并交给 ContentNegotiation 序列化。
 * 等价于原 Retrofit 拦截器里固定加的 `Content-Type: application/json`。
 */
inline fun <reified T> HttpRequestBuilder.jsonBody(body: T) {
    contentType(ContentType.Application.Json)
    setBody(body)
}
