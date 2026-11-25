package com.ethan.agent.ui.chat

import com.ethan.agent.shared.viewmodel.ChatUiState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.heightIn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Shield
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ethan.agent.ui.components.ModelDropdown

/** Model, mode, and attachment options shown from the input toolbar. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ChatOptionsSheet(
    state: ChatUiState,
    onModelSelected: (String) -> Unit,
    onModeSelected: (String) -> Unit,
    onPickFile: () -> Unit,
    onClose: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState()
    ModalBottomSheet(
        onDismissRequest = { onClose() },
        sheetState = sheetState,
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text("选项", style = MaterialTheme.typography.titleMedium)

            // Upload section
            Surface(
                onClick = { onPickFile(); onClose() },
                shape = MaterialTheme.shapes.small,
                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Row(
                    modifier = Modifier.padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Icon(Icons.Default.AttachFile, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                    Text("上传图片/文件")
                }
            }

            HorizontalDivider()

            // 模型选择器 —— 对齐 Web 的 ModelSelect：
            // 显示 alias/description 而非裸 id，右侧标 provider 消歧，选中值为 provider/id。
            // 组件化后与设置页的「默认模型 / 轻量模型」共用同一份实现。
            Text("模型", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (state.modelAmbiguous) {
                Text(
                    "该模型在多个 provider 下重名，请从下方列表选择要使用的 provider",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            ModelDropdown(
                models = state.models,
                value = state.selectedModel,
                onValueChange = onModelSelected,
            )

            // 模式选择器 —— Web 上是单个下拉（不是一排 chip）。原来用 Row 排 FilterChip，
            // 选项一多就把最后一个挤到只剩一个字宽换行，窄屏尤其明显。
            if (state.modes.isNotEmpty()) {
                Text("模式", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                var modeExpanded by remember { mutableStateOf(false) }
                val currentMode = remember(state.modes, state.selectedMode) {
                    state.modes.firstOrNull { it.key == state.selectedMode }
                }
                ExposedDropdownMenuBox(expanded = modeExpanded, onExpandedChange = { modeExpanded = it }) {
                    OutlinedTextField(
                        value = currentMode?.label ?: "",
                        onValueChange = {},
                        readOnly = true,
                        singleLine = true,
                        placeholder = { Text("模式") },
                        leadingIcon = currentMode?.icon?.takeIf { it.isNotBlank() }?.let { icon ->
                            { Text(icon) }
                        },
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = modeExpanded) },
                        modifier = Modifier.menuAnchor(MenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
                    )
                    ExposedDropdownMenu(
                        expanded = modeExpanded,
                        onDismissRequest = { modeExpanded = false },
                        modifier = Modifier.heightIn(max = 360.dp),
                    ) {
                        // 首项是「不指定模式」——对应 Web 的 `__default__` 空选项
                        DropdownMenuItem(
                            text = { Text("默认（不指定）") },
                            onClick = {
                                onModeSelected("")
                                modeExpanded = false
                            },
                        )
                        state.modes.forEach { mode ->
                            DropdownMenuItem(
                                text = {
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        if (mode.icon.isNotBlank()) {
                                            Text(mode.icon)
                                            Spacer(Modifier.width(8.dp))
                                        }
                                        Text(mode.label)
                                    }
                                },
                                onClick = {
                                    onModeSelected(mode.key)
                                    modeExpanded = false
                                },
                            )
                        }
                    }
                }
            }

            Spacer(Modifier.height(16.dp))
        }
    }
}

/** Server-driven onboarding, consent, choice, and wait-for-user dialogs. */
@Composable
internal fun ChatInteractionDialogs(
    state: ChatUiState,
    onOnboardingChange: (String, String) -> Unit,
    onCompleteOnboarding: () -> Unit,
    onDismissOnboarding: () -> Unit,
    onConsent: (Boolean) -> Unit,
    onDismissConsent: () -> Unit,
    onAskUserRespond: (String) -> Unit,
    onWaitForUserRespond: (String) -> Unit,
) {
    if (state.showOnboarding) {
        AlertDialog(
            onDismissRequest = onDismissOnboarding,
            title = { Text("欢迎使用 Ethan") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(state.onboarding?.message ?: "为你的 Agent 取个名字吧")
                    OutlinedTextField(
                        value = state.agentName,
                        onValueChange = { onOnboardingChange(it, state.userInfo) },
                        label = { Text("Agent 名称") },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = state.userInfo,
                        onValueChange = { onOnboardingChange(state.agentName, it) },
                        label = { Text("自我介绍") },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 3,
                    )
                }
            },
            confirmButton = { TextButton(onClick = onCompleteOnboarding) { Text("完成") } },
            dismissButton = { TextButton(onClick = onDismissOnboarding) { Text("跳过") } },
        )
    }

    state.consent?.let { consent ->
        AlertDialog(
            onDismissRequest = onDismissConsent,
            title = { Text("需要授权: ${consent.tool}") },
            text = {
                Column {
                    Text(consent.description)
                    consent.detail?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                }
            },
            confirmButton = { TextButton(onClick = { onConsent(true) }) { Text("允许") } },
            dismissButton = { TextButton(onClick = { onConsent(false) }) { Text("拒绝") } },
        )
    }

    // ask_user 选择卡片：问题 + 选项 + 倒计时（超时后端走 default，这里同步展示）
    state.askUser?.let { ask ->
        AlertDialog(
            onDismissRequest = { /* 不可关闭：必须选择，超时自动走默认 */ },
            title = { Text(ask.question) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    if (ask.options.isEmpty()) {
                        // 后端校验回传值必须在 options 内（空 options 时任何回传都会 400），
                        // 无法提供按钮；超时后只清卡片、不回传，由后端超时机制走默认值
                        Text(
                            "无可选选项，${state.askUserRemaining}s 后由服务端按默认值处理",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        ask.options.forEach { opt ->
                            TextButton(
                                onClick = { onAskUserRespond(opt.value) },
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text(
                                    text = opt.label + if (opt.value == ask.default) "（默认）" else "",
                                    modifier = Modifier.fillMaxWidth(),
                                    textAlign = TextAlign.Start,
                                )
                            }
                        }
                        Text(
                            "${state.askUserRemaining}s 后自动选择默认项",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            },
            confirmButton = {},
        )
    }

    // wait_for_user 等待卡片：确认/取消（或文本输入）+ 倒计时
    state.waitForUser?.let { wfu ->
        var textValue by remember(wfu.requestId) { mutableStateOf("") }
        val isText = wfu.inputType == "text"
        AlertDialog(
            onDismissRequest = { /* 不可关闭：必须确认/取消，超时自动回传 timeout */ },
            title = { Text(wfu.prompt, style = MaterialTheme.typography.titleSmall) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (isText) {
                        OutlinedTextField(
                            value = textValue,
                            onValueChange = { textValue = it },
                            placeholder = { Text(wfu.placeholder.ifBlank { "请输入…" }) },
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    Text(
                        "${formatRemainingSeconds(state.waitForUserRemaining)}后超时",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        onWaitForUserRespond(if (isText) textValue.trim().ifBlank { "done" } else "done")
                    },
                ) { Text(wfu.confirmLabel) }
            },
            dismissButton = {
                TextButton(onClick = { onWaitForUserRespond("cancel") }) { Text(wfu.cancelLabel) }
            },
        )
    }
}

/** wait_for_user 倒计时展示：>=60s 显示「M分S秒」，否则「Ns」。 */
private fun formatRemainingSeconds(seconds: Int): String = when {
    seconds >= 60 -> "${seconds / 60}分${seconds % 60}秒"
    else -> "${seconds}秒"
}

/** Enabling automatic consent requires a deliberate confirmation; disabling does not. */
@Composable
internal fun ChatAutoConsentConfirmation(onClose: () -> Unit, onToggleAutoConsent: () -> Unit) {
    AlertDialog(
        onDismissRequest = { onClose() },
        icon = { Icon(Icons.Default.Shield, contentDescription = null) },
        title = { Text("开启超级权限？") },
        text = {
            Text(
                "开启后，普通工具授权（读写文件、执行普通 shell 命令等）将不再弹窗，" +
                    "直接放行；高危命令（rm -rf 等）仍会确认。\n\n" +
                    "请确认你了解当前正在对话的 Agent 会做什么。",
            )
        },
        confirmButton = {
            TextButton(onClick = {
                onClose()
                onToggleAutoConsent()
            }) { Text("开启") }
        },
        dismissButton = {
            TextButton(onClick = { onClose() }) { Text("取消") }
        },
    )
}
