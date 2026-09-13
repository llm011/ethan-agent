package com.ethan.agent.shared.viewmodel

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertSame
import kotlin.test.assertTrue

/**
 * 记忆列表分页拼接规则。
 *
 * 这些函数是「下滑加载更多」的防回归网：一旦有人把去重改掉、或把 hasMore 判定
 * 退回「本页是否满」，现象是列表出现重复卡片、或恰好整除时多转一次圈。
 *
 * 与 Web/Desktop 的 `memory-paging.spec.ts` 覆盖同一组性质（两端行为要一致）。
 */
private data class Item(val id: String)

private fun item(id: String) = Item(id)

private fun page(from: Int, count: Int, prefix: String = "m") =
    (from until from + count).map { item("$prefix$it") }

class MemoryPagingTest {

    // ── appendPage ─────────────────────────────────────────────────────────

    @Test
    fun appendPageAppendsToTail() {
        val result = appendPage(page(0, 2), page(2, 2)) { it.id }
        assertEquals(listOf("m0", "m1", "m2", "m3"), result.map { it.id })
    }

    @Test
    fun appendPageDedupesById() {
        // 第二页把第一页的尾巴又发了一次（期间有记录被编辑导致重排）
        val result = appendPage(page(0, 3), page(2, 3)) { it.id }
        assertEquals(listOf("m0", "m1", "m2", "m3", "m4"), result.map { it.id })
    }

    @Test
    fun appendPageAllDuplicatesReturnsSameList() {
        val current = page(0, 2)
        assertSame(current, appendPage(current, page(0, 2)) { it.id })
    }

    @Test
    fun appendPageEmptyPageReturnsSameList() {
        val current = page(0, 2)
        assertSame(current, appendPage(current, emptyList()) { it.id })
    }

    @Test
    fun appendPageDoesNotMutateInput() {
        val current = page(0, 2)
        appendPage(current, page(2, 2)) { it.id }
        assertEquals(listOf("m0", "m1"), current.map { it.id })
    }

    @Test
    fun appendSecondPageYieldsFullList() {
        val first = page(0, MEMORY_PAGE)
        val second = page(MEMORY_PAGE, MEMORY_PAGE)
        val result = appendPage(first, second) { it.id }
        assertEquals(MEMORY_PAGE * 2, result.size)
        assertEquals(result.size, result.map { it.id }.toSet().size, "不应有重复")
    }

    // ── hasMoreAfter ───────────────────────────────────────────────────────

    @Test
    fun hasMorePrefersServerTotal() {
        // 后端说总共 10 条，现在拿到 offset 0..2 —— 还有
        assertTrue(hasMoreAfter(page(0, 3), total = 10, offset = 0, pageSize = 3))
        // 拿到 9..9（第 10 条），到头了
        assertFalse(hasMoreAfter(page(9, 1), total = 10, offset = 9, pageSize = 3))
    }

    @Test
    fun hasMoreExactPageBoundaryIsNotMore() {
        // 恰好整除：最后一页拿满 5 条，后端 total 也是 10 —— 不该再多请求一次空页
        assertFalse(hasMoreAfter(page(5, 5), total = 10, offset = 5, pageSize = 5))
        // 老写法「本页满 5 条就当还有」在这里会多转一次圈
        assertFalse(hasMoreAfter(page(5, 5), total = 10, offset = 5, pageSize = 5))
    }

    @Test
    fun hasMoreFallsBackToPageSizeWithoutTotal() {
        // 老后端不返回 total（0 = 未知）→ 退回按页大小判断
        assertTrue(hasMoreAfter(page(0, 3), total = 0, offset = 0, pageSize = 3))
        assertTrue(hasMoreAfter(page(0, 3), total = null, offset = 0, pageSize = 3))
        assertFalse(hasMoreAfter(page(0, 2), total = 0, offset = 0, pageSize = 3))
        assertFalse(hasMoreAfter(page(0, 2), total = null, offset = 0, pageSize = 3))
    }

    @Test
    fun hasMoreUsesOffsetNotJustPageSize() {
        // 页大小 3、total 4：第一页后还有，第二页后没有
        assertTrue(hasMoreAfter(page(0, 3), total = 4, offset = 0, pageSize = 3))
        assertFalse(hasMoreAfter(page(3, 1), total = 4, offset = 3, pageSize = 3))
    }

    @Test
    fun hasMoreOnFailedRequestIsFalse() {
        // 请求失败（page == null）不能当成「到头了」，但也不该继续请求
        assertFalse(hasMoreAfter<String>(null, total = 100, offset = 0, pageSize = 3))
    }

    // ── replaceHeadKeepLater ───────────────────────────────────────────────

    @Test
    fun refreshKeepsLaterPages() {
        val loaded = page(0, 4)
        val fresh = page(0, 2)
        val result = replaceHeadKeepLater(loaded, fresh, { it.id }, pageSize = 2)
        assertEquals(listOf("m0", "m1", "m2", "m3"), result.map { it.id })
    }

    @Test
    fun refreshWithShortFirstPageReplacesEverything() {
        // 第一页没铺满 → 本来就没更多了
        val result = replaceHeadKeepLater(page(0, 3), page(0, 1), { it.id }, pageSize = 2)
        assertEquals(listOf("m0"), result.map { it.id })
    }

    @Test
    fun refreshWithEmptyPageKeepsList() {
        val loaded = page(0, 3)
        assertSame(loaded, replaceHeadKeepLater(loaded, emptyList(), { it.id }, pageSize = 2))
    }

    @Test
    fun refreshAfterDeleteDoesNotDuplicate() {
        // 第一页删掉 m1、服务端补进 m2
        val loaded = listOf(item("m0"), item("m1"), item("m2"), item("m3"))
        val fresh = listOf(item("m0"), item("m2"))
        val result = replaceHeadKeepLater(loaded, fresh, { it.id }, pageSize = 2)
        val ids = result.map { it.id }
        assertEquals(ids.size, ids.toSet().size, "不应有重复：$ids")
        assertEquals(listOf("m0", "m2", "m3"), ids)
    }

    @Test
    fun refreshUsesDefaultPageSize() {
        val loaded = page(0, MEMORY_PAGE + 5)
        val fresh = page(0, MEMORY_PAGE)
        assertEquals(MEMORY_PAGE + 5, replaceHeadKeepLater(loaded, fresh, { it.id }).size)    }
}
