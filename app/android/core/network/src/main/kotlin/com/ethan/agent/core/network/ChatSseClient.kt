package com.ethan.agent.core.network

import com.ethan.agent.core.model.ChatRequest
import com.ethan.agent.core.model.ChatStreamEvent
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.BufferedReader
import java.io.InputStreamReader

class ChatSseClient(
    private val okHttpClient: OkHttpClient,
    private val json: Json,
) {
    fun streamChat(
        baseUrl: String,
        token: String,
        request: ChatRequest,
    ): Flow<ChatStreamEvent> = flow {
        val bodyJson = json.encodeToString(ChatRequest.serializer(), request)
        val httpRequest = Request.Builder()
            .url("${baseUrl.trimEnd('/')}/chat")
            .post(bodyJson.toRequestBody("application/json".toMediaType()))
            .header("Accept", "text/event-stream")
            .apply {
                if (token.isNotBlank()) header("Authorization", "Bearer $token")
            }
            .build()

        val response = okHttpClient.newCall(httpRequest).execute()
        if (!response.isSuccessful) {
            throw ApiException(response.code, "Chat failed: ${response.code}")
        }

        emitSseEvents(response) { emit(it) }
    }.flowOn(Dispatchers.IO)

    /**
     * 重连一个仍在进行的生成：GET /chat/{sessionId}/stream。
     *
     * 后端行为：
     *   - 200：返回 SSE 流（先回放缓冲，再继续实时推送）
     *   - 204：无活跃 run（已结束或从未开始），返回空流，调用方应走普通 fetchSession 拿落库结果
     *
     * 实现要点：复用 streamChat 的 SSE 解析逻辑，确保事件格式一致。
     */
    fun resumeStream(
        baseUrl: String,
        token: String,
        sessionId: String,
    ): Flow<ChatStreamEvent> = flow {
        val httpRequest = Request.Builder()
            .url("${baseUrl.trimEnd('/')}/chat/$sessionId/stream")
            .get()
            .header("Accept", "text/event-stream")
            .apply {
                if (token.isNotBlank()) header("Authorization", "Bearer $token")
            }
            .build()

        val response = okHttpClient.newCall(httpRequest).execute()
        // 204 = 无活跃 run，静默返回空流（与 Web 客户端行为一致）
        if (response.code == 204) {
            response.close()
            return@flow
        }
        if (!response.isSuccessful) {
            throw ApiException(response.code, "Resume stream failed: ${response.code}")
        }

        emitSseEvents(response) { emit(it) }
    }.flowOn(Dispatchers.IO)

    /** 共享 SSE 解析：读取 response body 的 event-stream，逐行解析 data: 并通过 emitter 回调发射。 */
    private suspend inline fun emitSseEvents(
        response: Response,
        crossinline emitter: suspend (ChatStreamEvent) -> Unit,
    ) {
        val body = response.body ?: run { response.close(); return }
        val reader = BufferedReader(InputStreamReader(body.byteStream()))
        try {
            var line: String?
            while (reader.readLine().also { line = it } != null) {
                val current = line ?: continue
                if (current.startsWith("data: ")) {
                    val payload = current.removePrefix("data: ").trim()
                    if (payload.isNotEmpty()) {
                        try {
                            emitter(json.decodeFromString(ChatStreamEvent.serializer(), payload))
                        } catch (_: Exception) {
                            // skip malformed chunks
                        }
                    }
                }
            }
        } finally {
            reader.close()
            response.close()
        }
    }
}

class ApiException(val code: Int, override val message: String) : Exception(message)
