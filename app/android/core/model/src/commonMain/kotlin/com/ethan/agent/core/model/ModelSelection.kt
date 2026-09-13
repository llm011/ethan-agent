package com.ethan.agent.core.model

/**
 * 模型选择的**展示层**入口 —— 照搬 Web/Desktop 共享组件
 * `packages/shared/src/ui/model-select.tsx` 与 `web/components/chat/chat-input.tsx` 的同名语义。
 *
 * 三端必须一致，否则会出现「Web 上选得好好的，Android 上选到另一个 provider」这类
 * 静默串号问题（隐私/计费都可能出错）。
 *
 * ## 匹配语义不在本文件里
 *
 * 真正「一个 ref 命中哪些模型」的判定**只有一份**，在 [modelCandidates] 系
 * （[resolveModel] / [isAmbiguous] / [ambiguousCandidates]，见 `Models.kt`）。
 * 本对象只负责展示名与「取什么值」的取舍，凡是涉及匹配的都必须委托过去 ——
 * 之前这里另写了一套 `id == selected` 的匹配，与 canonical 实现并存的结果是：
 * 同一份 `selectedModel`，`ChatUiState.modelAmbiguous`（走 canonical）说歧义、
 * 下拉框（走本对象）说不歧义，于是 UI 不禁发送、后端静默挑了个 provider。
 * 这种分叉不会再犯：[ModelSelectionTest] 里有一组用例逐条比对两套结论。
 *
 * 核心概念：
 * - **fullId**：`provider/id` 复合格式（[ModelEntry.fullId]）。同一模型可能被多个
 *   provider 提供（同名不同源），裸 id 无法区分，所以聊天输入框用 fullId 作为选中值。
 * - **displayName**：给用户看的名字。优先用户填的 alias，其次描述，最后才回退到 id。
 */
object ModelSelection {

    /** 重名待重选的哨兵值 —— 对应 Web 的 `NEED_CHOICE`。 */
    const val NEED_CHOICE = "__need_model_choice__"

    /** 复合 ID：`provider/id`；没有 provider 时退化为裸 id。直接复用 [ModelEntry.fullId]。 */
    fun fullIdOf(model: ModelEntry): String = model.fullId

    /**
     * 展示名：alias[0] → description → id。
     *
     * 之前 Android 直接用 `model.id`，于是列表里满屏 `ep-20251218165528-tt2hm` 这种
     * 机器 ID —— 而 Web 上同一个模型显示的是可读的别名。
     */
    fun displayNameOf(model: ModelEntry): String =
        model.alias.firstOrNull()?.takeIf { it.isNotBlank() }
            ?: model.description.takeIf { it.isNotBlank() }
            ?: model.id

    /**
     * 按 ref 找唯一模型：复合键 `provider/id`、裸 id、alias 都认（见 [modelCandidates]）。
     *
     * **歧义时返回 null 而不是「第一个命中的」** —— 后果不同：返回第一个等于替用户
     * 静默选了个 provider，返回 null 上层才会去提示「请指定一个」。
     */
    fun findById(models: List<ModelEntry>, value: String?): ModelEntry? = models.resolveModel(value)

    /**
     * 把可能来自存量配置/会话的值解析成合法的 fullId。
     *
     * 与 Web 的 `effectiveModelValue` 逐条对应：
     * 1. 已是某个模型的 fullId → 原样返回；
     * 2. 裸 id / alias 唯一命中 → **安全升级**为对应 fullId（老会话、老配置都能正确高亮）；
     * 3. 命中多个同名 → 返回 [NEED_CHOICE]，不猜（交给用户显式选，避免静默串到
     *    另一个 provider）；
     * 4. 什么都没命中 → 原样返回，让触发按钮显示原始值而不是退化成占位符，
     *    用户至少能看出当前状态不对劲。
     */
    fun effectiveValue(models: List<ModelEntry>, selected: String?): String {
        // 空白是「未选择」，与「选中了一个列表里没有的值」是两回事，不能混。
        if (selected.isNullOrBlank()) return ""
        val hits = models.modelCandidates(selected)
        return when (hits.size) {
            1 -> hits.single().fullId
            in 2..Int.MAX_VALUE -> NEED_CHOICE
            else -> selected
        }
    }

    /** 该选中值是否是「重名待重选」状态（用于展示提示文案与禁用发送）。 */
    fun isAmbiguous(models: List<ModelEntry>, selected: String?): Boolean = models.isAmbiguous(selected)
}
