package com.ethan.agent.ui.components

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.width
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.ModelEntry
import com.ethan.agent.core.model.ModelSelection

/**
 * 模型下拉框 —— 展示 alias / description 而不是裸 id，右侧标 provider 消歧，
 * 选中值是 `provider/id` 复合格式（[ModelSelection.fullIdOf]）。
 *
 * 对话页的「模型」和设置页的「默认模型 / 轻量模型」共用这一个组件。三处如果各写一套，
 * 很容易出现「Web 上选得好好的、Android 上选到另一个 provider」的静默串号
 * —— 同名模型可能被多个 provider 提供，隐私和计费都会出错（详见 [ModelSelection]）。
 *
 * @param models 可选模型列表；为空时显示「暂无模型」且不可选
 * @param value 当前选中值，可以是裸 id（存量配置）或 fullId；内部走
 *   [ModelSelection.effectiveValue] 做安全升级
 * @param onValueChange 选中回调，值的形式由 [valueMode] 决定
 * @param valueMode 回调值的形式：默认 [ModelDropdownValueMode.FullId]（`provider/id`），
 *   传给后端的配置项要用 [ModelDropdownValueMode.Id]（裸 id）—— 见下方说明。
 */
enum class ModelDropdownValueMode {
    /** 回调 `provider/id`。会话的 selectedModel 用这个（同名模型跨 provider 必须能区分）。 */
    FullId,

    /** 回调裸 `id`。后端配置字段（defaults.model / defaults.lite_model）只认裸 id。 */
    Id,
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ModelDropdown(
    models: List<ModelEntry>,
    value: String?,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    label: String? = null,
    placeholder: String = "选择模型",
    valueMode: ModelDropdownValueMode = ModelDropdownValueMode.FullId,
    /** 是否允许「留空」选项（配置项如 lite_model 留空 = 跟随主模型推断）。 */
    allowEmpty: Boolean = false,
    /** allowEmpty 时留空项的文案。 */
    emptyLabel: String = "留空（自动推断）",
) {
    var expanded by remember { mutableStateOf(false) }

    // id 模式下是否有跨 provider 的同名模型 —— 它们的裸 id 会撞车，必须临时用
    // provider/id 做 item 匹配，回调时再拆回裸 id。对齐 Web 的 hasIdCollision。
    val hasIdCollision = remember(models, valueMode) {
        valueMode == ModelDropdownValueMode.Id && models.map { it.id }.distinct().size != models.size
    }

    val effectiveValue = remember(models, value, valueMode, hasIdCollision) {
        when {
            // id 模式且无重名：原样使用，不做 fullId 升级（配置里存的就是裸 id）
            valueMode == ModelDropdownValueMode.Id && !hasIdCollision -> value.orEmpty()
            // 其余走通用升级：fullId 原样；裸 id 唯一命中 → 升级；重名 → NEED_CHOICE
            else -> ModelSelection.effectiveValue(models, value)
        }
    }
    val ambiguous = remember(models, value, hasIdCollision) {
        valueMode == ModelDropdownValueMode.FullId && ModelSelection.isAmbiguous(models, value)
    }
    val current = remember(models, effectiveValue) {
        ModelSelection.findById(models, effectiveValue)
    }

    val fieldText = when {
        ambiguous -> "有多个 provider 提供该模型，请指定一个"
        current != null -> ModelSelection.displayNameOf(current)
        // 匹配不到就显示原始值，别退化成占位符 —— 用户至少能看出当前状态不对劲
        !value.isNullOrBlank() -> value
        // 留空是独立语义（跟随默认），要显式说明，不能混成「未选择」
        allowEmpty -> emptyLabel
        else -> ""
    }
    // 消歧标注跟在选中名下面，和列表项右侧的 provider 标注一致
    val providerLabel = current?.provider?.takeIf { it.isNotBlank() }

    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = { expanded = it },
        modifier = modifier,
    ) {
        OutlinedTextField(
            value = fieldText,
            onValueChange = {},
            readOnly = true,
            singleLine = true,
            label = label?.let { { Text(it) } },
            placeholder = { Text(placeholder) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            supportingText = if (providerLabel != null) {
                { Text(providerLabel) }
            } else null,
            shape = MaterialTheme.shapes.small,
            modifier = Modifier
                .menuAnchor(MenuAnchorType.PrimaryNotEditable)
                .fillMaxWidth(),
        )
        ExposedDropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
            modifier = Modifier.heightIn(max = 360.dp),
        ) {
            if (models.isEmpty()) {
                DropdownMenuItem(
                    text = { Text("暂无模型", color = MaterialTheme.colorScheme.onSurfaceVariant) },
                    onClick = {},
                    enabled = false,
                )
            }
            if (allowEmpty) {
                DropdownMenuItem(
                    text = { Text(emptyLabel) },
                    onClick = {
                        onValueChange("")
                        expanded = false
                    },
                )
            }
            models.forEach { model ->
                DropdownMenuItem(
                    text = {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                ModelSelection.displayNameOf(model),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f, fill = false),
                            )
                            if (model.provider.isNotBlank()) {
                                Spacer(Modifier.width(8.dp))
                                Text(
                                    model.provider,
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                                    maxLines = 1,
                                    modifier = Modifier.weight(1f),
                                )
                            }
                        }
                    },
                    onClick = {
                        // 对外一律按 valueMode 约定给值：会话要 fullId（区分同名跨
                        // provider），配置项要裸 id（后端 defaults.model 只认裸 id）。
                        val out = when (valueMode) {
                            ModelDropdownValueMode.FullId -> ModelSelection.fullIdOf(model)
                            ModelDropdownValueMode.Id -> model.id
                        }
                        onValueChange(out)
                        expanded = false
                    },
                )
            }
        }
    }
}
