package com.ethan.agent.core.model

import kotlinx.datetime.Clock
import kotlinx.datetime.Instant
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime

data class ToolEndedAtDisplay(
    val label: String,
    val full: String,
)

/**
 * 工具完成时刻的展示文本，对齐 Web/Desktop `tool-timeline.tsx` 的 `formatEndedAt()`：
 * - `epochSec == null || epochSec <= 0` → `null`（历史消息无此字段时不显示，不误导）
 * - 当天 → `label = "HH:mm"`
 * - 跨天 → `label = "MM-dd HH:mm"`
 * - `full` → `"yyyy-MM-dd HH:mm:ss"`（用于详情卡片展示完整时间）
 */
fun formatToolEndedAt(
    epochSec: Long?,
    nowEpochSec: Long,
    timeZone: TimeZone,
): ToolEndedAtDisplay? {
    if (epochSec == null || epochSec <= 0L) return null
    val dt = Instant.fromEpochSeconds(epochSec).toLocalDateTime(timeZone)
    val now = Instant.fromEpochSeconds(nowEpochSec).toLocalDateTime(timeZone)
    val month = dt.monthNumber.toString().padStart(2, '0')
    val day = dt.dayOfMonth.toString().padStart(2, '0')
    val hh = dt.hour.toString().padStart(2, '0')
    val mm = dt.minute.toString().padStart(2, '0')
    val ss = dt.second.toString().padStart(2, '0')
    val hm = "$hh:$mm"
    val sameDay = dt.year == now.year && dt.monthNumber == now.monthNumber && dt.dayOfMonth == now.dayOfMonth
    val label = if (sameDay) hm else "$month-$day $hm"
    val full = "${dt.year}-$month-$day $hm:$ss"
    return ToolEndedAtDisplay(label = label, full = full)
}

/** 供 `:app` 等未直接依赖 `kotlinx-datetime` 的模块使用的默认时区重载。 */
fun formatToolEndedAt(epochSec: Long?): ToolEndedAtDisplay? =
    formatToolEndedAt(
        epochSec = epochSec,
        nowEpochSec = Clock.System.now().epochSeconds,
        timeZone = TimeZone.currentSystemDefault(),
    )
