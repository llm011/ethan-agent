package com.ethan.agent.ui.chat

import androidx.compose.foundation.layout.statusBarsPadding
import com.ethan.agent.shared.viewmodel.ChatUiState
import com.ethan.agent.shared.viewmodel.ConnectionState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Shield
import androidx.compose.material.icons.filled.VerifiedUser
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.ModelSelection
import com.ethan.agent.core.model.Quote
import com.ethan.agent.core.model.fullId
import coil.compose.rememberAsyncImagePainter
import androidx.compose.foundation.clickable
import androidx.compose.material.icons.filled.Fullscreen
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties

/** Message composition, queued sends, and running-task injection. */
@Composable
internal fun ChatInputPanel(
    state: ChatUiState,
    onInputChange: (String) -> Unit,
    onSend: () -> Unit,
    onStop: () -> Unit,
    onModelSelected: (String) -> Unit,
    onQuote: (Quote?) -> Unit,
    onRemoveImage: (Int) -> Unit,
    onInject: (String) -> Unit,
    onQueueRemove: (Long) -> Unit,
    onQueueEdit: (Long) -> Unit,
    onToggleAutoConsent: () -> Unit,
    onOpenOptions: () -> Unit,
    onConfirmAutoConsent: () -> Unit,
    onOpenFullEditor: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.background)
            .navigationBarsPadding()
            .padding(horizontal = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        // 排队消息 chips（对齐 Web 的 QueuedMessages，展示在输入框正上方）：
        // 流式中点发送进队，本轮跑完自动按序发出。点击 = 取回输入框编辑，× = 移除。
        // 拖拽排序 web 独有，手机上取回再发等效，暂不做。
        if (state.queuedMessages.isNotEmpty()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 4.dp)
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                state.queuedMessages.forEach { item ->
                    AssistChip(
                        onClick = { onQueueEdit(item.id) },
                        label = {
                            Text(
                                item.text.ifBlank { "🖼 图片" }.replace("\n", " ").take(16),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        },
                        trailingIcon = {
                            Icon(
                                Icons.Default.Close,
                                contentDescription = "移除排队消息",
                                modifier = Modifier
                                    .size(14.dp)
                                    .clickable { onQueueRemove(item.id) },
                                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        },
                    )
                }
            }
        }

        // 运行中「补充信息」（对齐 Web 的 InjectBox）：立即注入当前 run 的 inbox，
        // 下一轮调模型前读取。注意区别于发送键 —— 流式中发送是排队（等本轮跑完），
        // 想让 Agent 马上看到就走这里。
        if (state.isStreaming || state.isResuming) {
            var injectOpen by remember { mutableStateOf(false) }
            var injectText by remember { mutableStateOf("") }
            var injectSubmitted by remember { mutableStateOf(false) }

            Column(modifier = Modifier.fillMaxWidth().padding(bottom = 4.dp)) {
                if (!injectOpen) {
                    Text(
                        "＋ 补充信息（立即注入）",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                        modifier = Modifier
                            .clip(RoundedCornerShape(8.dp))
                            .clickable { injectOpen = true }
                            .padding(horizontal = 6.dp, vertical = 4.dp),
                    )
                } else {
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                        color = MaterialTheme.colorScheme.surfaceContainerLowest,
                    ) {
                        Column {
                            BasicTextField(
                                value = injectText,
                                onValueChange = { injectText = it },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 10.dp, vertical = 8.dp),
                                minLines = 2,
                                maxLines = 4,
                                textStyle = MaterialTheme.typography.bodyMedium.copy(
                                    color = MaterialTheme.colorScheme.onSurface,
                                ),
                                decorationBox = { innerTextField ->
                                    Box {
                                        if (injectText.isEmpty()) {
                                            Text(
                                                "补充一些信息给运行中的任务…（Enter 处提交）",
                                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                                                style = MaterialTheme.typography.bodyMedium,
                                                maxLines = 1,
                                                overflow = TextOverflow.Ellipsis,
                                            )
                                        }
                                        innerTextField()
                                    }
                                },
                            )
                            Row(
                                modifier = Modifier.fillMaxWidth().padding(end = 6.dp, bottom = 4.dp),
                                horizontalArrangement = Arrangement.End,
                            ) {
                                TextButton(onClick = {
                                    injectOpen = false
                                    injectText = ""
                                    injectSubmitted = false
                                }) { Text("收起", style = MaterialTheme.typography.labelMedium) }
                                TextButton(
                                    enabled = injectText.isNotBlank(),
                                    onClick = {
                                        onInject(injectText.trim())
                                        injectText = ""
                                        injectSubmitted = true
                                    },
                                ) { Text("注入", style = MaterialTheme.typography.labelMedium) }
                            }
                        }
                    }
                    // 提交成功的即时反馈（失败走全局错误横幅：injectMessage 会 set error）
                    LaunchedEffect(injectSubmitted) {
                        if (injectSubmitted) {
                            kotlinx.coroutines.delay(2500)
                            injectSubmitted = false
                        }
                    }
                    if (injectSubmitted) {
                        Text(
                            "✓ 已注入，下一轮调用模型时读取",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.primary.copy(alpha = 0.8f),
                            modifier = Modifier.padding(start = 6.dp, top = 2.dp),
                        )
                    }
                }
            }
        }

        // 待发送图片预览（对齐 Web：输入框上方缩略图 + 删除按钮）
        if (state.pendingImages.isNotEmpty()) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(bottom = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                state.pendingImages.forEachIndexed { index, img ->
                    Box(modifier = Modifier.size(56.dp)) {
                        Image(
                            painter = rememberAsyncImagePainter(img.dataUrl),
                            contentDescription = img.filename,
                            modifier = Modifier
                                .fillMaxSize()
                                .clip(MaterialTheme.shapes.small),
                            contentScale = ContentScale.Crop,
                        )
                        Surface(
                            onClick = { onRemoveImage(index) },
                            shape = CircleShape,
                            color = MaterialTheme.colorScheme.surface.copy(alpha = 0.85f),
                            modifier = Modifier
                                .align(Alignment.TopEnd)
                                .size(18.dp),
                        ) {
                            Box(contentAlignment = Alignment.Center) {
                                Icon(
                                    Icons.Default.Close,
                                    contentDescription = "移除图片",
                                    tint = MaterialTheme.colorScheme.onSurface,
                                    modifier = Modifier.size(12.dp),
                                )
                            }
                        }
                    }
                }
            }
        }

        state.quote?.let { quote ->
            AssistChip(
                onClick = {},
                label = { Text("引用: ${quote.content.take(40)}…", maxLines = 1) },
                trailingIcon = {
                    IconButton(onClick = { onQuote(null) }) {
                        Icon(Icons.Default.Close, contentDescription = "清除引用")
                    }
                },
                modifier = Modifier.padding(bottom = 4.dp),
            )
        }

        // 旧会话/默认模型存的纯 id 命中多个同名模型：列出候选让用户一键指定 provider，
        // 选择前禁用发送（与 web/desktop chat-input 的候选按钮同做法）
        if (state.modelAmbiguous) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 4.dp)
                    .background(MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.4f), RoundedCornerShape(12.dp))
                    .padding(horizontal = 10.dp, vertical = 6.dp),
            ) {
                Text(
                    "模型「${state.selectedModel}」在多个 provider 下重名，请选择要使用的：",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
                Row(
                    modifier = Modifier
                        .padding(top = 4.dp)
                        .horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    state.ambiguousCandidates.forEach { model ->
                        AssistChip(
                            onClick = { onModelSelected(model.fullId) },
                            label = { Text(model.fullId, style = MaterialTheme.typography.bodySmall) },
                        )
                    }
                }
            }
        }

        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = MaterialTheme.colorScheme.surfaceContainerLowest,
            shape = MaterialTheme.shapes.extraLarge,
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        ) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(start = 6.dp, end = 4.dp, top = 4.dp, bottom = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // + 号按钮：圆形
                Surface(
                    onClick = { onOpenOptions() },
                    shape = CircleShape,
                    color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                    modifier = Modifier.size(32.dp),
                ) {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            Icons.Default.Add,
                            contentDescription = "更多选项",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(18.dp),
                        )
                    }
                }
                // 超级权限开关。关闭→开启时必须过一道二次确认（见本 composable
                // 末尾的 AlertDialog）：长时间运行时用户容易忘了自己开着自动批准，
                // 导致普通 shell / 写文件操作一路放行。取消弹窗则保持关闭。
                Surface(
                    onClick = {
                        if (state.autoConsent) onToggleAutoConsent() // 关：降权，直接生效
                        else onConfirmAutoConsent()          // 开：先弹警示
                    },
                    shape = CircleShape,
                    color = if (state.autoConsent) MaterialTheme.colorScheme.tertiaryContainer
                        else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                    modifier = Modifier.size(32.dp).padding(start = 2.dp),
                ) {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            if (state.autoConsent) Icons.Default.VerifiedUser else Icons.Default.Shield,
                            contentDescription = if (state.autoConsent) "超级权限已开启" else "超级权限",
                            tint = if (state.autoConsent) MaterialTheme.colorScheme.onTertiaryContainer
                                else MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(16.dp),
                        )
                    }
                }
                // 输入框 + 发送按钮
                Row(
                    modifier = Modifier.weight(1f).padding(start = 4.dp, end = 2.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    BasicTextField(
                        value = state.inputText,
                        onValueChange = onInputChange,
                        modifier = Modifier
                            .weight(1f)
                            .padding(horizontal = 8.dp, vertical = 6.dp),
                        maxLines = 5,
                        textStyle = MaterialTheme.typography.bodyMedium.copy(
                            color = MaterialTheme.colorScheme.onSurface,
                        ),
                        decorationBox = { innerTextField ->
                            Box {
                                if (state.inputText.isEmpty()) {
                                    // 占位文案在「用户可能正在输入」这件事上会误导，
                                    // 留空又容易让人以为输入框坏了，所以保留；但内容
                                    // 必须短到不折行 —— 手机上输入框横向空间被一排按钮
                                    // 挤得很窄（+ / 超级权限 / 展开 / 发送），一折行就顶高
                                    // 整条输入栏（原来是「输入消息，支持 Markdown…」）。
                                    // maxLines = 1 只做兜底：文案短到不折行时它不生效，
                                    // 万一以后有人把文案改长，也只会被截断而不会撑高输入栏。
                                    //
                                    // 注意：不要在「输入框行」上做 centerVertically——
                                    // BasicTextField 会随输入长到 maxLines = 5，居中后输入区
                                    // 上下同时溢出，顶栏「+」被切一半、最后一行也贴着输入栏边。
                                    Text(
                                        if (state.isStreaming) CHAT_INPUT_PLACEHOLDER_QUEUED
                                        else CHAT_INPUT_PLACEHOLDER,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                                        style = MaterialTheme.typography.bodyMedium,
                                        maxLines = 1,
                                    )
                                }
                                innerTextField()
                            }
                        },
                    )
                    // 展开为全屏编辑（对齐 Web 输入框右上角的展开按钮）：长文本时
                    // 5 行上限太憋屈，全屏写完再发。
                    IconButton(
                        onClick = { onOpenFullEditor() },
                        modifier = Modifier.size(28.dp),
                    ) {
                        Icon(
                            Icons.Default.Fullscreen,
                            contentDescription = "展开为全屏编辑",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(18.dp),
                        )
                    }
                    Box(
                        modifier = Modifier.padding(end = 2.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        when {
                            state.isStopping -> {
                                CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
                            }
                            state.isStreaming || state.isResuming -> {
                                // 生成中：停止 + 排队发送并排（对齐 web —— 流式里的发送
                                // 是入队，本轮跑完自动发下一条；只有停止键的话队列功能没入口）
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    // 队列发送：有内容才亮
                                    val canQueue = state.inputText.isNotBlank() || state.pendingImages.isNotEmpty()
                                    Surface(
                                        shape = CircleShape,
                                        color = if (canQueue) MaterialTheme.colorScheme.primary
                                            else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                                        modifier = Modifier.size(36.dp),
                                    ) {
                                        IconButton(
                                            onClick = onSend,
                                            enabled = canQueue && !state.modelAmbiguous,
                                        ) {
                                            Icon(
                                                Icons.AutoMirrored.Filled.Send,
                                                contentDescription = "排队发送",
                                                tint = if (canQueue) MaterialTheme.colorScheme.onPrimary
                                                    else MaterialTheme.colorScheme.onSurfaceVariant,
                                                modifier = Modifier.size(18.dp).offset(x = 1.dp),
                                            )
                                        }
                                    }
                                    Spacer(Modifier.width(6.dp))
                                    Surface(
                                        shape = CircleShape,
                                        color = MaterialTheme.colorScheme.errorContainer,
                                        modifier = Modifier.size(36.dp),
                                    ) {
                                        IconButton(onClick = onStop) {
                                            Icon(
                                                Icons.Default.Stop,
                                                contentDescription = "停止",
                                                tint = MaterialTheme.colorScheme.error,
                                                modifier = Modifier.size(18.dp),
                                            )
                                        }
                                    }
                                }
                            }
                            else -> {
                                // 有内容且模型不歧义才可发送（歧义时按钮同时变灰，避免"看起来能点"）
                                val canSend = (state.inputText.isNotBlank() || state.pendingImages.isNotEmpty()) &&
                                    !state.modelAmbiguous
                                Surface(
                                    shape = CircleShape,
                                    color = if (canSend) MaterialTheme.colorScheme.primary
                                        else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                                    modifier = Modifier.size(36.dp),
                                ) {
                                    IconButton(
                                        onClick = onSend,
                                        // 模型歧义时禁用发送，强制用户先显式选一个 provider
                                        enabled = canSend,
                                    ) {
                                        Icon(
                                            Icons.AutoMirrored.Filled.Send,
                                            contentDescription = "发送",
                                            tint = if (canSend) MaterialTheme.colorScheme.onPrimary
                                                else MaterialTheme.colorScheme.onSurfaceVariant,
                                            modifier = Modifier.size(18.dp).offset(x = 1.dp),
                                        )
                                    }
                                }
                            }
                        }
                    }
                } // end inner Row (input + send)
            } // end outer Row
        } // end Surface

        // 底部状态行：左侧放「当前模型 + 运行状态」，右侧固定一行免责声明。
        // 之前只有居中的「对话由 AI 生成」，既浪费了一整行高度，也没告诉
        // 用户正在用哪个模型、是否在生成中 —— 这两件事恰好在手机上最需要
        // 一眼看到（模型选错要立刻发现，生成中要能判断该不该等）。
        Row(
            // 左侧留 8dp：这段文字原来紧贴屏幕边缘（外层只有 12dp 的
            // horizontal padding，视觉上正好压在气泡的左对齐线上），
            // 和上方气泡的起始位置对不齐，看着「太靠左」。
            Modifier.fillMaxWidth().padding(start = 8.dp, top = 2.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            // 显示**可读名**（alias/description）而不是 provider/id 原始值 ——
            // 与模型选择器里的选中名、Web 的展示口径一致。落库/提交仍用 fullId。
            state.selectedModel?.takeIf { it.isNotBlank() }?.let { raw ->
                Text(
                    text = ModelSelection.findById(state.models, raw)
                        ?.let(ModelSelection::displayNameOf) ?: raw,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
            }
            when {
                state.isResuming -> FooterStatusDot("重连中", MaterialTheme.colorScheme.tertiary)
                state.isStreaming -> FooterStatusDot("生成中", MaterialTheme.colorScheme.primary)
                state.connectionState == ConnectionState.Offline ->
                    FooterStatusDot("离线", MaterialTheme.colorScheme.error)
                state.connectionState == ConnectionState.Disconnected ->
                    FooterStatusDot("已断开", MaterialTheme.colorScheme.error)
            }
            Spacer(Modifier.weight(1f))
            Text(
                text = "对话由 AI 生成",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                maxLines = 1,
                // 固定靠右：模型名过长时省略号吃掉的是左侧的空间，
                // 免责声明始终贴住右边缘（用户明确要求靠右对齐）。
                textAlign = TextAlign.End,
                modifier = Modifier.wrapContentWidth(align = Alignment.End),
            )
        }
    } // end input Column (bottom-aligned)
}

