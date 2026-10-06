package com.ethan.agent.core.model

import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * `last_read_at`（未读水位）的 JSON 解析契约。
 *
 * 移动端红点判定是 `updated_at > last_read_at`，所以这个字段的解析是命门：
 * - 服务端返回浮点秒（SQLite REAL）→ 必须容忍 int/double/字符串数字
 * - **旧后端不返回该字段 → null**，调用方按「已读」兜底（不能默认为 0，否则满屏假红点）
 *
 * 两种「没有值」的语义必须区分：`null` = 后端不支持 / `0` = 明确没读过（算未读）。
 */
class SessionInfoJsonTest {

    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun parsesFloatTimestamp() {
        val s = json.decodeFromString(
            SessionInfo.serializer(),
            """{"id":"a","title":"t","model":"m","updated_at":1759712345.987,"last_read_at":1759712345.0}""",
        )
        assertEquals(1759712345, s.updatedAt)
        assertEquals(1759712345, s.lastReadAt)
    }

    @Test
    fun parsesIntegerTimestamps() {
        val s = json.decodeFromString(
            SessionInfo.serializer(),
            """{"id":"a","title":"t","model":"m","updated_at":200,"last_read_at":100}""",
        )
        assertEquals(200, s.updatedAt)
        assertEquals(100, s.lastReadAt)
    }

    @Test
    fun zeroWatermarkStaysZero() {
        // 服务端明确回 0 = 从未读过 → 保留 0（算未读），不能和「字段缺失」混为一谈
        val s = json.decodeFromString(
            SessionInfo.serializer(),
            """{"id":"a","title":"t","model":"m","updated_at":100,"last_read_at":0}""",
        )
        assertEquals(0, s.lastReadAt)
    }

    @Test
    fun missingFieldMeansLegacyServer() {
        val s = json.decodeFromString(
            SessionInfo.serializer(),
            """{"id":"a","title":"t","model":"m","updated_at":1759712345.5}""",
        )
        assertNull(s.lastReadAt, "旧后端没有该字段 → null（按已读兜底），不能变成 0")
    }

    @Test
    fun explicitJsonNullIsAlsoLegacy() {
        val s = json.decodeFromString(
            SessionInfo.serializer(),
            """{"id":"a","title":"t","model":"m","updated_at":100,"last_read_at":null}""",
        )
        assertNull(s.lastReadAt)
    }

    @Test
    fun otherEndpointsFieldsStillParse() {
        // /poll 的会话行没有 snippet；/sessions 的有。两个端点都要能解析。
        val poll = json.decodeFromString(
            SessionInfo.serializer(),
            """{"id":"a","title":"t","model":"m","updated_at":300,"source":"schedule","mode":"","pinned_at":0,"last_read_at":100}""",
        )
        assertEquals("schedule", poll.source)
        assertNull(poll.snippet)
    }
}
