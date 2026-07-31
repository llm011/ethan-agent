package com.ethan.agent.core.network

import com.ethan.agent.core.model.ChatRequest
import com.ethan.agent.core.model.ChatStreamEvent
import com.ethan.agent.core.model.ServerUrlUtils
import io.ktor.client.HttpClient
import io.ktor.client.request.accept
import io.ktor.client.request.prepareGet
import io.ktor.client.request.preparePost
import io.ktor.client.request.setBody
import io.ktor.client.statement.HttpResponse
import io.ktor.client.statement.bodyAsChannel
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.http.isSuccess
import io.ktor.utils.io.ByteReadChannel
import io.ktor.utils.io.readUTF8Line
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.serialization.json.Json

/**
 * Ktor 版 SSE 客户端（替换原手写 OkHttp BufferedReader 实现）。
 *
 * 手动逐行读 event-stream 而非用 Ktor SSE 插件：
 *   - 需要保留 204（无活跃 run）静默返回空流的语义
 *   - 逐行 `data:` 解析逻辑与 Web 客户端一致，跨平台行为可控
 */
class ChatSseClient(
    private val client: HttpClient,
    private val baseUrlProvider: () -> String,
    private val json: Json,
) {
    private fun origin(): String {
        // SSE 端点直接挂在 /api 下，与 EthanApiService 同源
        return ServerUrlUtils.toApiBaseUrl(baseUrlProvider()).trimEnd('/')
    }

    fun streamChat(request: ChatRequest): Flow<ChatStreamEvent> = flow {
        val bodyJson = json.encodeToString(ChatRequest.serializer(), request)
        client.preparePost("${origin()}/chat") {
            contentType(ContentType.Application.Json)
            accept(ContentType.parse("text/event-stream"))
            setBody(bodyJson)
        }.execute { response ->
            if (!response.status.isSuccess()) {
                throw ApiException(response.status.value, "Chat failed: ${response.status.value}")
            }
            emitSseEvents(response.bodyAsChannel()) { emit(it) }
        }
    }

    /**
     * 重连一个仍在进行的生成：GET /chat/{sessionId}/stream。
     *   - 200：SSE 流（先回放缓冲，再实时推送）
     *   - 204：无活跃 run，返回空流，调用方走普通 getSession 拿落库结果
     */
    fun resumeStream(sessionId: String): Flow<ChatStreamEvent> = flow {
        client.prepareGet("${origin()}/chat/$sessionId/stream") {
            accept(ContentType.parse("text/event-stream"))
        }.execute { response ->
            if (response.status == HttpStatusCode.NoContent) {
                return@execute
            }
            if (!response.status.isSuccess()) {
                throw ApiException(response.status.value, "Resume stream failed: ${response.status.value}")
            }
            emitSseEvents(response.bodyAsChannel()) { emit(it) }
        }
    }

    /** 逐行读 event-stream，解析 `data:` 负载并通过 emitter 发射。 */
    private suspend inline fun emitSseEvents(
        channel: ByteReadChannel,
        crossinline emitter: suspend (ChatStreamEvent) -> Unit,
    ) {
        while (true) {
            val line = channel.readUTF8Line() ?: break
            if (line.startsWith("data: ")) {
                val payload = line.removePrefix("data: ").trim()
                if (payload.isNotEmpty()) {
                    try {
                        emitter(json.decodeFromString(ChatStreamEvent.serializer(), payload))
                    } catch (_: Exception) {
                        // skip malformed chunks
                    }
                }
            }
        }
    }
}

class ApiException(val code: Int, override val message: String) : Exception(message)
