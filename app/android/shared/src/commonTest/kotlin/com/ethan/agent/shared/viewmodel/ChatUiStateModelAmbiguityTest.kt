package com.ethan.agent.shared.viewmodel

import com.ethan.agent.core.model.ModelEntry
import com.ethan.agent.core.model.fullId
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * `ChatUiState.modelAmbiguous` / `ambiguousCandidates` 的派生语义单测。
 *
 * 背景（PR #324 评审 F1）：这两个值以前是**独立字段**，由 models / agentSettings /
 * session 三条并行缓存流各自写入，先到的流写下的值会被后到的流按旧快照覆盖，
 * 于是旧会话会出现「该报的没报、不该报的报死」。改成从 (models, selectedModel) 派生后，
 * 结果只取决于最终状态、与写入顺序无关 —— 这几个用例就是钉住这一点。
 */
private fun m(id: String, provider: String) = ModelEntry(id = id, provider = provider)

private val MODELS = listOf(
    m("glm-5.3", "glm"),
    m("glm-5.3", "workbuddy"),
    m("glm-5.3-flash", "trae"),
)

class ChatUiStateModelAmbiguityTest {

    @Test
    fun `旧会话存裸 id 且多 provider 同名时_歧义`() {
        val st = ChatUiState(models = MODELS, selectedModel = "glm-5.3", sessionId = "s1", title = "旧会话")
        assertTrue(st.modelAmbiguous)
        assertEquals(listOf("glm/glm-5.3", "workbuddy/glm-5.3"), st.ambiguousCandidates.map { it.fullId })
    }

    @Test
    fun `歧义态只取决于最终状态_与三条缓存流谁先到无关`() {
        // 同一个 (models, selectedModel)，一个像是「session 流后写」的历史，
        // 一个像是「agentSettings 流后写」的历史 —— 派生结果必须一致。
        val fromSession = ChatUiState(models = MODELS, selectedModel = "glm-5.3", sessionId = "s1", title = "旧会话")
        val fromSettings = ChatUiState(models = MODELS, selectedModel = "glm-5.3", isLoading = false)
        assertEquals(fromSession.modelAmbiguous, fromSettings.modelAmbiguous)
        assertEquals(fromSession.ambiguousCandidates, fromSettings.ambiguousCandidates)
        assertTrue(fromSession.modelAmbiguous)
    }

    @Test
    fun `显式选中候选后歧义消失_无需额外清标志位`() {
        val ambiguous = ChatUiState(models = MODELS, selectedModel = "glm-5.3")
        assertTrue(ambiguous.modelAmbiguous)
        // onModelSelected 现在只写 selectedModel，歧义由派生自动消除
        val picked = ambiguous.copy(selectedModel = "workbuddy/glm-5.3")
        assertFalse(picked.modelAmbiguous)
        assertTrue(picked.ambiguousCandidates.isEmpty())
    }

    @Test
    fun `模型列表未加载时不误报歧义`() {
        assertFalse(ChatUiState(selectedModel = "glm-5.3").modelAmbiguous)
    }

    @Test
    fun `没有选中模型时不歧义`() {
        assertFalse(ChatUiState(models = MODELS).modelAmbiguous)
        assertFalse(ChatUiState(models = MODELS, selectedModel = "").modelAmbiguous)
    }

    @Test
    fun `升级成复合键后不再歧义`() {
        // 唯一命中的裸 id（trae/glm-5.3-flash）升级后不该再顶着歧义位
        val upgraded = ChatUiState(models = MODELS, selectedModel = "trae/glm-5.3-flash")
        assertFalse(upgraded.modelAmbiguous)
    }
}
