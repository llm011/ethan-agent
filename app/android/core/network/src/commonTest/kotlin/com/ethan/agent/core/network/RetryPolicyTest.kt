package com.ethan.agent.core.network

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * `RetryPolicy` 的退避与可重试判定单测。
 *
 * 背景：移动端断流自愈完全建立在这个策略上（`ChatSseClient.resilientStream` 用它的
 * delay 退避、用它的 isRetryable 决定要不要重连）。策略算错会有两种后果：
 *  - 退避涨太慢 → 服务端挂掉时高频打请求，耗电并在恢复瞬间惊群；
 *  - 可重试判定太宽 → 对 4xx（如 401 token 过期、404 会话不存在）反复重试，
 *    用户永远看不到真正的错误，界面卡在转圈。
 * 所以这两件事都在纯逻辑层钉住。
 */
class RetryPolicyTest {

    private val policy = RetryPolicy()

    @Test
    fun `退避按 1s 2s 4s 倍增`() {
        assertEquals(1_000L, policy.delayMillis(0))
        assertEquals(2_000L, policy.delayMillis(1))
        assertEquals(4_000L, policy.delayMillis(2))
        assertEquals(8_000L, policy.delayMillis(3))
    }

    @Test
    fun `退避封顶 30s 且不再增长`() {
        // 1,2,4,8,16 → 第 5 次本该是 32s，被截到 30s
        assertEquals(30_000L, policy.delayMillis(5))
        // 之后一直保持在封顶值，不会因为 attempt 变大而溢出或继续翻倍
        assertEquals(30_000L, policy.delayMillis(9))
        assertEquals(30_000L, policy.delayMillis(50))
        (0..60).forEach { attempt ->
            assertTrue(
                policy.delayMillis(attempt) <= 30_000L,
                "attempt=$attempt 超过了 maxDelayMs: ${policy.delayMillis(attempt)}",
            )
        }
    }

    @Test
    fun `服务端临时状态值得重试`() {
        // 5xx / 408 / 429 是服务端自己的临时状态，退避后重试有意义
        assertTrue(policy.isRetryable(ApiException(500, "boom")))
        assertTrue(policy.isRetryable(ApiException(502, "bad gateway")))
        assertTrue(policy.isRetryable(ApiException(503, "unavailable")))
        assertTrue(policy.isRetryable(ApiException(408, "timeout")))
        assertTrue(policy.isRetryable(ApiException(429, "too many requests")))
    }

    @Test
    fun `拿到了响应说明服务端是活的_业务错误不该重试`() {
        // 这几类重试只会把同一个错误再拿一遍，且会掩盖真正的提示（该重新登录 / 该放弃）
        assertFalse(policy.isRetryable(ApiException(400, "bad request")))
        assertFalse(policy.isRetryable(ApiException(401, "unauthorized")))
        assertFalse(policy.isRetryable(ApiException(403, "forbidden")))
        assertFalse(policy.isRetryable(ApiException(404, "not found")))
        assertFalse(policy.isRetryable(ApiException(409, "conflict")))
    }

    @Test
    fun `非 ApiException 的失败一律视为断线_可重试`() {
        // 拿不到 HTTP 响应 = 连接被拒 / 超时 / DNS 挂了 / channel 被关闭，
        // 这些正是「切后台后 socket 被回收」的典型表现，必须重试。
        // 用普通异常代表（commonMain 里没有 java.net 那套异常类型）。
        assertTrue(policy.isRetryable(RuntimeException("connection reset")))
        assertTrue(policy.isRetryable(IllegalStateException("channel closed")))
    }

    @Test
    fun `默认单条流最多重试 4 次`() {
        // 这个值同时是「流内自愈」的上限：超过后把错误交给上层，由上层走自己的跨流退避。
        assertEquals(4, RetryPolicy.DEFAULT_STREAM_RETRIES)
    }
}
