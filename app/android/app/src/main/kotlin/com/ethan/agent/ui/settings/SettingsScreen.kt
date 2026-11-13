package com.ethan.agent.ui.settings

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp

/**
 * 系统设置主屏幕 - 按功能模块清晰分类
 * 
 * 设计理念：
 * 1. **用户导向** - 按用户使用场景分组，而非技术实现
 * 2. **渐进披露** - 常用功能在前，高级功能折叠
 * 3. **即时生效** - 所有修改实时应用，无需重启（除非必要）
 * 4. **智能默认** - 提供合理的默认值，减少配置负担
 */

sealed class SettingsCategory(
    val title: String,
    val icon: ImageVector,
    val order: Int,
) {
    data object Connection : SettingsCategory("连接与账户", Icons.Default.Cloud, 1)
    data object Appearance : SettingsCategory("外观与体验", Icons.Default.Palette, 2)
    data object Performance : SettingsCategory("性能与缓存", Icons.Default.Speed, 3)
    data object Privacy : SettingsCategory("隐私与安全", Icons.Default.Lock, 4)
    data object Data : SettingsCategory("数据管理", Icons.Default.Storage, 5)
    data object Advanced : SettingsCategory("高级配置", Icons.Default.Tune, 6)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var selectedTab by remember { mutableStateOf(0) }
    
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("设置") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
    ) { paddingValues ->
        Column(modifier = modifier.fillMaxSize().padding(paddingValues)) {
            // Tab 导航
            TabRow(
                selectedTabIndex = selectedTab,
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
            ) {
                SettingsCategory.entries.sortedBy { it.order }.forEach { category ->
                    Tab(
                        selected = selectedTab == category.ordinal,
                        onClick = { selectedTab = category.ordinal },
                        text = { Text(category.title) },
                        icon = { Icon(category.icon, contentDescription = null) },
                    )
                }
            }
            
            // 内容区域
            when (selectedTab) {
                0 -> ConnectionSettings()
                1 -> AppearanceSettings()
                2 -> PerformanceSettings()
                3 -> PrivacySettings()
                4 -> DataManagementSettings()
                5 -> AdvancedSettings()
            }
        }
    }
}

// ========== 连接与账户 ==========

@Composable
private fun ConnectionSettings() {
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text(
            text = "连接与账户",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
        )
        
        Spacer(modifier = Modifier.height(8.dp))
        
        Text(
            text = "管理服务器连接、认证Token 和账户信息",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 服务器配置
        SectionHeader(title = "服务器配置")
        
        ServerUrlField()
        
        Spacer(modifier = Modifier.height(16.dp))
        
        AuthTokenField()
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 账户信息
        SectionHeader(title = "账户信息")
        
        UserProfileCard()
        
        Spacer(modifier = Modifier.height(16.dp))
        
        // 测试连接
        Button(
            onClick = { /* TODO: 测试连接 */ },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Icon(Icons.Default.CheckCircle, contentDescription = null)
            Spacer(modifier = Modifier.width(8.dp))
            Text("测试连接")
        }
    }
}

// ========== 外观与体验 ==========

@Composable
private fun AppearanceSettings() {
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text(
            text = "外观与体验",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
        )
        
        Spacer(modifier = Modifier.height(8.dp))
        
        Text(
            text = "自定义界面主题、字体和交互体验",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 主题设置
        SectionHeader(title = "主题")
        
        ThemeSelector()
        
        Spacer(modifier = Modifier.height(16.dp))
        
        // 深色模式
        DarkModeToggle()
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 字体大小
        SectionHeader(title = "字体")
        
        FontSizeSlider()
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 动画效果
        SectionHeader(title = "动画")
        
        AnimationQualitySwitch()
    }
}

// ========== 性能与缓存 ==========

@Composable
private fun PerformanceSettings() {
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text(
            text = "性能与缓存",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
        )
        
        Spacer(modifier = Modifier.height(8.dp))
        
        Text(
            text = "优化应用性能和存储空间",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // AI 内核选择
        SectionHeader(title = "AI 内核")
        
        KernelTypeSelector()
        
        Spacer(modifier = Modifier.height(16.dp))
        
        // 并发任务数
        ConcurrentTasksSlider()
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 缓存管理
        SectionHeader(title = "缓存管理")
        
        CacheUsageCard()
        
        ClearCacheButton()
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 自动清理
        AutoCleanupToggle()
    }
}

// ========== 隐私与安全 ==========

@Composable
private fun PrivacySettings() {
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text(
            text = "隐私与安全",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
        )
        
        Spacer(modifier = Modifier.height(8.dp))
        
        Text(
            text = "保护您的数据和隐私安全",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 生物识别锁
        SectionHeader(title = "设备安全")
        
        BiometricLockToggle()
        
        Spacer(modifier = Modifier.height(16.dp))
        
        PINLockToggle()
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 数据加密
        SectionHeader(title = "数据安全")
        
        EncryptionStatusCard()
        
        Spacer(modifier = Modifier.height(16.dp))
        
        // 权限管理
        SectionHeader(title = "应用权限")
        
        PermissionList()
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 会话授权
        SectionHeader(title = "会话授权")
        
        ConsentManagementCard()
    }
}

