package com.ethan.agent.core.model

/**
 * 模型选择的纯逻辑 —— 照搬 Web/Desktop 共享组件 `packages/shared/src/ui/model-select.tsx`
 * 与 `web/components/chat/chat-input.tsx:203` 的同名语义。
 *
 * 三端必须一致，否则会出现「Web 上选得好好的，Android 上选到另一个 provider」这类
 * 静默串号问题（隐私/计费都可能出错）。
 *
 * 核心概念：
 * - **fullId**：`provider/id` 复合格式。同一模型可能被多个 provider 提供（同名不同源），
 *   裸 id 无法区分，所以聊天输入框用 fullId 作为选中值。后端 `providers/manager.py`
 *   的 `model_id.split("/", 1)` 正好认这个格式。
 * - **displayName**：给用户看的名字。优先用户填的 alias，其次描述，最后才回退到 id。
 */
object ModelSelection {

    /** 重名待重选的哨兵值 —— 对应 Web 的 `NEED_CHOICE`。 */
    const val NEED_CHOICE = "__need_model_choice__"

    /** 复合 ID：`provider/id`；没有 provider 时退化为裸 id。 */
    fun fullIdOf(model: ModelEntry): String =
        if (model.provider.isNotBlank()) "${model.provider}/${model.id}" else model.id

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

    /** 按 fullId 精确命中，找不到再按裸 id 兜底（兼容存量会话里存的裸 id）。 */
    fun findById(models: List<ModelEntry>, value: String?): ModelEntry? {
        if (value.isNullOrBlank()) return null
        return models.firstOrNull { fullIdOf(it) == value }
            ?: models.firstOrNull { it.id == value }
    }

    /**
     * 把可能来自存量配置/会话的值解析成合法的 fullId。
     *
     * 与 Web 的 `effectiveModelValue` 逐条对应：
     * 1. 已是某个模型的 fullId → 原样返回；
     * 2. 裸 id 唯一命中 → **安全升级**为对应 fullId（老会话、老配置都能正确高亮）；
     * 3. 裸 id 命中多个同名 → 返回 [NEED_CHOICE]，不猜（交给用户显式选，避免静默串到
     *    另一个 provider）；
     * 4. 什么都没命中 → 原样返回，让触发按钮显示原始值而不是退化成占位符，
     *    用户至少能看出当前状态不对劲。
     */
    fun effectiveValue(models: List<ModelEntry>, selected: String?): String {
        if (selected.isNullOrBlank()) return ""
        if (models.any { fullIdOf(it) == selected }) return selected
        val hits = models.filter { it.id == selected }
        return when {
            hits.size == 1 -> fullIdOf(hits[0])
            hits.size > 1 -> NEED_CHOICE
            else -> selected
        }
    }

    /** 该选中值是否是「重名待重选」状态（用于展示提示文案与禁用发送）。 */
    fun isAmbiguous(models: List<ModelEntry>, selected: String?): Boolean =
        !selected.isNullOrBlank() &&
            models.none { fullIdOf(it) == selected } &&
            models.count { it.id == selected } > 1
}