/** 底部状态行的小圆点 + 文案（生成中 / 重连中 / 已断开）。 */
@Composable
private fun FooterStatusDot(label: String, color: androidx.compose.ui.graphics.Color) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Box(Modifier.size(5.dp).clip(CircleShape).background(color))
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = color,
            maxLines = 1,
        )
    }
}

/**
 * 输入框占位文案。**必须短到在窄屏上不折行** —— 文案一折行会把整条输入栏顶高，
 * 因为左右两侧被一排按钮（+ / 超级权限 / 展开 / 发送）占掉了大部分宽度。
 *
 * 提到顶层常量是为了两处（收起态输入框、全屏编辑）引用同一份字符串，
 * 改文案时不会只改到一处。
 */
internal const val CHAT_INPUT_PLACEHOLDER = "输入消息"
internal const val CHAT_INPUT_PLACEHOLDER_QUEUED = "排队发送"

/** Full-screen editor shares the same input and send callbacks as the compact panel. */
@Composable
internal fun ChatFullEditor(
    state: ChatUiState,
    onInputChange: (String) -> Unit,
    onSend: () -> Unit,
    onClose: () -> Unit,
) {
    Dialog(
        onDismissRequest = { onClose() },
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background)
                .statusBarsPadding()
                .navigationBarsPadding()
                .imePadding()
                .padding(horizontal = 12.dp, vertical = 8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = { onClose() }) {
                    Icon(Icons.Default.Close, contentDescription = "关闭全屏编辑")
                }
                Text(
                    "编辑消息",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.weight(1f),
                )
                // 发送后关闭全屏；流式中发送会走排队路径（与主输入框同一 onSend）
                val canSendFull = (state.inputText.isNotBlank() || state.pendingImages.isNotEmpty()) &&
                    !state.modelAmbiguous
                IconButton(
                    onClick = {
                        onClose()
                        onSend()
                    },
                    enabled = canSendFull,
                ) {
                    Icon(
                        Icons.AutoMirrored.Filled.Send,
                        contentDescription = "发送",
                        tint = if (canSendFull) MaterialTheme.colorScheme.primary
                            else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.4f),
                    )
                }
            }
            HorizontalDivider(modifier = Modifier.padding(bottom = 8.dp))
            BasicTextField(
                value = state.inputText,
                onValueChange = onInputChange,
                modifier = Modifier.fillMaxWidth().weight(1f),
                textStyle = MaterialTheme.typography.bodyLarge.copy(
                    color = MaterialTheme.colorScheme.onSurface,
                ),
                decorationBox = { innerTextField ->
                    Box {
                        if (state.inputText.isEmpty()) {
                            Text(
                                CHAT_INPUT_PLACEHOLDER,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                                style = MaterialTheme.typography.bodyLarge,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        innerTextField()
                    }
                },
            )
        }
    }
}
