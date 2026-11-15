package com.ethan.agent.core.model

import kotlinx.datetime.TimeZone
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * 工具步骤 `ended_at` 的解析与展示格式化契约：
 * - 历史消息 / 旧后端缺少 `ended_at` → null，不显示（避免编造假时间）
 * - 服务端返回浮点 epoch 秒（SQLite REAL / time.time()）→ 兼容 int/double/null
 * - 当天仅显示 `HH:mm`，跨天带 `MM-dd HH:mm`，详情提供完整 `yyyy-MM-dd HH:mm:ss`
 */
class ToolEndedAtTest {

    private val json = Json { ignoreUnknownKeys = true }
    private val tz = TimeZone.of("UTC+8")

    @Test
    fun parsesFloatAndMissingEndedAt() {
        val step = json.decodeFromString(
            ToolStep.serializer(),
            """{"tool":"shell","state":"done","duration_ms":120,"ended_at":1763218995.678}""",
        )
        assertEquals(1763218995L, step.endedAt)

        val legacy = json.decodeFromString(
            ToolStep.serializer(),
            """{"tool":"shell","state":"done","duration_ms":120}""",
        )
        assertNull(legacy.endedAt)

        val event = json.decodeFromString(
            ChatStreamEvent.serializer(),
            """{"tool":"shell","state":"done","ended_at":1763219000.25}""",
        )
        assertEquals(1763219000L, event.endedAt)
    }

    @Test
    fun formatSameDayShowsHourMinute() {
        // 2025-11-15 23:03:15 UTC+8 = 1763218995
        // 2025-11-15 23:30:00 UTC+8 = 1763220600
        val out = formatToolEndedAt(
            epochSec = 1763218995L,
            nowEpochSec = 1763220600L,
            timeZone = tz,
        )
        assertEquals("23:03", out?.label)
        assertEquals("2025-11-15 23:03:15", out?.full)
    }

    @Test
    fun formatDifferentDayShowsMonthDay() {
        // 2025-11-15 23:03:15 UTC+8 = 1763218995
        // 2025-11-16 00:05:00 UTC+8 = 1763222700
        val out = formatToolEndedAt(
            epochSec = 1763218995L,
            nowEpochSec = 1763222700L,
            timeZone = tz,
        )
        assertEquals("11-15 23:03", out?.label)
        assertEquals("2025-11-15 23:03:15", out?.full)
    }

    @Test
    fun formatNullOrZeroReturnsNull() {
        assertNull(formatToolEndedAt(null, nowEpochSec = 1763220600L, timeZone = tz))
        assertNull(formatToolEndedAt(0L, nowEpochSec = 1763220600L, timeZone = tz))
        assertNull(formatToolEndedAt(-10L, nowEpochSec = 1763220600L, timeZone = tz))
    }
}
