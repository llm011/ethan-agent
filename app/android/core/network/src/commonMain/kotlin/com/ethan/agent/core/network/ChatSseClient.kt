package com.ethan.agent.core.network

import com.ethan.agent.core.model.ChatRequest
import com.ethan.agent.core.model.ChatStreamEvent
import com.ethan.agent.core.model.ServerUrlUtils
import io.ktor.client.HttpClient
import io.ktor.client.request.accept
import io.ktor.client.request.prepareGet
import io.ktor.client.request.preparePost
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsChannel
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.http.isSuccess
import io.ktor.utils.io.ByteReadChannel
import io.ktor.utils.io.readUTF8Line
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.serialization.json.Json
import kotlin.math.min

/**
 * Ktor 版 SSE 客户端（替换原手写 OkHttp BufferedReader 实现）。
 *
 * 手动逐行读 event-stream 而非用 Ktor SSE 插件：
 *   - 需要保留 204（无活跃 run）静默返回空流的语义
 *   - 逐行 `data:` 解析逻辑与 Web 客户端一致，跨平台行为可控
 *
 * **断线重连**（见 [RetryPolicy] 与 [ResilientSse]）：长连接会在服务端重启、移动网络
 * 切换（Wi-Fi ↔ 蜂窝）、以及手机息屏 / 进程被挂起时断开。没有自动重连时，断点之后
 * 拉起来的流就是一条干流 —— 调用方看到的是「App 一会儿自己变成离线」，而且不点「重连」
 * 永远回不来。恢复端点（`GET /chat/{id}/stream`）本身就是幂等的「从头回放」语义，
 * 所以重连是安全的：重发一次 resume 就能把 run 接回来。
 */
class ChatSseClient(
    private val client: HttpClient,
    private val baseUrlProvider: () -> String,
    private val json: Json,
    /** 断流后的重连策略。默认指数退避 1s/2s/4s…，封顶 30s。 */
    private val retryPolicy: RetryPolicy = RetryPolicy(),
) {
    private fun origin(): String {
        // SSE 端点直接挂在 /api 下，与 EthanApiService 同源
        return ServerUrlUtils.toApiBaseUrl(baseUrlProvider()).trimEnd('/')
    }

    /**
     * 对可恢复的流做**同一流内**重连：流已产出过的事件不会重发，调用方无需感知重连。
     *
     * 只对 [retryPolicy] 判定为可重试、且已经产出过至少一个事件的流生效 ——
     * 一个还没出头就失败的流更像「服务器没起来 / 地址不对」，交给调用方报错更诚实，
     * 也避免把打错地址的用户锁在一个永远重试的循环里。首个事件之后的重试由
     * [retryAttempts] 计数并封顶，与调用方自己的 resume 重连是两回事
     * （那是「跨流」重连，应用层有自己的退避）。
     *
     * @param retryAttempts 剩余自动重试次数；0 表示只跑一次、失败直接抛给调用方。
     *   非幂等请求（[streamChat]）必须传 0，理由见那里的说明。
     * @param hasEmittedContent 建立连接前该流的进度是否已经非空（例如已渲染的正文）。
     *   非空说明这是一个「正在接续」的流，首次连接失败也值得重试。
     */
    private fun <T> resilientStream(
        retryAttempts: Int,
        hasEmittedContent: Boolean,
        block: suspend (emit: suspend (T) -> Unit) -> Unit,
    ): Flow<T> = flow {
        var attempt = 0
        var emitted = hasEmittedContent
        while (true) {
            try {
                block { value ->
                    emitted = true
                    emit(value)
                }
                return@flow
            } catch (e: Throwable) {
                // 取消是正常控制流（用户点了停止 / 页面销毁），必须原样抛出去，
                // 否则会被当成一次「断线」而重连一个已经被取消的流。
                if (e is CancellationException) throw e
                if (!retryPolicy.isRetryable(e)) throw e
                if (!emitted) throw e
                if (attempt >= retryAttempts) throw e
                delay(retryPolicy.delayMillis(attempt))
                attempt += 1
            }
        }
    }

    /**
     * 发起一轮生成：POST /chat，响应是一条 SSE 流。
     *
     * **刻意不做自动重连**（[retryAttempts] 传 0），因为 POST /chat 不是幂等的：它的
     * 作用是「创建并运行一轮生成」。如果响应在途中丢了（服务端其实已经收到并开始跑），
     * 重发就会开起**第二轮**生成 —— 用户看到两条重复回复、工具被重复执行、token 被
     * 重复计费。这类「请求可能已生效」的失败只能由上层用会话状态去核对（上层是
     * 先 resumeStream 探一下有没有活跃 run，再决定要不要重发），不能在传输层盲重试。
     *
     * 需要自动重连的是 [resumeStream] —— 那个端点是幂等的「从头回放」。
     */
    fun streamChat(
        request: ChatRequest,
        retryAttempts: Int = 0,
    ): Flow<ChatStreamEvent> = resilientStream(
        retryAttempts = retryAttempts,
        hasEmittedContent = false,
    ) { emit ->
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
     *
     * 这个端点天然幂等（每次都是「从头回放 + 继续推」），因此断流重试是安全的。
     *
     * @param hasProgress 调用方此刻是否已经渲染过内容。断点续传场景下它告诉本方法
     *   「这是一个进行中的 run，不是一条还没接上的空流」—— 首连失败也该重试。
     */
    fun resumeStream(
        sessionId: String,
        hasProgress: Boolean = false,
        retryAttempts: Int = RetryPolicy.DEFAULT_STREAM_RETRIES,
    ): Flow<ChatStreamEvent> = resilientStream(
        retryAttempts = retryAttempts,
        hasEmittedContent = hasProgress,
    ) { emit ->
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

    /**
     * 单次健康检查（`GET /health`）。用于「切回前台主动探活」：
     * 长连接被系统挂起后我们拿不到任何断线通知，只能主动问一次。
     */
    suspend fun healthy(): Boolean = try {
        val response = client.prepareGet("${origin()}/health").execute()
        response.status.isSuccess()
    } catch (e: CancellationException) {
        throw e
    } catch (_: Throwable) {
        false
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
                    } catch (e: Exception) {
                        // 完整 SSE chunk 含用户消息/工具参数等敏感内容，println 在 release 也会
                        // 打到 logcat System.out——仅 debug 构建输出且截断到 200 字符
                        if (isDebugBuild()) {
                            val preview = if (payload.length > 200) payload.take(200) + "…" else payload
                            println("[SSE] Failed to parse chunk: ${e.message} | payload=$preview")
                        }
                    }
                }
            }
        }
    }
}