// ========== 数据管理 ==========

@Composable
private fun DataManagementSettings() {
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text(
            text = "数据管理",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
        )
        
        Spacer(modifier = Modifier.height(8.dp))
        
        Text(
            text = "管理您的对话历史、知识和配置文件",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 会话管理
        SectionHeader(title = "对话历史")
        
        SessionsManagementCard()
        
        Spacer(modifier = Modifier.height(16.dp))
        
        // 知识库
        SectionHeader(title = "知识库")
        
        KnowledgeBaseCard()
        
        Spacer(modifier = Modifier.height(16.dp))
        
        // 记忆管理
        SectionHeader(title = "长期记忆")
        
        MemoryManagementCard()
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 导出/导入
        SectionHeader(title = "数据迁移")
        
        ExportDataButton()
        
        Spacer(modifier = Modifier.height(8.dp))
        
        ImportDataButton()
    }
}

// ========== 高级配置 ==========

@Composable
private fun AdvancedSettings() {
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text(
            text = "高级配置",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
        )
        
        Spacer(modifier = Modifier.height(8.dp))
        
        Text(
            text = "开发者选项和高级功能配置",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 调试选项
        SectionHeader(title = "调试")
        
        DebugLoggingToggle()
        
        Spacer(modifier = Modifier.height(16.dp))
        
        NetworkProfilerToggle()
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 插件管理
        SectionHeader(title = "插件系统")
        
        PluginManagerCard()
        
        Spacer(modifier = Modifier.height(16.dp))
        
        // 内核配置
        SectionHeader(title = "内核高级配置")
        
        DSHAdvancedConfig()
        
        Spacer(modifier = Modifier.height(16.dp))
        
        ClaudeSDKAdvancedConfig()
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 网络代理
        SectionHeader(title = "网络")
        
        ProxySettings()
        
        Spacer(modifier = Modifier.height(24.dp))
        
        // 关于
        SectionHeader(title = "关于")
        
        AboutSection()
    }
}

// ========== 通用组件 ==========

@Composable
private fun SectionHeader(title: String) {
    Text(
        text = title,
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.Medium,
        color = MaterialTheme.colorScheme.primary,
    )
}

@Composable
private fun ServerUrlField() {
    var serverUrl by remember { mutableStateOf("") }
    
    OutlinedTextField(
        value = serverUrl,
        onValueChange = { serverUrl = it },
        label = { Text("服务器地址") },
        modifier = Modifier.fillMaxWidth(),
        singleLine = true,
    )
}

@Composable
private fun AuthTokenField() {
    var token by remember { mutableStateOf("") }
    var showToken by remember { mutableStateOf(false) }
    
    OutlinedTextField(
        value = token,
        onValueChange = { token = it },
        label = { Text("认证 Token") },
        modifier = Modifier.fillMaxWidth(),
        visualTransformation = if (showToken) androidx.compose.ui.text.input.VisualTransformation.None else androidx.compose.ui.text.input.VisualTransformation.Password,
        trailingIcon = {
            IconButton(onClick = { showToken = !showToken }) {
                Icon(
                    imageVector = if (showToken) Icons.Default.Visibility else Icons.Default.Invisible,
                    contentDescription = if (showToken) "隐藏" else "显示",
                )
            }
        },
    )
}

@Composable
private fun ThemeSelector() {
    var selectedTheme by remember { mutableStateOf("qingwa") }
    
    ExposedDropdownMenuBox(
        expanded = false,
        onExpandedChange = {},
    ) {
        OutlinedTextField(
            value = selectedTheme,
            onValueChange = {},
            readOnly = true,
            label = { Text("主题") },
            modifier = Modifier.fillMaxWidth(),
            trailingIcon = {
                Icon(Icons.Default.ArrowDropDown, contentDescription = "展开")
            },
        )
        
        ExposedDropdownMenu(expanded = false, onDismissRequest = {}) {
            listOf("青瓦", "暖橙", "素纸", "微雾", "深色").forEach { theme ->
                DropdownMenuItem(
                    text = { Text(theme) },
                    onClick = { selectedTheme = theme.lowercase() },
                )
            }
        }
    }
}

@Composable
private fun DarkModeToggle() {
    var enabled by remember { mutableStateOf(false) }
    
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("深色模式")
        Switch(checked = enabled, onCheckedChange = { enabled = it })
    }
}

