package com.ethan.agent.core.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ServerUrlUtilsTest {

    @Test
    fun sessionWebUrlUsesOriginNotApiBase() {
        // 必须是给人看的页面地址：带 /api 的地址在浏览器里只会吐 JSON。
        assertEquals(
            "http://127.0.0.1:8900/chat/s_20260923_0028_5bc7/",
            ServerUrlUtils.toSessionWebUrl("http://127.0.0.1:8900", "s_20260923_0028_5bc7"),
        )
    }

    @Test
    fun sessionWebUrlToleratesDirtyServerUrl() {
        // 用户可能把带路径/带 /api/ 的地址粘进设置页，origin 归一化后仍然是干净的。
        assertEquals(
            "https://chat.example.com:29999/chat/s_1/",
            ServerUrlUtils.toSessionWebUrl("https://chat.example.com:29999/api/chat/", "s_1"),
        )
        // 不带 scheme 的裸域名按 https 兜底（与 normalize 一致）。
        assertEquals(
            "https://example.com/chat/s_1/",
            ServerUrlUtils.toSessionWebUrl("example.com", "s_1"),
        )
    }

    @Test
    fun sessionWebUrlTrimsSessionId() {
        assertEquals(
            "http://127.0.0.1:8900/chat/s_1/",
            ServerUrlUtils.toSessionWebUrl("http://127.0.0.1:8900", "  s_1  "),
        )
    }

    @Test
    fun sessionWebUrlReturnsNullWhenNotComposable() {
        // 新会话还没有 id：宁可不显示复制入口，也不复制一个打开就是 404 的地址。
        assertNull(ServerUrlUtils.toSessionWebUrl("http://127.0.0.1:8900", ""))
        assertNull(ServerUrlUtils.toSessionWebUrl("http://127.0.0.1:8900", "   "))
        // 服务器地址还没加载出来 / 非法。
        assertNull(ServerUrlUtils.toSessionWebUrl("", "s_1"))
        assertNull(ServerUrlUtils.toSessionWebUrl("ftp://example.com", "s_1"))
    }
}
