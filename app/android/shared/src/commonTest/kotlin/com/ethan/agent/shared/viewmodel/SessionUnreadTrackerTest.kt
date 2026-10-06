package com.ethan.agent.shared.viewmodel

import com.ethan.agent.core.model.SessionInfo
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * 会话未读红点判定（[SessionUnreadTracker]）的回归网。
 *
 * 覆盖用户报的 bug：「点进会话后抽屉里的红点仍存在，有时要点好几次才消失」——
 * 对应下面 markRead 之后**重复轮询仍然是已读**、以及抽屉独有会话（只在全量列表里）
 * 也能推对水位这两组用例。
 *
 * 判定口径与 Web/Desktop 的 `packages/shared/src/lib/unread.ts` 一致。
 */
private fun session(
    id: String,
    updatedAt: Long,
    lastReadAt: Long? = updatedAt,
    title: String = id,
) = SessionInfo(id = id, title = title, model = "m", updatedAt = updatedAt, lastReadAt = lastReadAt)

class SessionUnreadTrackerTest {

    // ── 基础判定 ───────────────────────────────────────────────────────────

    @Test
    fun watermarkCoveringUpdatedAtIsRead() {
        val tracker = SessionUnreadTracker()
        assertFalse(tracker.isUnread(session("a", updatedAt = 100, lastReadAt = 100)))
        assertFalse(tracker.isUnread(session("a", updatedAt = 100, lastReadAt = 120)))
    }

    @Test
    fun newerMessageThanWatermarkIsUnread() {
        val tracker = SessionUnreadTracker()
        assertTrue(tracker.isUnread(session("a", updatedAt = 200, lastReadAt = 100)))
    }

    @Test
    fun zeroWatermarkMeansNeverRead() {
        val tracker = SessionUnreadTracker()
        assertTrue(tracker.isUnread(session("a", updatedAt = 100, lastReadAt = 0)))
    }

    @Test
    fun unreadIdsOnlyContainsUnreadSessions() {
        val tracker = SessionUnreadTracker()
        val list = listOf(
            session("read", updatedAt = 100, lastReadAt = 100),
            session("unread", updatedAt = 200, lastReadAt = 100),
        )
        assertEquals(setOf("unread"), tracker.unreadIds(list))
    }

    // ── 清除：用户报的「点了不清 / 点好几次才消」 ─────────────────────────

    @Test
    fun markReadClearsImmediately() {
        val tracker = SessionUnreadTracker()
        val s = session("a", updatedAt = 200, lastReadAt = 100)
        assertTrue(tracker.isUnread(s))

        tracker.markRead("a", updatedAt = 200)

        assertFalse(tracker.isUnread(s))
    }

    @Test
    fun markReadSurvivesStaleServerWatermarkAcrossPolls() {
        // /read 回执还没回来（或丢包）时，轮询拿到的仍是旧水位 —— 红点不能因此回弹。
        // 这是老实现的失败模式：水位推的是「客户端快照」，服务端一刷新就重判未读。
        val tracker = SessionUnreadTracker()
        val stalePoll = session("a", updatedAt = 200, lastReadAt = 100)

        tracker.markRead("a", updatedAt = 200)

        repeat(3) {
            assertFalse(tracker.isUnread(stalePoll), "轮询不能让已清掉的红点回来")
            assertEquals(emptySet(), tracker.unreadIds(listOf(stalePoll)))
        }
    }

    @Test
    fun staleResponseLandingAfterFreshResponseCannotRelightTheDot() {
        // 乱序响应：较新的那次先落地（服务端已追平），较旧的那次后落地（还带 /read
        // 之前的水位）。乐观水位只增不减，所以后者也不能把红点带回来。
        val tracker = SessionUnreadTracker()
        tracker.markRead("a", updatedAt = 200)

        val fresh = session("a", updatedAt = 200, lastReadAt = 200)
        val stale = session("a", updatedAt = 200, lastReadAt = 100)

        assertFalse(tracker.isUnread(fresh))
        assertFalse(tracker.isUnread(stale), "旧响应后落地也不能点亮红点")
    }

    @Test
    fun markReadIsMonotonic() {
        val tracker = SessionUnreadTracker()
        tracker.markRead("a", updatedAt = 200)
        tracker.markRead("a", updatedAt = 150) // 更旧的值不能把水位拉低
        assertFalse(tracker.isUnread(session("a", updatedAt = 200, lastReadAt = 100)))
    }

    @Test
    fun messageArrivingAfterMarkReadMakesUnreadAgain() {
        val tracker = SessionUnreadTracker()
        tracker.markRead("a", updatedAt = 200)

        assertTrue(tracker.isUnread(session("a", updatedAt = 250, lastReadAt = 200)), "新消息应重新亮红点")
        assertFalse(tracker.isUnread(session("a", updatedAt = 200, lastReadAt = 200)))
    }

    @Test
    fun markReadWithUnknownUpdatedAtDoesNotInventWatermark() {
        // 列表里还没有这条会话（深链直进）时 updatedAt 传 0：不写乐观水位，
        // 免得用一个凭空的 0 水位把后续真实未读吞掉。
        val tracker = SessionUnreadTracker()
        tracker.markRead("a", updatedAt = 0)
        assertTrue(tracker.isUnread(session("a", updatedAt = 100, lastReadAt = 0)))
    }

    // ── 服务端水位推进到更前面时，乐观水位不会拦住后续的新消息 ──────────────