@Composable
private fun FontSizeSlider() {
    var fontSize by remember { mutableStateOf(14f) }
    
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text("字体大小")
            Text("%.1f".format(fontSize))
        }
        
        Slider(
            value = fontSize,
            onValueChange = { fontSize = it },
            steps = 10,
            range = 12f..18f,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun KernelTypeSelector() {
    var selectedKernel by remember { mutableStateOf("dsh") }
    
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "当前内核：${getKernelLabel(selectedKernel)}",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Medium,
            )
            
            Spacer(modifier = Modifier.height(12.dp))
            
            ExposedDropdownMenuBox(
                expanded = false,
                onExpandedChange = {},
            ) {
                OutlinedTextField(
                    value = selectedKernel,
                    onValueChange = {},
                    readOnly = true,
                    label = { Text("选择内核") },
                    modifier = Modifier.fillMaxWidth(),
                    trailingIcon = {
                        Icon(Icons.Default.ArrowDropDown, contentDescription = "展开")
                    },
                )
                
                ExposedDropdownMenu(expanded = false, onDismissRequest = {}) {
                    listOf(
                        Triple("dsh", "DeepSeek Harness", "高性能、低延迟"),
                        Triple("claude_sdk", "Anthropic Claude", "高质量输出"),
                        Triple("legacy", "Ethan Legacy", "向后兼容"),
                    ).forEach { (value, label, desc) ->
                        DropdownMenuItem(
                            text = {
                                Column {
                                    Text(label)
                                    Text(
                                        text = desc,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            },
                            onClick = { selectedKernel = value },
                        )
                    }
                }
            }
            
            Spacer(modifier = Modifier.height(12.dp))
            
            Text(
                text = "⚠️ 切换内核需要重启应用才能生效",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
}

private fun getKernelLabel(kernel: String): String {
    return when (kernel) {
        "dsh" -> "DeepSeek Harness"
        "claude_sdk" -> "Anthropic Claude"
        "legacy" -> "Ethan Legacy"
        else -> "未知"
    }
}

@Composable
private fun ConcurrentTasksSlider() {
    var count by remember { mutableStateOf(5) }
    
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text("最大并发任务数")
            Text(count.toString())
        }
        
        Slider(
            value = count.toFloat(),
            onValueChange = { count = it.toInt() },
            steps = 9,
            range = 1f..10f,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun CacheUsageCard() {
    var cacheSize by remember { mutableStateOf("125 MB") }
    
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "缓存使用情况",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Medium,
            )
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Text(
                text = "已用：$cacheSize",
                style = MaterialTheme.typography.bodyLarge,
            )
            
            Spacer(modifier = Modifier.height(8.dp))
            
            LinearProgressIndicator(
                progress = 0.65f,
                modifier = Modifier.fillMaxWidth(),
            )
            
            Spacer(modifier = Modifier.height(12.dp))
            
            Button(
                onClick = { /* TODO: 清除缓存 */ },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("清除缓存")
            }
        }
    }
}

@Composable
private fun BiometricLockToggle() {
    var enabled by remember { mutableStateOf(false) }
    
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column {
            Text("生物识别锁")
            Text(
                text = "使用指纹或面部识别解锁应用",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Switch(checked = enabled, onCheckedChange = { enabled = it })
    }
}

@Composable
private fun EncryptionStatusCard() {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text("数据加密")
                Text(
                    text = "本地数据已加密存储",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Icon(
                imageVector = Icons.Default.CheckCircle,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

@Composable
private fun ConsentManagementCard() {
    var grantedCount by remember { mutableStateOf(12) }
    
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "会话授权管理",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Medium,
            )
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Text(
                text = "已授权：$grantedCount 次",
                style = MaterialTheme.typography.bodyMedium,
            )
            
            Spacer(modifier = Modifier.height(12.dp))
            
            Button(
                onClick = { /* TODO: 查看授权 */ },
                variant = ButtonVariant.Outlined,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("查看所有授权")
            }
        }
    }
}

@Composable
private fun SessionsManagementCard() {
    var sessionCount by remember { mutableStateOf(156) }
    var totalSize by remember { mutableStateOf("2.3 GB") }
    
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "对话历史",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Medium,
            )
            
            Spacer(modifier = Modifier.height(8.dp))
            
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text("会话数：$sessionCount")
                Text("总计：$totalSize")
            }
            
            Spacer(modifier = Modifier.height(12.dp))
            
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Button(
                    onClick = { /* TODO: 导出 */ },
                    modifier = Modifier.weight(1f),
                    variant = ButtonVariant.Outlined,
                ) {
                    Text("导出")
                }
                
                Button(
                    onClick = { /* TODO: 删除 */ },
                    modifier = Modifier.weight(1f),
                ) {
                    Text("清空历史")
                }
            }
        }
    }
}

@Composable
private fun AboutSection() {
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            text = "版本：v0.5.395",
            style = MaterialTheme.typography.bodyLarge,
        )
        
        Spacer(modifier = Modifier.height(8.dp))
        
        Text(
            text = "架构：可插拔内核系统",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.primary,
        )
        
        Spacer(modifier = Modifier.height(8.dp))
        
        Text(
            text = "© 2026 Ethan Team",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
