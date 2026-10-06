package com.ethan.agent.core.model

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * [FileSignatureFreshness] 的单测。
 *
 * 背景（issue ETHA-30）：深度听书交付的音频卡片在 App 上「点播放没反应/打开一个 401 页面」，
 * 根因之一是签名只在渲染时取一次，页面停留超过服务端 TTL(600s) 后播放/下载必然 401。
 * 这里把 TTL 与安全余量的判定钉住，防止有人把余量改没了。
 */
class FileSignatureFreshnessTest {

    private val t0 = 1_700_000_000_000L

    @Test
    fun freshSignatureIsNotStale() {
        assertFalse(FileSignatureFreshness.isStale(t0, t0))
        assertFalse(FileSignatureFreshness.isStale(t0, t0 + 60_000))
        // TTL 600s - 余量 60s = 540s 内都还新鲜
        assertFalse(FileSignatureFreshness.isStale(t0, t0 + 539_999))
    }

    @Test
    fun staleAfterSafetyMargin() {
        assertTrue(FileSignatureFreshness.isStale(t0, t0 + 540_000))
        assertTrue(FileSignatureFreshness.isStale(t0, t0 + FileSignatureFreshness.TTL_MS))
        assertTrue(FileSignatureFreshness.isStale(t0, t0 + FileSignatureFreshness.TTL_MS + 1))
    }

    @Test
    fun neverSignedCountsAsStale() {
        assertTrue(FileSignatureFreshness.isStale(0L, t0))
        assertTrue(FileSignatureFreshness.isStale(-1L, t0))
    }

    @Test
    fun clockGoingBackwardsCountsAsStale() {
        // 用户改系统时间/时区后 now < signedAt：宁可重签，也不要拿可能失效的直链去撞 401。
        assertTrue(FileSignatureFreshness.isStale(t0, t0 - 1))
    }
}
