package com.ethan.agent.shared.viewmodel

/**
 * 记忆列表的分页拼接纯函数（commonMain，可单测、iOS 也能用）。
 *
 * 与 Web/Desktop 的 `@ethan/shared/lib/memory-paging.ts` 是同一套规则的 Kotlin 版本：
 * 两端行为要一致，分页边界这种细节各写一版很容易慢慢漂移。
 */

/** 记忆列表每页条数（三端保持一致）。 */
const val MEMORY_PAGE = 30

/**
 * 追加下一页到列表尾部。
 *
 * - 按 [idOf] 去重：offset 翻页在「两次请求之间有编辑/删除」时会错位 ——
 *   后端按 updated_at DESC 排序，期间有记录被改就会整段重排，下一页可能
 *   把上一页的尾巴再发一次。
 * - 返回新 list（不原地改），便于 Compose 判断状态变更。
 */
fun <T> appendPage(current: List<T>, page: List<T>, idOf: (T) -> String): List<T> {
    if (page.isEmpty()) return current
    val seen = current.mapTo(mutableSetOf(), idOf)
    val fresh = page.filter { idOf(it) !in seen }
    if (fresh.isEmpty()) return current
    return current + fresh
}

/**
 * 翻页后判断「还有没有下一页」。
 *
 * 优先用后端的 [total]：`offset + 本页条数 < total` 就是还有。这比「本页是否拿到
 * 满页」准 —— 恰好整除时后者会多请求一次空页（转到头了还在转圈）。
 *
 * [total] 缺省时（老后端不返回，用 0 或负数表示「不知道」）退回按页大小判断。
 *
 * @param page  刚拉到的一页；null = 请求失败，不要把「失败」当成「到头了」，
 *              否则一次网络抖动会让用户再也拉不到后面的页
 * @param total 后端返回的总条数；<= 0 视为未知
 */
fun <T> hasMoreAfter(
    page: List<T>?,
    total: Int?,
    offset: Int = 0,
    pageSize: Int = MEMORY_PAGE,
): Boolean {
    if (page == null) return false
    if (total != null && total > 0) return offset + page.size < total
    return page.size >= pageSize
}

/**
 * 用「刚拉到的一页」刷新列表头部，同时保留更靠后的已加载分页。
 *
 * 使用场景：编辑 / 删除一条记忆后要刷新列表。这时列表里可能已经有用户往下翻出来的
 * 好几页，直接 `list = firstPage` 会让那些页凭空消失 —— 用户看到的是「刚翻出来的
 * 内容突然没了」。所以只替换第一页覆盖的范围，后面的原样留着。
 *
 * 与 `chat/history.ts` 的 `replaceTailKeepOlder` 同思路，方向相反：消息是往上翻、
 * 保留更早的；记忆列表是往下翻、保留更靠后的。
 *
 * - [fresh] 为空 → 不改动（宁可不动，也不要把已翻出来的列表清空）
 * - [fresh] 没铺满一页 → 本来就没有更多了，以它为准
 * - 重叠区间用 [fresh] 的版本
 */
fun <T> replaceHeadKeepLater(
    prev: List<T>,
    fresh: List<T>,
    idOf: (T) -> String,
    pageSize: Int = MEMORY_PAGE,
): List<T> {
    if (fresh.isEmpty()) return prev
    if (fresh.size < pageSize) return fresh
    if (prev.size <= fresh.size) return fresh
    val kept = prev.drop(fresh.size)
    val freshIds = fresh.mapTo(mutableSetOf(), idOf)
    return fresh + kept.filter { idOf(it) !in freshIds }
}