class ApiException(val code: Int, override val message: String) : Exception(message)

/**
 * 断线重连策略：指数退避 + 上限。
 *
 * 为什么要有上限：服务端真的挂掉时，无上限的退避会按「每秒一次」的节奏无限打请求，
 * 既耗电也会在服务恢复的瞬间制造惊群。到达 [maxDelayMs] 后保持该间隔重试，
 * 由调用方的重试次数上限（或用户手动重连）来决定何时放弃。
 */
data class RetryPolicy(
    val initialDelayMs: Long = 1_000,
    val maxDelayMs: Long = 30_000,
    /** 退避倍率：delay = initial * multiplier^attempt，再被 maxDelayMs 截断。 */
    val multiplier: Int = 2,
) {
    /** 第 [attempt] 次（0 起）重试前应等待的毫秒数。 */
    fun delayMillis(attempt: Int): Long {
        var delay = initialDelayMs
        repeat(attempt) { delay = min(delay * multiplier, maxDelayMs) }
        return min(delay, maxDelayMs)
    }

    /**
     * 哪些失败值得重连。
     *
     * 判定的是「这条连接是不是被迫断的」而不是「服务端返回了几号错误」：
     *   - [ApiException] 是**拿到了** HTTP 响应 —— 服务端在正常工作，4xx/5xx 都是
     *     业务语义（401 该重新登录、404 该放弃），重连只会把同一个错误再拿一遍。
     *     唯一例外是 5xx / 408 / 429：这些是「服务端自己的临时状态」，值得退避重试。
     *   - 其余（IO 超时、连接被重置、DNS 失败、channel 关闭…）都是断线，重试。
     */
    fun isRetryable(e: Throwable): Boolean = when (e) {
        is ApiException -> e.code >= 500 || e.code == 408 || e.code == 429
        else -> true
    }

    companion object {
        /**
         * 单条流内部的重连次数。与调用方（ViewModel）自己的「跨流 resume 重连」叠加：
         * 单条流最多 4 次连续重连，全部失败才把错误交给上层，由上层再走它自己的退避。
         */
        const val DEFAULT_STREAM_RETRIES = 4
    }
}
