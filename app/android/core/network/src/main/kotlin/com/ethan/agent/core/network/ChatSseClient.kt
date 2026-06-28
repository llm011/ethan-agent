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

        val reader = BufferedReader(InputStreamReader(response.body?.byteStream() ?: return@flow))
        var buffer = ""
        try {
            var line: String?
            while (reader.readLine().also { line = it } != null) {
                val current = line ?: continue
                if (current.startsWith("data: ")) {
                    val payload = current.removePrefix("data: ").trim()
                    if (payload.isNotEmpty()) {
                        try {
                            emit(json.decodeFromString(ChatStreamEvent.serializer(), payload))
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
    }.flowOn(Dispatchers.IO)
}

class ApiException(val code: Int, override val message: String) : Exception(message)
