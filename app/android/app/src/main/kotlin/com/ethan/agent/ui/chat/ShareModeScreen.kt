package com.ethan.agent.ui.chat

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import com.ethan.agent.shared.UiMessage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private enum class ShareWidthPreset(val label: String, val pxWidth: Int) {
    COMPACT("紧凑", 720),
    STANDARD("标准", 960),
    WIDE("宽", 1200),
}

private fun formatShareTime(tsSeconds: Long?): String {
    if (tsSeconds == null || tsSeconds <= 0L) return ""
    val sdf = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault())
    return sdf.format(Date(tsSeconds * 1000))
}

private fun formatShareDuration(ms: Long): String {
    return when {
        ms < 1000 -> "${ms}ms"
        ms < 60_000 -> String.format(Locale.US, "%.1fs", ms / 1000.0)
        else -> "${ms / 60_000}m${(ms % 60_000) / 1000}s"
    }
}

private fun snippetText(text: String, maxLen: Int = 60): String {
    val oneLine = text.replace(Regex("\\s+"), " ").trim()
    return if (oneLine.length > maxLen) oneLine.take(maxLen) + "…" else oneLine
}

@Composable
fun ShareModeScreen(
    messages: List<UiMessage>,
    defaultSelectedIndex: Int,
    onClose: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    val validIndices = remember(messages) {
        messages.indices.filter { i ->
            val m = messages[i]
            !m.isStreaming && (m.content.isNotBlank() || m.cards.isNotEmpty())
        }
    }

    var selectedIndices by remember(messages, defaultSelectedIndex) {
        val initial = if (defaultSelectedIndex in validIndices) {
            setOf(defaultSelectedIndex)
        } else {
            validIndices.lastOrNull()?.let { setOf(it) } ?: emptySet()
        }
        mutableStateOf(initial)
    }

    var includeMeta by remember { mutableStateOf(true) }
    var includeStats by remember { mutableStateOf(true) }
    var includeCards by remember { mutableStateOf(true) }
    var cardsOnly by remember { mutableStateOf(false) }
    var widthPreset by remember { mutableStateOf(ShareWidthPreset.STANDARD) }
    var showSelector by remember { mutableStateOf(false) }
    var editingIndex by remember { mutableStateOf<Int?>(null) }
    val editedContents = remember { mutableStateMapOf<Int, String>() }
    var exporting by remember { mutableStateOf(false) }

    val selectedMessages = remember(messages, selectedIndices) {
        validIndices.filter { it in selectedIndices }.map { it to messages[it] }
    }
    val hasCards = remember(selectedMessages) {
        selectedMessages.any { (_, m) -> m.cards.isNotEmpty() }
    }
    if (!hasCards && cardsOnly) {
        cardsOnly = false
    }

    BackHandler { onClose() }

    Surface(
        modifier = Modifier.fillMaxSize(),
        color = MaterialTheme.colorScheme.background,
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .navigationBarsPadding(),
        ) {
            // 顶部栏
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onClose) {
                    Icon(Icons.Default.Close, contentDescription = "关闭")
                }
                Icon(
                    Icons.Default.Share,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                    tint = MaterialTheme.colorScheme.primary,
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    "分享对话",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = { showSelector = !showSelector }) {
                    Text("已选 ${selectedIndices.size}/${validIndices.size}")
                    Icon(
                        if (showSelector) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }

            HorizontalDivider()

            // 可折叠的消息选择器
            AnimatedVisibility(visible = showSelector) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.35f))
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            "选择要分享的消息",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            TextButton(onClick = { selectedIndices = validIndices.toSet() }) {
                                Text("全选")
                            }
                            TextButton(onClick = { selectedIndices = emptySet() }) {
                                Text("清空")
                            }
                        }
                    }
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(180.dp)
                            .verticalScroll(rememberScrollState()),
                    ) {
                        validIndices.forEach { idx ->
                            val msg = messages[idx]
                            val checked = idx in selectedIndices
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(8.dp))
                                    .clickable {
                                        selectedIndices = if (checked) {
                                            selectedIndices - idx
                                        } else {
                                            selectedIndices + idx
                                        }
                                    }
                                    .padding(vertical = 2.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Checkbox(
                                    checked = checked,
                                    onCheckedChange = { isChecked ->
                                        selectedIndices = if (isChecked) {
                                            selectedIndices + idx
                                        } else {
                                            selectedIndices - idx
                                        }
                                    },
                                )
                                Text(
                                    text = if (msg.role == "user") "你" else "Ethan",
                                    style = MaterialTheme.typography.labelSmall,
                                    fontWeight = FontWeight.Bold,
                                    color = if (msg.role == "user") Color(0xFF0969DA) else MaterialTheme.colorScheme.onSurface,
                                    modifier = Modifier.width(44.dp),
                                )
                                Text(
                                    text = snippetText(editedContents[idx] ?: msg.content),
                                    style = MaterialTheme.typography.bodySmall,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f),
                                )
                            }
                        }
                    }
                }
            }

            // 选项栏
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 12.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                FilterChip(
                    selected = includeMeta,
                    onClick = { includeMeta = !includeMeta },
                    label = { Text("角色与时间") },
                )
                FilterChip(
                    selected = includeStats,
                    onClick = { includeStats = !includeStats },
                    label = { Text("统计信息") },
                )
                if (hasCards) {
                    FilterChip(
                        selected = includeCards,
                        onClick = { includeCards = !includeCards },
                        label = { Text("附件卡片") },
                    )
                    FilterChip(
                        selected = cardsOnly,
                        onClick = { cardsOnly = !cardsOnly },
                        label = { Text("仅导出卡片") },
                    )
                }
                ShareWidthPreset.entries.forEach { preset ->
                    FilterChip(
                        selected = widthPreset == preset,
                        onClick = { widthPreset = preset },
                        label = { Text(preset.label) },
                    )
                }
            }

            // 预览区域
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .background(Color(0xFFF3F4F6))
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
                contentAlignment = Alignment.TopCenter,
            ) {
                if (selectedMessages.isEmpty()) {
                    Text(
                        "请至少选择一条消息",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Color(0xFF6B7280),
                        modifier = Modifier.padding(top = 48.dp),
                    )
                } else {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(14.dp))
                            .background(Color.White)
                            .border(1.dp, Color(0xFFE5E7EB), RoundedCornerShape(14.dp))
                            .padding(
                                horizontal = when (widthPreset) {
                                    ShareWidthPreset.COMPACT -> 16.dp
                                    ShareWidthPreset.STANDARD -> 20.dp
                                    ShareWidthPreset.WIDE -> 24.dp
                                },
                                vertical = 20.dp,
                            ),
                    ) {
                        selectedMessages.forEachIndexed { listPos, (idx, msg) ->
                            val displayContent = editedContents[idx] ?: msg.content
                            val isEditing = editingIndex == idx

                            Column(modifier = Modifier.fillMaxWidth()) {
                                if (includeMeta || !cardsOnly) {
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        if (includeMeta) {
                                            val isUser = msg.role == "user"
                                            Box(
                                                modifier = Modifier
                                                    .clip(RoundedCornerShape(6.dp))
                                                    .background(if (isUser) Color(0xFFDDF4FF) else Color(0xFFEAEEF2))
                                                    .padding(horizontal = 8.dp, vertical = 2.dp),
                                            ) {
                                                Text(
                                                    text = if (isUser) "你" else "Ethan",
                                                    fontSize = 11.sp,
                                                    fontWeight = FontWeight.SemiBold,
                                                    color = if (isUser) Color(0xFF0969DA) else Color(0xFF1F2328),
                                                )
                                            }
                                            val timeStr = formatShareTime(msg.createdAt)
                                            if (timeStr.isNotEmpty()) {
                                                Spacer(Modifier.width(8.dp))
                                                Text(
                                                    text = timeStr,
                                                    fontSize = 11.sp,
                                                    color = Color(0xFF8B949E),
                                                )
                                            }
                                        }
                                        Spacer(Modifier.weight(1f))
                                        if (!cardsOnly) {
                                            IconButton(
                                                onClick = { editingIndex = if (isEditing) null else idx },
                                                modifier = Modifier.size(28.dp),
                                            ) {
                                                Icon(
                                                    if (isEditing) Icons.Default.Check else Icons.Default.Edit,
                                                    contentDescription = if (isEditing) "完成编辑" else "编辑内容",
                                                    tint = Color(0xFF6B7280),
                                                    modifier = Modifier.size(15.dp),
                                                )
                                            }
                                        }
                                    }
                                    Spacer(Modifier.height(6.dp))
                                }

                                if (!cardsOnly) {
                                    if (isEditing) {
                                        OutlinedTextField(
                                            value = displayContent,
                                            onValueChange = { editedContents[idx] = it },
                                            modifier = Modifier.fillMaxWidth(),
                                            textStyle = MaterialTheme.typography.bodyMedium,
                                        )
                                    } else if (displayContent.isNotBlank()) {
                                        Text(
                                            text = displayContent,
                                            fontSize = 14.sp,
                                            lineHeight = 22.sp,
                                            color = Color(0xFF1F2328),
                                        )
                                    }
                                }

                                if (includeCards && msg.cards.isNotEmpty()) {
                                    Spacer(Modifier.height(8.dp))
                                    msg.cards.forEach { card ->
                                        Row(
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .padding(vertical = 2.dp)
                                                .clip(RoundedCornerShape(8.dp))
                                                .background(Color(0xFFF6F8FA))
                                                .border(1.dp, Color(0xFFE5E7EB), RoundedCornerShape(8.dp))
                                                .padding(horizontal = 10.dp, vertical = 8.dp),
                                            verticalAlignment = Alignment.CenterVertically,
                                        ) {
                                            Text(
                                                text = card.name ?: card.path ?: "附件",
                                                fontSize = 12.sp,
                                                fontWeight = FontWeight.Medium,
                                                color = Color(0xFF1F2328),
                                            )
                                        }
                                    }
                                }

                                if (includeStats && msg.role == "assistant" && !cardsOnly) {
                                    val statChips = buildList {
                                        msg.usage?.model?.takeIf { it.isNotBlank() }?.let { add(it) }
                                        val totalTokens = (msg.usage?.inputTokens ?: 0) + (msg.usage?.outputTokens ?: 0)
                                        if (totalTokens > 0) add("$totalTokens tokens")
                                        msg.ttfbMs?.let { add("首字 ${formatShareDuration(it)}") }
                                        msg.totalDurationMs?.let { add("总计 ${formatShareDuration(it)}") }
                                    }
                                    if (statChips.isNotEmpty()) {
                                        Spacer(Modifier.height(8.dp))
                                        Row(
                                            modifier = Modifier.horizontalScroll(rememberScrollState()),
                                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                                        ) {
                                            statChips.forEach { chip ->
                                                Box(
                                                    modifier = Modifier
                                                        .clip(RoundedCornerShape(4.dp))
                                                        .background(Color(0xFFF1F3F5))
                                                        .padding(horizontal = 6.dp, vertical = 2.dp),
                                                ) {
                                                    Text(
                                                        text = chip,
                                                        fontSize = 10.sp,
                                                        color = Color(0xFF57606A),
                                                    )
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            if (listPos < selectedMessages.lastIndex) {
                                HorizontalDivider(
                                    modifier = Modifier.padding(vertical = 14.dp),
                                    color = Color(0xFFEAEEF2),
                                )
                            }
                        }

                        Spacer(Modifier.height(16.dp))
                        HorizontalDivider(color = Color(0xFFEAEEF2))
                        Spacer(Modifier.height(12.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = "Ethan",
                                fontSize = 15.sp,
                                fontWeight = FontWeight.Bold,
                                color = Color(0xFF1F2328),
                            )
                            Text(
                                text = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault()).format(Date()),
                                fontSize = 11.sp,
                                color = Color(0xFF8B949E),
                            )
                        }
                    }
                }
            }

            // 底部操作栏
            HorizontalDivider()
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 10.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                OutlinedButton(
                    onClick = {
                        if (selectedMessages.isEmpty() || exporting) return@OutlinedButton
                        exporting = true
                        scope.launch {
                            val ok = withContext(Dispatchers.IO) {
                                val bmp = renderShareBitmap(
                                    messages = selectedMessages.map { (idx, m) ->
                                        m.copy(content = editedContents[idx] ?: m.content)
                                    },
                                    widthPx = widthPreset.pxWidth,
                                    includeMeta = includeMeta,
                                    includeStats = includeStats,
                                    includeCards = includeCards,
                                    cardsOnly = cardsOnly,
                                )
                                saveBitmapToGallery(context, bmp)
                            }
                            exporting = false
                            Toast.makeText(
                                context,
                                if (ok) "已保存到相册 Pictures/Ethan" else "保存失败，请重试",
                                Toast.LENGTH_SHORT,
                            ).show()
                        }
                    },
                    enabled = selectedMessages.isNotEmpty() && !exporting,
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Default.Download, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("保存图片")
                }

                Button(
                    onClick = {
                        if (selectedMessages.isEmpty() || exporting) return@Button
                        exporting = true
                        scope.launch {
                            val file = withContext(Dispatchers.IO) {
                                val bmp = renderShareBitmap(
                                    messages = selectedMessages.map { (idx, m) ->
                                        m.copy(content = editedContents[idx] ?: m.content)
                                    },
                                    widthPx = widthPreset.pxWidth,
                                    includeMeta = includeMeta,
                                    includeStats = includeStats,
                                    includeCards = includeCards,
                                    cardsOnly = cardsOnly,
                                )
                                saveBitmapToCache(context, bmp)
                            }
                            exporting = false
                            if (file != null) {
                                val uri = FileProvider.getUriForFile(
                                    context,
                                    "${context.packageName}.fileprovider",
                                    file,
                                )
                                val intent = Intent(Intent.ACTION_SEND).apply {
                                    type = "image/png"
                                    putExtra(Intent.EXTRA_STREAM, uri)
                                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                                }
                                context.startActivity(Intent.createChooser(intent, "分享对话长图"))
                            } else {
                                Toast.makeText(context, "生成分享图片失败", Toast.LENGTH_SHORT).show()
                            }
                        }
                    },
                    enabled = selectedMessages.isNotEmpty() && !exporting,
                    modifier = Modifier.weight(1f),
                ) {
                    if (exporting) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimary,
                        )
                    } else {
                        Icon(Icons.Default.Share, contentDescription = null, modifier = Modifier.size(18.dp))
                    }
                    Spacer(Modifier.width(6.dp))
                    Text("分享图片")
                }
            }
        }
    }
}

