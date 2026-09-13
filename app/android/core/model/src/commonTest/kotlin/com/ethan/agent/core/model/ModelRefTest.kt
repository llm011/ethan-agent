package com.ethan.agent.core.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * `fullId` / `modelCandidates` / `resolveModel` / `isAmbiguous` / `ambiguousCandidates`
 * 的纯函数单测 —— 这几个函数决定「旧会话存的 model 引用要不要升级成复合键、
 * 要不要提示用户重选 provider」，是 PR #324 的核心判定逻辑，必须锁住。
 */
private fun m(id: String, provider: String, alias: List<String> = emptyList()) =
    ModelEntry(id = id, provider = provider, alias = alias)

/** 两个 provider 提供同名 `glm-5.3`；deepseek-v3 带 alias。 */
private val MODELS = listOf(
    m("glm-5.3", "glm"),
    m("glm-5.3", "workbuddy"),
    m("glm-5.3-flash", "trae"),
    m("deepseek-v3", "glm", alias = listOf("ds")),
)

/** 聚合网关场景：provider `trae` 下的 model id 本身带 "/"。 */
private val SLASH_ID_MODEL = listOf(
    m("trae/glm-5.3-flash", "trae"),
    m("glm-5.3", "glm"),
)

class FullIdTest {

    @Test
    fun `复合键是 provider 加 id`() {
        assertEquals("glm/glm-5.3", m("glm-5.3", "glm").fullId)
    }

    @Test
    fun `provider 为空时退化为纯 id`() {
        assertEquals("glm-5.3", m("glm-5.3", "").fullId)
    }

    @Test
    fun `id 自身含斜杠时前缀照样拼`() {
        assertEquals("trae/trae/glm-5.3-flash", m("trae/glm-5.3-flash", "trae").fullId)
    }
}

class ResolveModelTest {

    @Test
    fun `精确复合键命中`() {
        assertEquals("glm/glm-5.3", MODELS.resolveModel("glm/glm-5.3")?.fullId)
    }

    @Test
    fun `纯 id 唯一命中时升级为复合键`() {
        assertEquals("trae/glm-5.3-flash", MODELS.resolveModel("glm-5.3-flash")?.fullId)
    }

    @Test
    fun `alias 唯一命中时升级`() {
        assertEquals("glm/deepseek-v3", MODELS.resolveModel("ds")?.fullId)
    }

    @Test
    fun `纯 id 命中多个同名模型时不猜_返回 null`() {
        assertNull(MODELS.resolveModel("glm-5.3"))
    }

    @Test
    fun `前缀写错时不 fall-through 到纯 id 匹配_返回 null`() {
        assertNull(MODELS.resolveModel("foo/glm-5.3"))
    }

    @Test
    fun `null 与空白返回 null`() {
        assertNull(MODELS.resolveModel(null))
        assertNull(MODELS.resolveModel(""))
        assertNull(MODELS.resolveModel("   "))
    }

    @Test
    fun `候选集为空时不命中`() {
        assertNull(emptyList<ModelEntry>().resolveModel("glm-5.3"))
    }

    /** 双斜杠：id 本身含 "/" 的模型，其复合键是 `provider/provider/id`。 */
    @Test
    fun `双斜杠复合键命中 id 含斜杠的那个模型`() {
        val hit = SLASH_ID_MODEL.resolveModel("trae/trae/glm-5.3-flash")
        assertEquals("trae/glm-5.3-flash", hit?.id)
        assertEquals("trae", hit?.provider)
    }

    /** 旧会话（#308 之前）存的是裸 id，而该 id 本身就带 "/"。 */
    @Test
    fun `旧格式的裸 id 含斜杠时仍能升级`() {
        assertEquals("trae/trae/glm-5.3-flash", SLASH_ID_MODEL.resolveModel("trae/glm-5.3-flash")?.fullId)
    }

    /**
     * 同一个 provider 下既有 id=`glm-5.3-flash` 又有 id=`trae/glm-5.3-flash` 时，
     * `trae/glm-5.3-flash` 这个引用两种解释都成立 —— 规则是「精确复合键优先」。
     * 两者都属于 trae，不会静默切到别的 provider，所以这个优先级是安全的。
     */
    @Test
    fun `引用同时像复合键又像裸 id 时_精确复合键优先`() {
        val collide = listOf(
            m("glm-5.3-flash", "trae"),
            m("trae/glm-5.3-flash", "trae"),
        )
        assertEquals("trae/glm-5.3-flash", collide.resolveModel("trae/glm-5.3-flash")?.fullId)
    }
}

class IsAmbiguousTest {

    @Test
    fun `纯 id 命中同名多个时歧义`() {
        assertTrue(MODELS.isAmbiguous("glm-5.3"))
    }

    @Test
    fun `精确复合键永远不歧义`() {
        assertFalse(MODELS.isAmbiguous("glm/glm-5.3"))
        assertFalse(MODELS.isAmbiguous("workbuddy/glm-5.3"))
    }

    @Test
    fun `纯 id 唯一命中时不歧义`() {
        assertFalse(MODELS.isAmbiguous("glm-5.3-flash"))
    }

    @Test
    fun `模型列表为空时不歧义_避免加载中误报`() {
        assertFalse(emptyList<ModelEntry>().isAmbiguous("glm-5.3"))
    }

    @Test
    fun `null 与空白不歧义`() {
        assertFalse(MODELS.isAmbiguous(null))
        assertFalse(MODELS.isAmbiguous(""))
    }

    @Test
    fun `id 含斜杠且多个 provider 同名时也算歧义`() {
        val dup = listOf(
            m("trae/glm-5.3-flash", "trae"),
            m("trae/glm-5.3-flash", "workbuddy"),
        )
        assertTrue(dup.isAmbiguous("trae/glm-5.3-flash"))
        assertNull(dup.resolveModel("trae/glm-5.3-flash"))
    }
}

class AmbiguousCandidatesTest {

    @Test
    fun `歧义时列出全部同名候选_供 UI 一键选择`() {
        val candidates = MODELS.ambiguousCandidates("glm-5.3")
        assertEquals(listOf("glm/glm-5.3", "workbuddy/glm-5.3"), candidates.map { it.fullId })
    }

    @Test
    fun `非歧义时不给候选`() {
        assertTrue(MODELS.ambiguousCandidates("workbuddy/glm-5.3").isEmpty())
        assertTrue(MODELS.ambiguousCandidates("glm-5.3-flash").isEmpty())
        assertTrue(MODELS.ambiguousCandidates(null).isEmpty())
        assertTrue(MODELS.ambiguousCandidates("").isEmpty())
    }

    @Test
    fun `候选里的每个 fullId 都能被 resolveModel 唯一解析_保证点一下就消除歧义`() {
        val candidates = MODELS.ambiguousCandidates("glm-5.3")
        assertTrue(candidates.isNotEmpty())
        for (c in candidates) {
            assertEquals(c, MODELS.resolveModel(c.fullId))
        }
    }
}
