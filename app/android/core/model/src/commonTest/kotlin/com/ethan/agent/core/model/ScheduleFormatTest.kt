package com.ethan.agent.core.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class ScheduleFormatTest {

    @Test
    fun `每小时特定分钟`() {
        val trigger = "cron[month='*', day='*', day_of_week='*', hour='*', minute='17']"
        assertEquals("每小时第 17 分", ScheduleFormat.formatTrigger(trigger))
    }

    @Test
    fun `每小时多个分钟`() {
        val trigger = "cron[month='*', day='*', day_of_week='*', hour='*', minute='0,30']"
        assertEquals("每小时 00、30 分", ScheduleFormat.formatTrigger(trigger))
    }

    @Test
    fun `每小时整点`() {
        val trigger = "cron[month='*', day='*', day_of_week='*', hour='*', minute='0']"
        assertEquals("每小时整点", ScheduleFormat.formatTrigger(trigger))
    }

    @Test
    fun `工作日特定时间`() {
        val trigger = "cron[month='*', day='*', day_of_week='mon-fri', hour='9', minute='30']"
        assertEquals("工作日 09:30", ScheduleFormat.formatTrigger(trigger))
    }

    @Test
    fun `周末特定时间`() {
        val trigger = "cron[month='*', day='*', day_of_week='sat,sun', hour='10', minute='0']"
        assertEquals("周末 10:00", ScheduleFormat.formatTrigger(trigger))
    }

    @Test
    fun `每天多个小时`() {
        val trigger = "cron[month='*', day='*', day_of_week='*', hour='9,21', minute='0']"
        assertEquals("每天 09:00、21:00", ScheduleFormat.formatTrigger(trigger))
    }

    @Test
    fun `小时范围`() {
        val trigger = "cron[month='*', day='*', day_of_week='*', hour='10-23', minute='0']"
        assertEquals("每天 10-23 点 整点", ScheduleFormat.formatTrigger(trigger))
    }

    @Test
    fun `每月固定日`() {
        val trigger = "cron[month='*', day='15', day_of_week='*', hour='8', minute='0']"
        assertEquals("每月 15 日 08:00", ScheduleFormat.formatTrigger(trigger))
    }

    @Test
    fun `特定星期几`() {
        val trigger = "cron[month='*', day='*', day_of_week='1,3,5', hour='14', minute='0']"
        assertEquals("每 周一、周三、周五 14:00", ScheduleFormat.formatTrigger(trigger))
    }

    @Test
    fun `单次时间`() {
        val trigger = "date[2026-10-01 10:00:00+08:00]"
        assertEquals("单次 2026-10-01 10:00", ScheduleFormat.formatTrigger(trigger))
    }

    @Test
    fun `时间间隔`() {
        assertEquals("每 10 分钟", ScheduleFormat.formatTrigger("interval[0:10:00]"))
        assertEquals("每 2 小时", ScheduleFormat.formatTrigger("interval[2:00:00]"))
    }

    @Test
    fun `不会泄露机器星号语法`() {
        val trigger = "cron[month='*', day='*', day_of_week='*', hour='*', minute='42']"
        val formatted = ScheduleFormat.formatTrigger(trigger)
        assertFalse(formatted.contains("*"))
        assertFalse(formatted.contains("cron["))
    }
}
