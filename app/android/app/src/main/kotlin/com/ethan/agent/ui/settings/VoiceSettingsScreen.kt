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
import com.ethan.agent.core.model.VoiceBackendDto
import com.ethan.agent.core.model.VoiceBackendsResponse

/**
 * 语音设置页 —— TTS / ASR 后端选择。
 *
 * 核心约束（与 web/desktop 一致）：
 * **本地后端不可用是常态，不是错误**。
 * ethan-tts 依赖 Apple Silicon + MLX，Windows/Linux/Intel Mac 都跑不了。
 * 所以不可用时展示「为什么不能 + 改用在线后端」，而不是红色报错。
 */
@Composable
fun VoiceSettings(
    data: VoiceBackendsResponse?,
    busyKind: String,
    onSelect: (String, String) -> Unit,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val currentTts = data?.current?.tts ?: "edge-tts"
    val currentAsr = data?.current?.asr ?: "off"

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
        Text("语音", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        Text(
            "语音合成（朗读）与语音识别（说话输入）。本地后端离线可用但仅限 Apple Silicon；" +
                "在线后端零安装。",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(16.dp))

        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
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

        // ── TTS ──
        Text("语音合成（TTS）", fontWeight = FontWeight.Medium)
        Spacer(Modifier.height(8.dp))

        listOf(
            "edge-tts" to ("Edge TTS（在线）" to "微软在线语音，零安装、跨平台。需要联网，音色控制较弱。"),
            "ethan-tts" to ("Ethan TTS（本地）" to "本机 Qwen3-TTS，离线、可克隆音色、可调语气。需要 Apple Silicon。"),
        ).forEach { (key, meta) ->
            val (label, desc) = meta
            val probe = data.tts[key]
            VoiceBackendCard(
                title = label,
                desc = desc,
                probe = probe,
                isCurrent = currentTts == key,
                isBusy = busyKind == "tts",
                // edge-tts 零依赖，永远可选；本地后端看 probe
                enabled = if (key == "edge-tts") true else (probe?.available == true),
                onSelect = { onSelect(key, "") },
            )
            Spacer(Modifier.height(8.dp))
        }

        // 预检明细
        data.tts["ethan-tts"]?.let { probe ->
            if (probe.checks.isNotEmpty()) {
                Spacer(Modifier.height(4.dp))
                VoiceChecks(probe)
            }
        }

        Spacer(Modifier.height(16.dp))

        // ── ASR ──
        Text("语音识别（ASR）", fontWeight = FontWeight.Medium)
        Spacer(Modifier.height(4.dp))
        Text(
            "语音输入的识别引擎。依赖本地语音后端；关闭时只能打字。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))

        Card(Modifier.fillMaxWidth()) {
            Row(
                Modifier.padding(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Default.Mic, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(8.dp))
                Column(Modifier.weight(1f)) {
                    Text(if (currentAsr == "off") "已关闭" else "已启用", fontWeight = FontWeight.Medium)
                    if (currentAsr == "off" && !data.asr.available && data.asr.reason.isNotEmpty()) {
                        Text(
                            data.asr.reason,
                            style = MaterialTheme.typography.bodySmall,
                            color = Color(0xFFD97706),
                        )
                    }
                }
                Button(
                    onClick = {
                        if (currentAsr == "off") onSelect("", "ethan-tts") else onSelect("", "off")
                    },
                    enabled = currentAsr != "off" || data.asr.available,
                ) {
                    Text(if (currentAsr == "off") "启用" else "关闭")
                }
            }
        }
    }
}

@Composable
private fun VoiceBackendCard(
    title: String,
    desc: String,
    probe: VoiceBackendDto?,
    isCurrent: Boolean,
    isBusy: Boolean,
    enabled: Boolean,
    onSelect: () -> Unit,
) {
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
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = if (enabled) Icons.Default.CheckCircle else Icons.Default.Warning,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp),
                    tint = if (enabled) Color(0xFF16A34A) else Color(0xFFD97706),
                )
                Spacer(Modifier.width(6.dp))
                Text(title, fontWeight = FontWeight.Medium)
                if (isCurrent) {
                    Spacer(Modifier.width(6.dp))
                    Badge(containerColor = MaterialTheme.colorScheme.primary) { Text("当前") }
                }
                if (probe?.serviceRunning == true) {
                    Spacer(Modifier.width(6.dp))
                    Text(
                        "服务运行中",
                        style = MaterialTheme.typography.labelSmall,
                        color = Color(0xFF16A34A),
                    )
                }
                Spacer(Modifier.weight(1f))
                if (!isCurrent) {
                    Button(
                        onClick = onSelect,
                        enabled = enabled && !isBusy,
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp),
                    ) {
                        if (isBusy) {
                            CircularProgressIndicator(Modifier.size(12.dp), strokeWidth = 2.dp)
                        } else {
                            Text("启用", style = MaterialTheme.typography.labelMedium)
                        }
                    }
                }
            }
            Spacer(Modifier.height(4.dp))
            Text(
                desc,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (!enabled && probe?.reason?.isNotEmpty() == true) {
                Spacer(Modifier.height(4.dp))
                Text(probe.reason, style = MaterialTheme.typography.bodySmall, color = Color(0xFFD97706))
            }
        }
    }
}

/** 环境检查明细：默认收起，出问题时才需要展开。 */
@Composable
private fun VoiceChecks(probe: VoiceBackendDto) {
    var expanded by remember { mutableStateOf(false) }
    val failed = probe.checks.count { it.status == "error" }

    TextButton(onClick = { expanded = !expanded }) {
        Text(
            if (failed > 0) "环境检查（$failed 项异常）" else "环境检查",
            style = MaterialTheme.typography.labelSmall,
        )
        Icon(
            if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
            contentDescription = null,
            modifier = Modifier.size(14.dp),
        )
    }
    if (expanded) {
        Column(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.3f), RoundedCornerShape(6.dp))
                .padding(8.dp),
        ) {
            probe.checks.forEach { c ->
                Row(Modifier.padding(vertical = 2.dp)) {
                    Icon(
                        imageVector = if (c.status == "ok") Icons.Default.Check else Icons.Default.Warning,
                        contentDescription = null,
                        modifier = Modifier.size(12.dp),
                        tint = if (c.status == "ok") Color(0xFF16A34A) else Color(0xFFD97706),
                    )
                    Spacer(Modifier.width(6.dp))
                    Text(
                        "${c.name}：${c.detail}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}
