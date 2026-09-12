package com.ethan.agent.core.model

import kotlin.time.Duration
import kotlinx.datetime.Clock
import kotlinx.datetime.Instant
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime

/**
 * 定时任务的展示格式化 —— 照搬 Web/Desktop 共享的
 * `packages/shared/src/lib/utils.ts` 的 `formatTrigger` / `formatNextRun`。
 *
 * 三端必须一致：同一个 cron 在 Web 上显示「每天 09:00」，Android 上却显示
 * `cron[month='*', day='*', hour='9', minute='0']` 这种原文，用户会以为两端不是同一个产品。
 *
 * 纯函数、无平台依赖，便于单测。
 */
object ScheduleFormat {

    private val INTERVAL_RE = Regex("""interval\[(\d+):(\d+):(\d+)]""")
    private val CRON_RE = Regex("""cron\[(.+)]""")
    private val CRON_FIELD_RE = Regex("""(\w+)='([^']+)'""")

    private val DAY_NAMES = mapOf(
        "0" to "周日", "1" to "周一", "2" to "周二", "3" to "周三",
        "4" to "周四", "5" to "周五", "6" to "周六",
        "mon" to "周一", "tue" to "周二", "wed" to "周三", "thu" to "周四",
        "fri" to "周五", "sat" to "周六", "sun" to "周日",
    )

    private fun isWild(v: String?): Boolean = v.isNullOrBlank() || v == "*"

    private fun pad2(v: String): String = if (v.length >= 2) v else "0".repeat(2 - v.length) + v

    /**
     * 小时字段可能是单值、多值（`9,21`）或步长（星号斜杠 N）。
     * 多值展开成「09:00、21:00」，避免拼出 `9,21:00` 这种读不通的结果。
     */
    private fun formatHours(hour: String, minute: String): String {
        if (hour.contains(",")) {
            return hour.split(",").joinToString("、") { padTime(it.trim(), minute) }
        }
        return padTime(hour, minute)
    }

    /** `cron[hour='9', minute='0']` → `09:00`；通配的小时显示 `?`，通配的分钟显示 `00`。 */
    private fun padTime(hour: String, minute: String): String {
        val hh = if (isWild(hour)) "?" else pad2(hour)
        val mm = if (isWild(minute)) "00" else pad2(minute)
        return "$hh:$mm"
    }

    /**
     * 把后端返回的 trigger 原文转成人类可读的中文描述。
     *
     * 支持两种形式（与后端 `scheduler` 一致）：
     * - `interval[H:MM:SS]` → 「每 N 分钟 / 每 N 小时 / 每 N 天」
     * - `cron[key='val', ...]` → 「每天 09:00」「每 周一、周三 10:30」「每月 15 日 08:00」
     *
     * 无法识别时原样返回，让用户至少看到真实配置而不是空白。
     */
    fun formatTrigger(trigger: String): String {
        INTERVAL_RE.find(trigger)?.let { m ->
            val h = m.groupValues[1].toIntOrNull() ?: 0
            val min = m.groupValues[2].toIntOrNull() ?: 0
            val s = m.groupValues[3].toIntOrNull() ?: 0
            val total = h * 3600 + min * 60 + s
            return when {
                total < 60 -> "每 $total 秒"
                total < 3600 -> "每 ${(total + 30) / 60} 分钟"
                total < 86400 -> {
                    val hours = total / 3600.0
                    if (hours == hours.toLong().toDouble()) "每 ${hours.toLong()} 小时"
                    else "每 ${((total / 3600.0) * 10).toLong() / 10.0} 小时"
                }
                else -> "每 ${(total + 43200) / 86400} 天"
            }
        }

        CRON_RE.find(trigger)?.let { m ->
            val p = mutableMapOf<String, String>()
            for (fm in CRON_FIELD_RE.findAll(m.groupValues[1])) {
                p[fm.groupValues[1]] = fm.groupValues[2]
            }
            val minute = p["minute"] ?: "*"
            val hour = p["hour"] ?: "*"
            val dow = p["day_of_week"] ?: "*"
            val dom = p["day"] ?: "*"

            // 每 N 分钟：minute='*/N'
            if (minute.startsWith("*/")) {
                return "每 ${minute.removePrefix("*/")} 分钟（cron）"
            }
            // 每天固定时间；hour 可能是多值（`9,21`）或步长（星号斜杠 N）
            if (!isWild(hour) && isWild(dow) && isWild(dom)) {
                return "每天 ${formatHours(hour, minute)}"
            }
            // 指定星期几
            if (!isWild(dow) && isWild(dom)) {
                val days = dow.split(",").joinToString("、") { d ->
                    DAY_NAMES[d.trim()] ?: d.trim()
                }
                return "每 $days ${padTime(hour, minute)}"
            }
            // 每月固定日
            if (!isWild(dom) && isWild(dow)) {
                return "每月 $dom 日 ${padTime(hour, minute)}"
            }
        }

        return trigger
    }

