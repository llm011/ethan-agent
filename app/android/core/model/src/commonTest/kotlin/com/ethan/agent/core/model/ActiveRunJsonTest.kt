package com.ethan.agent.core.model

import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * 「进行中会话」相关字段的 JSON 解析契约（ETHA-37）：
 *
 * - `SessionDetail.active_run`：切进正在生成的会话时，前端据此立即呈现进行中状态并接流。
 *   **旧后端不返回该字段 → false**（按「没有活跃 run」兜底），不能因为字段缺失抛异常。
 * - `PollData.active_sessions`：会话列表「生成中」指示器的数据源。旧后端缺失 → 空集合。
 * - `Message.status`：历史快照里 generating 的 assistant 消息要渲染成「还在写」的气泡。
 */
class ActiveRunJsonTest {

    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun sessionDetailParsesActiveRunTrue() {
        val d = json.decodeFromString(
            SessionDetail.serializer(),
            """{"id":"s1","title":"t","model":"m","active_run":true,"messages":[]}""",
        )
        assertTrue(d.activeRun)
    }

    @Test
    fun sessionDetailDefaultsToFalseWhenFieldMissing() {
        val d = json.decodeFromString(
            SessionDetail.serializer(),
            """{"id":"s1","title":"t","model":"m","messages":[]}""",
        )
        assertFalse(d.activeRun, "旧后端没有 active_run → false，不能解析失败")
    }

    @Test
    fun pollDataParsesActiveSessions() {
        val p = json.decodeFromString(
            PollData.serializer(),
            """{"sessions":[{"id":"a","title":"t","model":"m","updated_at":100}],"active_sessions":["a","b"]}""",
        )
        assertEquals(listOf("a", "b"), p.activeSessions)
    }

    @Test
    fun pollDataDefaultsToEmptyWhenFieldMissing() {
        val p = json.decodeFromString(
            PollData.serializer(),
            """{"sessions":[]}""",
        )
        assertTrue(p.activeSessions.isEmpty())
    }

    @Test
    fun messageDefaultsStatusToCompleted() {
        val m = json.decodeFromString(
            Message.serializer(),
            """{"role":"assistant","content":"hi"}""",
        )
        assertEquals("completed", m.status)
    }

    @Test
    fun messageParsesGeneratingStatus() {
        val m = json.decodeFromString(
            Message.serializer(),
            """{"role":"assistant","content":"partial","status":"generating"}""",
        )
        assertEquals("generating", m.status)
    }
}
