package com.ethan.agent.ui.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.KernelInfoDto
import com.ethan.agent.core.model.KernelsResponse

/**
 * AI 内核设置页 —— 决定「由谁执行这一轮对话」。
 *
 * 设计要点（与 web/desktop 的 kernel-selector 保持一致）：
 *
 * 1. **不可用的内核不隐藏**，显示「安装」按钮 + 安装命令。
 *    隐藏会让人以为没这个能力；显示出来才有选择权。
 *
 * 2. **能力差异必须明说**。尤其是「能否用 Ethan 的工具」——
 *    这是「内核作为 Ethan 的心脏」的核心指标：
 *      · 可用 → 它用 Ethan 的手脚干活
 *      · 不可用 → 只是个外接的三方 agent
 *    用户据此决定用哪个，而不是自己踩坑才发现。
 *
 * 3. **切换失败要给出原因**。后端会先校验再写配置，
 *    不可用时保持原内核并返回 409，这里把 reason 原样展示。
 */
@Composable
fun KernelSettings(
    data: KernelsResponse?,
    busyKind: String,
    onSelect: (String) -> Unit,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val current = data?.default ?: "ethan"

    // 注意：**不要**在这里加 fillMaxSize / verticalScroll。
    // 外层 SettingsScreen 的 HorizontalPager 每页已经是
    //   Column(fillMaxSize + verticalScroll + padding)
    // 内层再套一层 verticalScroll 会形成嵌套滚动，内层拿到无界高度约束，
    // Compose 测量期直接抛异常 → 切到这个 Tab 就闪退。实测踩到。
    // 本组件只负责内容，滚动交给外层。
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(16.dp),
    ) {
        Text("AI 内核", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        Text(
            "决定由谁执行这一轮对话。原生内核使用 Ethan 的全部能力；" +
                "外部内核把执行权交给对应 CLI，各自有自己的工具与提示词。",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(16.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.End,
        ) {
            TextButton(onClick = onRefresh) {
                Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("刷新")
            }
        }

        if (data == null) {
            Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(modifier = Modifier.size(24.dp))
            }
            return@Column
        }

        data.kernels.forEach { kernel ->
            KernelCard(
                kernel = kernel,
                isCurrent = kernel.kind == current,
                isBusy = busyKind == kernel.kind,
                onSelect = { onSelect(kernel.kind) },
            )
            Spacer(Modifier.height(8.dp))
        }

        Spacer(Modifier.height(16.dp))
        Text(
            "提示：外部内核会以完全放行的权限运行（不询问授权），" +
                "请只在信任的任务下使用。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun KernelCard(
    kernel: KernelInfoDto,
    isCurrent: Boolean,
    isBusy: Boolean,
    onSelect: () -> Unit,
) {
    val caps = kernel.capabilities
    val isExternal = kernel.kind != "ethan"

    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (isCurrent) {
                MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.35f)
            } else {
                MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.35f)
            },
        ),
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    imageVector = if (kernel.available) Icons.Default.CheckCircle else Icons.Default.Warning,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp),
                    tint = if (kernel.available) Color(0xFF16A34A) else Color(0xFFD97706),
                )
                Spacer(Modifier.width(6.dp))
                Text(kernel.name, fontWeight = FontWeight.Medium)
                Spacer(Modifier.width(6.dp))
                Text(
                    kernel.kind,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (isCurrent) {
                    Spacer(Modifier.width(6.dp))
                    Badge(containerColor = MaterialTheme.colorScheme.primary) { Text("当前") }
                }
                Spacer(Modifier.weight(1f))
                if (!isCurrent) {
                    Button(
                        onClick = onSelect,
                        enabled = kernel.available && !isBusy,
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp),
                    ) {
                        if (isBusy) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(12.dp),
                                strokeWidth = 2.dp,
                            )
                        } else {
                            Text("启用", style = MaterialTheme.typography.labelMedium)
                        }
                    }
                }
            }

            // 不可用原因
            if (!kernel.available && kernel.reason.isNotEmpty()) {
                Spacer(Modifier.height(4.dp))
                Text(
                    kernel.reason,
                    style = MaterialTheme.typography.bodySmall,
                    color = Color(0xFFD97706),
                )
                if (kernel.installCommand.isNotEmpty()) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        kernel.installCommand,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            // 能力标签：能否共享 Ethan 工具是最关键的一条
            if (isExternal) {
                Spacer(Modifier.height(6.dp))
                FlowRowLikeBadges(
                    sharesTools = caps.sharesEthanTools,
                    ethanContext = caps.ethanContext,
                    consent = caps.consent,
                    resumable = caps.resumable,
                )

                // 不能共享时说明原因——别让用户以为是 bug
                if (!caps.sharesEthanTools && caps.sharesEthanToolsReason.isNotEmpty()) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        caps.sharesEthanToolsReason,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

/**
 * 能力标签行。
 *
 * 「可用 Ethan 的工具」用绿色强调，因为它是区分「真·内核」和「外接三方 agent」
 * 的关键指标；「仅自带工具」用灰色，表示能力受限但不是错误。
 */
@Composable
private fun FlowRowLikeBadges(
    sharesTools: Boolean,
    ethanContext: Boolean,
    consent: Boolean,
    resumable: Boolean,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        if (sharesTools) {
            SmallChip(
                text = "可用 Ethan 的工具",
                bg = Color(0xFF16A34A).copy(alpha = 0.15f),
                fg = Color(0xFF16A34A),
            )
        } else {
            SmallChip(
                text = "仅自带工具",
                bg = MaterialTheme.colorScheme.surfaceVariant,
                fg = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        // ethanContext 只表示「不注入 Ethan 的人格/画像/系统提示词」。技能与记忆能不能用
        // 由上面的 sharesTools 决定（经 MCP 注入，附带技能索引与记忆召回提示）。
        // 这里以前写「不共享技能/记忆」，和绿色徽章自相矛盾。
        if (!ethanContext) {
            SmallChip(
                text = "不注入人格/画像",
                bg = MaterialTheme.colorScheme.surfaceVariant,
                fg = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (!consent) {
            SmallChip(
                text = "无中途授权",
                bg = MaterialTheme.colorScheme.surfaceVariant,
                fg = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (resumable) {
            SmallChip(
                text = "支持续接",
                bg = MaterialTheme.colorScheme.surfaceVariant,
                fg = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun SmallChip(text: String, bg: Color, fg: Color) {
    Box(
        modifier = Modifier
            .background(bg, RoundedCornerShape(4.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    ) {
        Text(text, style = MaterialTheme.typography.labelSmall, color = fg)
    }
}
