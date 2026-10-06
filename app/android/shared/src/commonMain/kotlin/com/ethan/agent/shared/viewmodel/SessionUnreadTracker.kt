package com.ethan.agent.shared.viewmodel

import com.ethan.agent.core.model.SessionInfo

/**
 * 会话未读红点的判定状态机（纯逻辑，无平台依赖，commonTest 可直接覆盖）。
 *
 * ## 为什么不是「客户端比较两次轮询的 updatedAt」
 *
 * 旧实现是客户端自造的启发式：记下每个会话上次看到的 `updatedAt`，下一次轮询发现变大
 * 就点亮红点，`markRead` 再把水位推上去。它有两个天生不稳的地方（就是用户报的
 * 「点进去红点不清除 / 要点好几次才消失」）：
 *
 * 1. `markRead` 只从**主列表**（服务端 hide_heartbeat/hide_scheduled/hide_background
 *    之后的 50 条）里取会话来推水位，而抽屉吃的是**未过滤**的全量列表。定时/心跳/后台
 *    会话、或掉出前 50 的会话点开后水位推不上去，3 秒后的轮询又把它判成未读——红点
 *    永远清不掉。
 * 2. 水位推的是「客户端上一次轮询快照」的 `updatedAt`，而不是服务端的实时值；消息恰好
 *    在点击前到达时水位仍然偏低，下一次轮询红点回弹——「有时」。
 *
 * ## 现在怎么算
 *
 * 判定口径与 Web/Desktop 完全一致（`packages/shared/src/lib/unread.ts`）：
 *
 * ```
 * 未读 = updated_at > last_read_at      // 服务端水位，UPDATE 是原子的
 * ```
 *
 * 客户端只额外叠一层**本地乐观水位**：点开会话时立刻把水位推到已知的 `updatedAt`，
 * 不等 `/sessions/{id}/read` 回执。服务端水位一旦追平，乐观水位即退休（[observe]），
 * 保证「清掉的红点不会因为回执慢/丢包而闪回来」。
 *
 * 另外，正在查看的会话永不亮红点（对齐 Web sidebar 的 activeSessionId）——后台回复
 * 实时到达时不该给用户自己正在看的会话点一个红点。
 */
class SessionUnreadTracker {

    /** 本地乐观水位：sessionId -> 已读到（含）的 updated_at（epoch 秒） */
    private val optimisticWatermarks = mutableMapOf<String, Long>()

    /** 正在查看的会话 id；null 表示当前不在任何会话里 */
    var activeSessionId: String? = null
        private set

    fun setActive(id: String?) {
        activeSessionId = id
    }

    /**
     * 未读判定的服务端一侧水位。
     *
     * `lastReadAt` 为 null = 旧后端不返回该字段 → 按「已读」兜底，避免升级后满屏假红点
     * （老客户端本来也没有红点，退回无红点比全量误报安全）。
     */
    private fun serverWatermark(session: SessionInfo): Long =
        session.lastReadAt ?: session.updatedAt

    /** 判定水位 = 服务端水位与本地乐观水位取高 */
    private fun effectiveWatermark(session: SessionInfo): Long =
        maxOf(serverWatermark(session), optimisticWatermarks[session.id] ?: 0L)

    /**
     * 只看服务端口径的未读（不含本地乐观水位）。
     *
     * 用于决定「正在查看的会话要不要补一次 /read 上报」——乐观水位已经把红点按住了，
     * 但服务端水位没推进的话，Web/桌面端还会一直亮着。
     */
    fun serverUnread(session: SessionInfo): Boolean =
        session.updatedAt > serverWatermark(session)

    fun isUnread(session: SessionInfo): Boolean {
        if (session.id == activeSessionId) return false
        return session.updatedAt > effectiveWatermark(session)
    }

    fun unreadIds(sessions: List<SessionInfo>): Set<String> =
        sessions.asSequence().filter { isUnread(it) }.map { it.id }.toSet()

    /**
     * 标记已读（乐观）：把本地水位推到 [updatedAt]（单调递增，不会被更旧的值拉低）。
     *
     * @param updatedAt 该会话当前已知的 `updatedAt`；拿到 0（列表里还没有这条会话）时
     *                  不写乐观水位，靠正在查看的会话豁免 + 服务端 /read 兜住。
     */
    fun markRead(id: String, updatedAt: Long) {
        if (updatedAt > (optimisticWatermarks[id] ?: 0L)) {
            optimisticWatermarks[id] = updatedAt
        }
    }

    /**
     * 新一批服务端数据到达时调用：服务端水位已追平本地乐观水位的，可以退休，
     * 避免这张表随会话数无限增长。
     */
    fun observe(sessions: List<SessionInfo>) {
        for (session in sessions) {
            val server = session.lastReadAt ?: continue
            val local = optimisticWatermarks[session.id] ?: continue
            if (server >= local) optimisticWatermarks.remove(session.id)
        }
    }

    /**
     * 正在查看、且服务端仍标未读的会话（需要补一次 /read 上报）。
     *
     * 覆盖两种场景：`/read` 请求丢包；以及后台落消息时该会话没有活跃订阅者
     * （服务端不会自动推水位）。对齐 Web sidebar 的 markActiveRead。
     */
    fun activeNeedsReadReport(sessions: List<SessionInfo>): String? {
        val id = activeSessionId ?: return null
        val session = sessions.firstOrNull { it.id == id } ?: return null
        return if (serverUnread(session)) id else null
    }

    /** 切换服务器/登出时清空，避免上一个后端的会话水位带过来。 */
    fun reset() {
        optimisticWatermarks.clear()
        activeSessionId = null
    }
}

/**
 * 「点开这个会话该把水位推到哪个 updatedAt」。
 *
 * **主列表和抽屉列表都要看**：抽屉是未过滤的全量列表，定时/心跳/后台会话、以及掉出
 * 默认 50 条窗口的会话只在 `drawerSessions` 里有。旧实现只看主列表，这些会话的水位
 * 推不上去，红点清了又回来。
 */
fun latestKnownUpdatedAt(
    sessions: List<SessionInfo>,
    drawerSessions: List<SessionInfo>,
    id: String,
): Long = maxOf(
    sessions.asSequence().filter { it.id == id }.maxOfOrNull { it.updatedAt } ?: 0L,
    drawerSessions.asSequence().filter { it.id == id }.maxOfOrNull { it.updatedAt } ?: 0L,
)