    /**
     * `2026-06-15 00:21:35+08:00` → `3 分钟后（00:24）`
     *
     * 已经过期的显示「已过期」，一小时内显示「即将执行」，当天显示「N 小时后」，
     * 跨天显示「M月D日 HH:mm」。无法解析时原样返回。
     */
    fun formatNextRun(nextRunTime: String?, nowEpochSeconds: Long): String {
        if (nextRunTime.isNullOrBlank()) return "已暂停"
        val instant = parseInstant(nextRunTime) ?: return nextRunTime
        val nextEpoch = instant.epochSeconds
        val diffMins = ((nextEpoch - nowEpochSeconds) / 60.0).let {
            if (it >= 0) (it + 0.5).toLong() else -((-it + 0.5).toLong())
        }
        val local = instant.toLocalDateTime(TimeZone.currentSystemDefault())
        val timeStr = "${pad2(local.hour.toString())}:${pad2(local.minute.toString())}"

        return when {
            diffMins < 0 -> "已过期（$timeStr）"
            diffMins < 1 -> "即将执行（$timeStr）"
            diffMins < 60 -> "$diffMins 分钟后（$timeStr）"
            diffMins < 1440 -> {
                val h = diffMins / 60
                val m = (diffMins % 60).toInt()
                val suffix = if (m > 0) "$h 小时 $m 分钟后" else "$h 小时后"
                "$suffix（$timeStr）"
            }
            else -> "${local.monthNumber}月${local.dayOfMonth}日 $timeStr"
        }
    }

    /**
     * 兼容两类后端时间格式：
     * - ISO8601 带偏移：`2026-06-15 00:21:35+08:00`（后端 `next_run_time` 的实际格式，
     *   空格分隔且偏移只有小时 —— 标准 ISO 解析器不接受，需补 `T` 和 `:00`）
     * - 标准 ISO8601：`2026-06-15T00:21:35+08:00`
     */
    internal fun parseInstant(raw: String): Instant? {
        val s = raw.trim()
        val candidates = mutableListOf(s)
        // "2026-06-15 00:21:35+08:00" → "2026-06-15T00:21:35+08:00"
        s.replaceFirst(' ', 'T').let { if (it != s) candidates += it }
        // 偏移只有小时："...+08:00" 已合规；"...+08" → "...+08:00"
        val shortOffset = Regex("""([+-]\d{2})$""")
        for (c in candidates.toList()) {
            shortOffset.find(c)?.let { m ->
                candidates += c.substring(0, m.range.first) + m.groupValues[1] + ":00"
            }
        }
        for (c in candidates) {
            runCatching { return Instant.parse(c) }
        }
        return null
    }

    /** 按日期分组用的 key：`2026-09-12`。无法解析返回 null。 */
    fun dateKeyOf(nextRunTime: String?): String? {
        val instant = nextRunTime?.let { parseInstant(it) } ?: return null
        val local = instant.toLocalDateTime(TimeZone.currentSystemDefault())
        return "${local.year}-${pad2(local.monthNumber.toString())}-${pad2(local.dayOfMonth.toString())}"
    }

    /** 时间轴的「HH:mm」标签；无下次执行时返回 `--:--`。 */
    fun timeLabelOf(nextRunTime: String?): String {
        val instant = nextRunTime?.let { parseInstant(it) } ?: return "--:--"
        val local = instant.toLocalDateTime(TimeZone.currentSystemDefault())
        return "${pad2(local.hour.toString())}:${pad2(local.minute.toString())}"
    }

    /** 当前时间戳（秒）。把平台时钟收敛在这里，页面层不直接依赖 kotlinx-datetime。 */
    fun nowEpochSeconds(): Long = Clock.System.now().epochSeconds

    /**
     * 「今天 + N 天」的日期键（`yyyy-MM-dd`，本地时区）。
     * 用于「今天」范围过滤 —— Web 的语义是「今天和明天」。
     */
    fun todayPlusDaysKey(days: Long): String {
        val local = (Clock.System.now() + Duration.parse("${days}d"))
            .toLocalDateTime(TimeZone.currentSystemDefault())
        return "${local.year}-${pad2(local.monthNumber.toString())}-${pad2(local.dayOfMonth.toString())}"
    }

    /** 场景键 → 中文名。与 Web 的 `sceneLabel` 一致。 */
    fun sceneLabel(scene: String): String = when (scene) {

        "work" -> "工作"
        "life" -> "生活"
        else -> scene
    }
}
