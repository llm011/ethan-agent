package com.ethan.agent.ui.settings.components

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.kernel.KernelManager
import com.ethan.agent.core.kernel.KernelType

/**
 * 内核设置组件 - 支持运行时切换内核
 */
@Composable
fun KernelSettings(
    currentKernel: KernelType,
    onKernelChange: (KernelType) -> Unit,
    modifier: Modifier = Modifier,
) {
    var showRestartDialog by remember { mutableStateOf(false) }
    
    Column(modifier = modifier.fillMaxWidth()) {
        Text(
            text = "AI 内核",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
        )
        
        Spacer(modifier = Modifier.height(8.dp))
        
        Text(
            text = "选择 AI 模型后端，切换后需要重启应用",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        
        Spacer(modifier = Modifier.height(16.dp))
        
        // 内核选择器
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
            ),
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    text = "当前内核：${currentKernel.label}",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Medium,
                )
                
                Spacer(modifier = Modifier.height(12.dp))
                
                ExposedDropdownMenuBox(
                    expanded = false, // TODO: 实现下拉菜单状态
                    onExpandedChange = {},
                ) {
                    OutlinedTextField(
                        value = currentKernel.label,
                        onValueChange = {},
                        readOnly = true,
                        label = { Text("选择内核") },
                        modifier = Modifier.fillMaxWidth(),
                        trailingIcon = {
                            Icon(
                                imageVector = androidx.compose.material.icons.Icons.Default.ArrowDropDown,
                                contentDescription = "展开",
                            )
                        },
                    )
                    
                    ExposedDropdownMenu(
                        expanded = false,
                        onDismissRequest = {},
                    ) {
                        KernelType.entries.forEach { kernelType ->
                            DropdownMenuItem(
                                text = { Text(kernelType.label) },
                                onClick = {
                                    onKernelChange(kernelType)
                                    showRestartDialog = true
                                },
                            )
                        }
                    }
                }
                
                Spacer(modifier = Modifier.height(12.dp))
                
                // 内核说明
                when (currentKernel) {
                    KernelType.DSH -> {
                        Text(
                            text = "DeepSeek Harness - 高性能、低延迟，适合日常对话和快速任务",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                    KernelType.CLAUDE_SDK -> {
                        Text(
                            text = "Anthropic Claude - 高质量输出，适合复杂推理和内容创作",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                    KernelType.LEGACY -> {
                        Text(
                            text = "Ethan Legacy - 向后兼容模式，保留所有原有功能",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                }
            }
        }
        
        Spacer(modifier = Modifier.height(16.dp))
        
        // 高级配置（折叠）
        ExpandableConfigPanel()
    }
}

@Composable
private fun ExpandableConfigPanel() {
    var expanded by remember { mutableStateOf(false) }
    
    Column {
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { expanded = !expanded },
            color = MaterialTheme.colorScheme.surfaceVariant,
            shape = RoundedCornerShape(8.dp),
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(12.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "高级配置",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Medium,
                )
                Icon(
                    imageVector = if (expanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                    contentDescription = if (expanded) "收起" else "展开",
                )
            }
        }
        
        if (expanded) {
            Spacer(modifier = Modifier.height(8.dp))
            
            AdvancedKernelConfig()
        }
    }
}

@Composable
private fun AdvancedKernelConfig() {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            // DSH 配置
            DSHAdvancedConfig()
            
            HorizontalDivider(modifier = Modifier.padding(vertical = 12.dp))
            
            // Claude SDK 配置
            ClaudeSDKAdvancedConfig()
        }
    }
}

@Composable
private fun DSHAdvancedConfig() {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            text = "DSH 内核配置",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
        )
        
        Spacer(modifier = Modifier.height(8.dp))
        
        // 模型配置
        ModelSelectionField()
        
        Spacer(modifier = Modifier.height(12.dp))
        
        // Temperature
        SliderField(
            label = "Temperature",
            value = 0.7f,
            onValueChange = {},
            min = 0f,
            max = 1f,
        )
        
        Spacer(modifier = Modifier.height(12.dp))
        
        // Max Tokens
        TextField(
            label = "Max Tokens",
            value = "4096",
            onValueChange = {},
        )
    }
}

@Composable
private fun ClaudeSDKAdvancedConfig() {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            text = "Claude SDK 配置",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
        )
        
        Spacer(modifier = Modifier.height(8.dp))
        
        // API Key
        PasswordField(
            label = "API Key",
            value = "",
            onValueChange = {},
        )
        
        Spacer(modifier = Modifier.height(12.dp))
        
        // Model Selection
        ModelSelectionField(clients = listOf("claude-3-opus", "claude-3-sonnet"))
    }
}

@Composable
private fun ModelSelectionField(clients: List<String> = emptyList()) {
    var selectedModel by remember { mutableStateOf("deepseek-chat") }
    
    OutlinedTextField(
        value = selectedModel,
        onValueChange = { selectedModel = it },
        label = { Text("模型") },
        modifier = Modifier.fillMaxWidth(),
        enabled = clients.isEmpty(),
        readOnly = clients.isNotEmpty(),
        trailingIcon = {
            if (clients.isNotEmpty()) {
                ExposedDropdownMenuButton(expanded = false, onExpandedChange = {})
            }
        },
    )
}

@Composable
private fun SliderField(
    label: String,
    value: Float,
    onValueChange: (Float) -> Unit,
    min: Float = 0f,
    max: Float = 1f,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(text = label, style = MaterialTheme.typography.bodyMedium)
            Text(text = "%.2f".format(value), style = MaterialTheme.typography.bodySmall)
        }
        
        Slider(
            value = value,
            onValueChange = onValueChange,
            steps = 10,
            range = min..max,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun TextField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun PasswordField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
) {
    var passwordVisible by remember { mutableStateOf(false) }
    
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        modifier = Modifier.fillMaxWidth(),
        visualTransformation = if (passwordVisible) VisualTransformation.None else VisualTransformation.Password,
        trailingIcon = {
            IconButton(onClick = { passwordVisible = !passwordVisible }) {
                Icon(
                    imageVector = if (passwordVisible) Icons.Default.Visibility else Icons.Default.Invisible,
                    contentDescription = if (passwordVisible) "隐藏" else "显示",
                )
            }
        },
    )
}

// KernelType 扩展
enum class KernelType(val label: String) {
    DSH("DeepSeek Harness"),
    CLAUDE_SDK("Anthropic Claude"),
    LEGACY("Ethan Legacy");
    
    companion object {
        fun fromString(value: String): KernelType = entries.find { it.label == value } ?: DSH
    }
}
