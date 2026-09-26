package com.ethan.agent.shared.viewmodel

import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * `MessageRoleKind.of` 的分类语义单测。
 *
 * 背景：移动端隐藏头像后，气泡靠「角色配色 + 角色名」区分说话方，而这个分类是
 * 配色与取名的**唯一输入**。分错了就是整条气泡的颜色和名字都错，所以在纯逻辑层钉住它。
 *
 * 重点覆盖两类容易出错的情况：
 *  1. 大小写/空白：服务端与历史数据里的 role 不保证是规范小写（`"User"` / `" user "`）。
 *  2. 未知值：必须**兜底成 Assistant 而不是抛异常** —— 展示层要能扛住脏数据，
 *     否则服务端将来加一个新 role 就会让老客户端崩在渲染里。
 */
class MessageRoleKindTest {

    @Test
    fun `规范 role 各自映射到对应分类`() {
        assertEquals(MessageRoleKind.User, MessageRoleKind.of("user"))
        assertEquals(MessageRoleKind.Assistant, MessageRoleKind.of("assistant"))
        assertEquals(MessageRoleKind.Tool, MessageRoleKind.of("tool"))
        assertEquals(MessageRoleKind.System, MessageRoleKind.of("system"))
    }

    @Test
    fun `工具类别名都归到 Tool`() {
        // 服务端历史上同时出现过 tool / function / tool_result 三种写法，
        // 只认 "tool" 会让另两种落到 Assistant，颜色和名字都错。
        assertEquals(MessageRoleKind.Tool, MessageRoleKind.of("function"))
        assertEquals(MessageRoleKind.Tool, MessageRoleKind.of("tool_result"))
    }

    @Test
    fun `大小写与首尾空白不影响分类`() {
        assertEquals(MessageRoleKind.User, MessageRoleKind.of("USER"))
        assertEquals(MessageRoleKind.User, MessageRoleKind.of("  user  "))
        assertEquals(MessageRoleKind.Assistant, MessageRoleKind.of("Assistant"))
    }

    @Test
    fun `未知或缺失的 role 兜底成 Assistant 而不是抛异常`() {
        // 这是刻意的容错：宁可颜色不准，也不能因为一个没见过的 role 让整条消息渲染失败。
        assertEquals(MessageRoleKind.Assistant, MessageRoleKind.of(null))
        assertEquals(MessageRoleKind.Assistant, MessageRoleKind.of(""))
        assertEquals(MessageRoleKind.Assistant, MessageRoleKind.of("   "))
        assertEquals(MessageRoleKind.Assistant, MessageRoleKind.of("brand_new_role"))
    }
}
