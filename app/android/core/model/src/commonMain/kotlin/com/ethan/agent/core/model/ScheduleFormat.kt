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
    private val DATE_RE = Regex("""date\[(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})""")

    private val DAY_NAMES = mapOf(
        "0" to "周日", "1" to "周一", "2" to "周二", "3" to "周三",
        "4" to "周四", "5" to "周五", "6" to "周六", "7" to "周日",
        "mon" to "周一", "tue" to "周二", "wed" to "周三", "thu" to "周四",
        "fri" to "周五", "sat" to "周六", "sun" to "周日",
    )

    private fun isWild(v: String?): Boolean = v.isNullOrBlank() || v == "*"

    private fun pad2(v: String): String = if (v.length >= 2) v else "0".repeat(2 - v.length) + v

    private fun formatDow(dow: String): String {
        val lower = dow.trim().lowercase()
        if (isWild(lower)) return ""
        if (lower == "mon-fri" || lower == "1-5") return "工作日"
        if (lower in setOf("sat,sun", "sun,sat", "6,0", "0,6", "6,7", "7,6")) return "周末"
        return lower.split(",").joinToString("、") { d ->
            val key = d.trim()
            DAY_NAMES[key] ?: key
        }
    }

    private fun formatMinutes(minute: String): String {
        if (minute.startsWith("*/")) {
            return "每 ${minute.removePrefix("*/")} 分钟"
        }
        if (minute.contains(",")) {
            val mins = minute.split(",").joinToString("、") { pad2(it.trim()) }
            return "第 ${mins} 分"
        }
        if (isWild(minute) || minute == "0") return "整点"
        return "第 ${pad2(minute)} 分"
    }

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
     * 支持形式（与后端 `scheduler` 一致）：
     * - `interval[H:MM:SS]` → 「每 N 分钟 / 每 N 小时 / 每 N 天」
     * - `cron[key='val', ...]` → 「每天 09:00」「每小时第 17 分」「工作日 09:00」「每月 15 日 08:00」
     * - `date[...]` → 「单次 2026-10-01 10:00」
     *
     * 无法识别时做去通配兜底，绝不直接把带 * 的机器 cron 语法暴露给用户。
     */
    fun formatTrigger(trigger: String): String {
        DATE_RE.find(trigger)?.let { m ->
            return "单次 ${m.groupValues[1]} ${m.groupValues[2]}"
        }

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
            val month = p["month"] ?: "*"

            val dowStr = formatDow(dow)
            val dowPrefix = when {
                dowStr.isEmpty() -> ""
                dowStr in setOf("工作日", "周末") -> "$dowStr "
                else -> "每 $dowStr "
            }

            // 1. 每 N 分钟：minute='*/N'
            if (minute.startsWith("*/")) {
                val step = minute.removePrefix("*/")
                return if (isWild(hour)) {
                    "${dowPrefix}每 $step 分钟"
                } else if (hour.contains("-")) {
                    "${dowPrefix}${hour} 点每 $step 分钟"
                } else {
                    "${dowPrefix}${formatHours(hour, "00")} 起每 $step 分钟"
                }
            }

            // 2. 每小时（hour 通配符，如 hour='*'）：常见如每小时第 17 分、每小时整点
            if (isWild(hour)) {
                val minStr = formatMinutes(minute)
                return if (dowPrefix.isNotEmpty()) {
                    "${dowPrefix}每小时$minStr"
                } else {
                    "每小时$minStr"
                }
            }

            // 3. 小时范围（如 hour='9-18' 或 '10-23'）
            if (hour.contains("-")) {
                val minStr = if (isWild(minute) || minute == "0") "整点" else ":${pad2(minute)}"
                return if (dowPrefix.isNotEmpty()) {
                    "${dowPrefix}${hour} 点 $minStr"
                } else {
                    "每天 ${hour} 点 $minStr"
                }
            }

            // 4. 每年固定月份+日期
            if (!isWild(month) && !isWild(dom)) {
                return "每年 ${month}月${dom}日 ${formatHours(hour, minute)}"
            }

            // 5. 每年固定月份
            if (!isWild(month)) {
                return "每年 ${month}月 ${formatHours(hour, minute)}"
            }

            // 6. 每月固定日
            if (!isWild(dom) && isWild(dow)) {
                return "每月 $dom 日 ${formatHours(hour, minute)}"
            }

            // 7. 指定星期几 / 工作日 / 周末
            if (!isWild(dow) && isWild(dom)) {
                return "${dowPrefix}${formatHours(hour, minute)}"
            }

            // 8. 每天固定时间
            if (!isWild(hour) && isWild(dow) && isWild(dom)) {
                return "每天 ${formatHours(hour, minute)}"
            }

            // 9. 兜底格式化：把非通配字段拼接起来，绝不输出带 * 的机器字符串
            val parts = mutableListOf<String>()
            if (!isWild(month)) parts.add("${month}月")
            if (!isWild(dom)) parts.add("${dom}日")
            if (dowPrefix.isNotBlank()) parts.add(dowPrefix.trim())
            if (!isWild(hour) || !isWild(minute)) {
                parts.add(formatHours(hour, minute))
            }
            if (parts.isNotEmpty()) {
                return parts.joinToString(" ")
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