    @Test
    fun laterMessagesStillShowUnreadAfterServerWatermarkMovesOn() {
        val tracker = SessionUnreadTracker()
        tracker.markRead("a", updatedAt = 200)

        // 服务端水位走到 200（与本地乐观水位一致）之后又来新消息：仍然正确判未读
        assertFalse(tracker.isUnread(session("a", updatedAt = 200, lastReadAt = 200)))
        assertTrue(tracker.isUnread(session("a", updatedAt = 300, lastReadAt = 200)))
    }

    // ── 正在查看的会话 ────────────────────────────────────────────────────

    @Test
    fun activeSessionNeverUnread() {
        val tracker = SessionUnreadTracker()
        val s = session("a", updatedAt = 200, lastReadAt = 100)

        tracker.setActive("a")
        assertFalse(tracker.isUnread(s), "正在看的会话不亮红点")
        assertEquals(emptySet(), tracker.unreadIds(listOf(s)))

        tracker.setActive(null)
        assertTrue(tracker.isUnread(s), "离开后仍未读（没走过 markRead）就该亮红点")
    }

    @Test
    fun activeNeedsReadReportOnlyWhenServerStillUnread() {
        val tracker = SessionUnreadTracker()
        tracker.setActive("a")

        // 服务端还标着未读 → 需要补一次 /read 上报（本地乐观水位按住了红点）
        assertTrue(tracker.serverUnread(session("a", updatedAt = 200, lastReadAt = 100)))
        assertEquals("a", tracker.activeNeedsReadReport(listOf(session("a", updatedAt = 200, lastReadAt = 100))))

        // 服务端已追平 → 不再重复上报
        assertNull(tracker.activeNeedsReadReport(listOf(session("a", updatedAt = 200, lastReadAt = 200))))
        // 不在列表里 / 没有活跃会话 → 不上报
        assertNull(tracker.activeNeedsReadReport(emptyList()))
        tracker.setActive(null)
        assertNull(tracker.activeNeedsReadReport(listOf(session("a", updatedAt = 200, lastReadAt = 100))))
    }

    // ── 旧后端兼容 ────────────────────────────────────────────────────────

    @Test
    fun legacyServerWithoutWatermarkShowsNoUnread() {
        // 不返回 last_read_at 的后端：一律按已读，不能升级后满屏红点
        val tracker = SessionUnreadTracker()
        val legacy = session("a", updatedAt = 200, lastReadAt = null)
        assertNull(legacy.lastReadAt)
        assertFalse(tracker.isUnread(legacy))
        assertFalse(tracker.serverUnread(legacy))
    }

    // ── 水位取值要找全两个列表（根因之一） ─────────────────────────────────

    @Test
    fun latestKnownUpdatedAtLooksAtDrawerListToo() {
        // 定时/心跳/后台会话、以及掉出默认 50 条窗口的会话只在抽屉（未过滤全量列表）里。
        // 老实现只从主列表取 updatedAt → 水位推不动 → 红点清不掉。
        val main = listOf(session("normal", updatedAt = 500))
        val drawer = listOf(session("normal", updatedAt = 500), session("scheduled", updatedAt = 900))

        assertEquals(900, latestKnownUpdatedAt(main, drawer, "scheduled"))
        assertEquals(500, latestKnownUpdatedAt(main, drawer, "normal"))
    }

    @Test
    fun latestKnownUpdatedAtTakesFreshestOfBothLists() {
        // 同一条会话两处都有（抽屉刚轮询完、主列表还是缓存）→ 取最新
        val main = listOf(session("a", updatedAt = 100))
        val drawer = listOf(session("a", updatedAt = 300))
        assertEquals(300, latestKnownUpdatedAt(main, drawer, "a"))
    }

    @Test
    fun latestKnownUpdatedAtReturnsZeroForUnknownSession() {
        assertEquals(0, latestKnownUpdatedAt(emptyList(), emptyList(), "nope"))
    }

    @Test
    fun drawerOnlySessionClearsOnceAndStaysCleared() {
        // 端到端串一下根因场景：抽屉独有的定时会话点开后，红点必须一次清除且不再回弹。
        val tracker = SessionUnreadTracker()
        val main = listOf(session("normal", updatedAt = 500))
        val drawer = listOf(session("normal", updatedAt = 500), session("scheduled", updatedAt = 900, lastReadAt = 800))

        assertEquals(setOf("scheduled"), tracker.unreadIds(main + drawer))

        // 用户点开（走 SessionUnreadTracker + latestKnownUpdatedAt 的组合，与 VM 一致）
        tracker.setActive("scheduled")
        tracker.markRead("scheduled", latestKnownUpdatedAt(main, drawer, "scheduled"))

        // 之后几轮轮询（服务端水位还没追上）都不能让红点回来
        repeat(3) {
            assertEquals(emptySet(), tracker.unreadIds(main + drawer))
        }

        // 离开会话后依然已读
        tracker.setActive(null)
        assertEquals(emptySet(), tracker.unreadIds(main + drawer))

        // 服务端追平后照常判新消息
        val caughtUp = listOf(session("scheduled", updatedAt = 900, lastReadAt = 900))
        assertEquals(emptySet(), tracker.unreadIds(caughtUp))
        assertEquals(setOf("scheduled"), tracker.unreadIds(listOf(session("scheduled", updatedAt = 1200, lastReadAt = 900))))
    }
}