private fun renderShareBitmap(
    messages: List<UiMessage>,
    widthPx: Int,
    includeMeta: Boolean,
    includeStats: Boolean,
    includeCards: Boolean,
    cardsOnly: Boolean,
): Bitmap {
    val paddingH = (widthPx * 0.055f).toInt().coerceAtLeast(36)
    val paddingV = 44
    val contentWidth = widthPx - paddingH * 2

    val rolePaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = 24f
        typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
    }
    val timePaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = 22f
        color = android.graphics.Color.parseColor("#8B949E")
    }
    val bodyPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = 28f
        color = android.graphics.Color.parseColor("#1F2328")
    }
    val statPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = 20f
        color = android.graphics.Color.parseColor("#57606A")
    }
    val logoPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = 30f
        typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
        color = android.graphics.Color.parseColor("#1F2328")
    }
    val dividerPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = android.graphics.Color.parseColor("#EAEEF2")
        strokeWidth = 2f
    }
    val badgeBgPaint = Paint(Paint.ANTI_ALIAS_FLAG)

    data class Block(
        val msg: UiMessage,
        val bodyLayout: StaticLayout?,
        val statsText: String?,
    )

    val blocks = messages.map { msg ->
        val layout = if (!cardsOnly && msg.content.isNotBlank()) {
            StaticLayout.Builder.obtain(msg.content, 0, msg.content.length, bodyPaint, contentWidth)
                .setAlignment(Layout.Alignment.ALIGN_NORMAL)
                .setLineSpacing(8f, 1f)
                .build()
        } else null

        val stats = if (includeStats && msg.role == "assistant" && !cardsOnly) {
            buildList {
                msg.usage?.model?.takeIf { it.isNotBlank() }?.let { add(it) }
                val totalTokens = (msg.usage?.inputTokens ?: 0) + (msg.usage?.outputTokens ?: 0)
                if (totalTokens > 0) add("$totalTokens tokens")
                msg.ttfbMs?.let { add("首字 ${formatShareDuration(it)}") }
                msg.totalDurationMs?.let { add("总计 ${formatShareDuration(it)}") }
            }.takeIf { it.isNotEmpty() }?.joinToString("  ·  ")
        } else null

        Block(msg, layout, stats)
    }

    var totalHeight = paddingV
    blocks.forEachIndexed { idx, block ->
        if (includeMeta) totalHeight += 42
        block.bodyLayout?.let { totalHeight += it.height + 14 }
        if (includeCards && block.msg.cards.isNotEmpty()) {
            totalHeight += block.msg.cards.size * 52 + 12
        }
        block.statsText?.let { totalHeight += 36 }
        if (idx < blocks.lastIndex) totalHeight += 32
    }
    totalHeight += 68 + paddingV

    val bitmap = Bitmap.createBitmap(widthPx, totalHeight.coerceAtLeast(200), Bitmap.Config.ARGB_8888)
    val canvas = Canvas(bitmap)
    canvas.drawColor(android.graphics.Color.WHITE)

    var y = paddingV.toFloat()
    blocks.forEachIndexed { idx, block ->
        val msg = block.msg
        if (includeMeta) {
            val isUser = msg.role == "user"
            val label = if (isUser) "你" else "Ethan"
            badgeBgPaint.color = android.graphics.Color.parseColor(if (isUser) "#DDF4FF" else "#EAEEF2")
            rolePaint.color = android.graphics.Color.parseColor(if (isUser) "#0969DA" else "#1F2328")
            val textW = rolePaint.measureText(label)
            val badgeRect = RectF(paddingH.toFloat(), y, paddingH + textW + 28f, y + 34f)
            canvas.drawRoundRect(badgeRect, 10f, 10f, badgeBgPaint)
            canvas.drawText(label, paddingH + 14f, y + 25f, rolePaint)

            val timeStr = formatShareTime(msg.createdAt)
            if (timeStr.isNotEmpty()) {
                canvas.drawText(timeStr, badgeRect.right + 16f, y + 25f, timePaint)
            }
            y += 42f
        }

        block.bodyLayout?.let { layout ->
            canvas.save()
            canvas.translate(paddingH.toFloat(), y)
            layout.draw(canvas)
            canvas.restore()
            y += layout.height + 14f
        }

        if (includeCards && msg.cards.isNotEmpty()) {
            badgeBgPaint.color = android.graphics.Color.parseColor("#F6F8FA")
            msg.cards.forEach { card ->
                val rect = RectF(paddingH.toFloat(), y, (widthPx - paddingH).toFloat(), y + 44f)
                canvas.drawRoundRect(rect, 10f, 10f, badgeBgPaint)
                canvas.drawText(card.name ?: card.path ?: "附件", paddingH + 16f, y + 29f, statPaint)
                y += 52f
            }
            y += 12f
        }

        block.statsText?.let { stats ->
            canvas.drawText(stats, paddingH.toFloat(), y + 22f, statPaint)
            y += 36f
        }

        if (idx < blocks.lastIndex) {
            y += 14f
            canvas.drawLine(paddingH.toFloat(), y, (widthPx - paddingH).toFloat(), y, dividerPaint)
            y += 18f
        }
    }

    y += 16f
    canvas.drawLine(paddingH.toFloat(), y, (widthPx - paddingH).toFloat(), y, dividerPaint)
    y += 40f
    canvas.drawText("Ethan", paddingH.toFloat(), y, logoPaint)
    val dateStr = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault()).format(Date())
    val dateW = timePaint.measureText(dateStr)
    canvas.drawText(dateStr, widthPx - paddingH - dateW, y, timePaint)

    return bitmap
}

private fun saveBitmapToCache(context: Context, bitmap: Bitmap): File? {
    return try {
        val dir = File(context.cacheDir, "share").apply { mkdirs() }
        val file = File(dir, "ethan-share-${System.currentTimeMillis()}.png")
        FileOutputStream(file).use { out ->
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)
        }
        file
    } catch (_: Exception) {
        null
    }
}

private fun saveBitmapToGallery(context: Context, bitmap: Bitmap): Boolean {
    return try {
        val filename = "ethan-share-${System.currentTimeMillis()}.png"
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, filename)
            put(MediaStore.Images.Media.MIME_TYPE, "image/png")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                put(MediaStore.Images.Media.RELATIVE_PATH, "${Environment.DIRECTORY_PICTURES}/Ethan")
                put(MediaStore.Images.Media.IS_PENDING, 1)
            }
        }
        val resolver = context.contentResolver
        val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values) ?: return false
        resolver.openOutputStream(uri)?.use { out ->
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)
        } ?: return false
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            values.clear()
            values.put(MediaStore.Images.Media.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
        }
        true
    } catch (_: Exception) {
        false
    }
}
