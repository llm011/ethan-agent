package com.ethan.agent.core.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * [ModelSelection] 的单测。
 *
 * 这个对象是 UI 侧取值/展示的入口（对话页与设置页的模型下拉框都走它），
 * 匹配语义必须与同包的 [modelCandidates] 系（[resolveModel] / [isAmbiguous]）**完全一致** ——
 * 两套口径分叉的表现是「下拉框说选中了某个 provider，聊天页却提示重名待选」。
 * 下面最后一组用例就是专门钉住这层委托关系的。
 */
private fun entry(id: String, provider: String, alias: List<String> = emptyList(), description: String = "") =
    ModelEntry(id = id, provider = provider, alias = alias, description = description)

private val SELECTION_MODELS = listOf(
    entry("glm-5.3", "glm"),
    entry("glm-5.3", "workbuddy"),
    entry("glm-5.3-flash", "trae"),
    entry("deepseek-v3", "glm", alias = listOf("ds")),
)

/** id 本身含 "/"：同一个 provider 下两个模型的引用长得几乎一样。 */
private val SLASH_MODELS = listOf(
    entry("glm-5.3-flash", "trae"),
    entry("trae/glm-5.3-flash", "trae"),
)

class ModelSelectionFullIdTest {

    @Test
    fun `fullIdOf 与 Models_kt 的 fullId 完全一致`() {
        assertEquals(entry("glm-5.3", "glm").fullId, ModelSelection.fullIdOf(entry("glm-5.3", "glm")))
        assertEquals("glm-5.3", ModelSelection.fullIdOf(entry("glm-5.3", "")))
        assertEquals("trae/trae/glm-5.3-flash", ModelSelection.fullIdOf(entry("trae/glm-5.3-flash", "trae")))
    }
}

class ModelSelectionDisplayNameTest {

    @Test
    fun `展示名按 alias 到 description 到 id 依次回退`() {
        assertEquals("ds", ModelSelection.displayNameOf(entry("deepseek-v3", "glm", alias = listOf("ds"))))
        assertEquals("描述", ModelSelection.displayNameOf(entry("raw-id", "glm", description = "描述")))
        assertEquals("raw-id", ModelSelection.displayNameOf(entry("raw-id", "glm")))
        // alias 里是空白串时不能把空白当名字用
        assertEquals("raw-id", ModelSelection.displayNameOf(entry("raw-id", "glm", alias = listOf("  "))))
    }
}

class ModelSelectionEffectiveValueTest {

    @Test
    fun `空白输入返回空串`() {
        assertEquals("", ModelSelection.effectiveValue(SELECTION_MODELS, null))
        assertEquals("", ModelSelection.effectiveValue(SELECTION_MODELS, ""))
        assertEquals("", ModelSelection.effectiveValue(SELECTION_MODELS, "   "))
    }

    @Test
    fun `已经是复合键就原样返回`() {
        assertEquals("glm/glm-5.3", ModelSelection.effectiveValue(SELECTION_MODELS, "glm/glm-5.3"))
    }

    @Test
    fun `裸 id 唯一命中时升级成复合键`() {
        assertEquals("trae/glm-5.3-flash", ModelSelection.effectiveValue(SELECTION_MODELS, "glm-5.3-flash"))
    }

    @Test
    fun `alias 也能解析出复合键`() {
        assertEquals("glm/deepseek-v3", ModelSelection.effectiveValue(SELECTION_MODELS, "ds"))
    }

    @Test
    fun `裸 id 命中同名多个时返回哨兵值不猜`() {
        assertEquals(ModelSelection.NEED_CHOICE, ModelSelection.effectiveValue(SELECTION_MODELS, "glm-5.3"))
    }

    @Test
    fun `什么都没命中时原样返回_让用户看出状态不对劲`() {
        assertEquals("nope", ModelSelection.effectiveValue(SELECTION_MODELS, "nope"))
    }

    @Test
    fun `id 含斜杠的引用按精确复合键优先_不误判为歧义`() {
        assertEquals("trae/glm-5.3-flash", ModelSelection.effectiveValue(SLASH_MODELS, "trae/glm-5.3-flash"))
    }
}

class ModelSelectionAmbiguityTest {

    @Test
    fun `裸 id 同名多个算歧义`() {
        assertTrue(ModelSelection.isAmbiguous(SELECTION_MODELS, "glm-5.3"))
    }

    @Test
    fun `精确复合键不算歧义`() {
        assertFalse(ModelSelection.isAmbiguous(SELECTION_MODELS, "glm/glm-5.3"))
        assertFalse(ModelSelection.isAmbiguous(SELECTION_MODELS, "workbuddy/glm-5.3"))
    }

    @Test
    fun `alias 命中唯一模型时不算歧义`() {
        assertFalse(ModelSelection.isAmbiguous(SELECTION_MODELS, "ds"))
    }

    @Test
    fun `null 空白与空列表都不算歧义`() {
        assertFalse(ModelSelection.isAmbiguous(SELECTION_MODELS, null))
        assertFalse(ModelSelection.isAmbiguous(SELECTION_MODELS, ""))
        assertFalse(ModelSelection.isAmbiguous(emptyList(), "glm-5.3"))
    }

    @Test
    fun `findById 歧义时返回 null_不替用户猜 provider`() {
        assertNull(ModelSelection.findById(SELECTION_MODELS, "glm-5.3"))
        assertNull(ModelSelection.findById(SELECTION_MODELS, null))
    }

    @Test
    fun `findById 复合键 裸 id alias 都能命中`() {
        assertEquals("workbuddy", ModelSelection.findById(SELECTION_MODELS, "workbuddy/glm-5.3")?.provider)
        assertEquals("trae", ModelSelection.findById(SELECTION_MODELS, "glm-5.3-flash")?.provider)
        assertEquals("deepseek-v3", ModelSelection.findById(SELECTION_MODELS, "ds")?.id)
    }

    /**
     * 委托一致性：本对象与 `modelCandidates` 系对同一批引用必须给出同样的结论。
     * 有人日后把匹配逻辑在这里重新实现一遍（而不是委托），这条会立刻挂。
     */
    @Test
    fun `判定与 Models_kt 的 canonical 实现逐条一致`() {
        val refs = listOf(
            null, "", "   ", "glm-5.3", "glm/glm-5.3", "workbuddy/glm-5.3",
            "glm-5.3-flash", "trae/glm-5.3-flash", "ds", "nope", "foo/glm-5.3",
        )
        for (ref in refs) {
            assertEquals(
                SELECTION_MODELS.isAmbiguous(ref),
                ModelSelection.isAmbiguous(SELECTION_MODELS, ref),
                "isAmbiguous 口径分叉：ref=$ref",
            )
            val effective = ModelSelection.effectiveValue(SELECTION_MODELS, ref)
            // 空白是「未选择」，canonical 那套里 modelCandidates 返回空集合、isAmbiguous 为 false，
            // 单看这两个推不出「要归成空串」，所以这条单独写：口径对齐但不合并语义。
            val expected = if (ref.isNullOrBlank()) {
                ""
            } else {
                SELECTION_MODELS.resolveModel(ref)?.fullId
                    ?: if (SELECTION_MODELS.isAmbiguous(ref)) ModelSelection.NEED_CHOICE else ref
            }
            assertEquals(expected, effective, "effectiveValue 口径分叉：ref=$ref")
        }
    }
}
