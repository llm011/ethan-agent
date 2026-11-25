package com.ethan.agent.ui.chat

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.geometry.Size
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ethan.agent.core.model.FileSignature
import com.ethan.agent.core.model.UserIdentity
import com.ethan.agent.shared.UiMessage
import com.ethan.agent.shared.viewmodel.MessageRoleKind
import com.ethan.agent.ui.theme.bubbleAccentColor
import com.ethan.agent.ui.theme.bubbleContainerColor
import com.ethan.agent.ui.theme.bubbleRoleLabel
import com.ethan.agent.ui.theme.bubbleRoleLabelColor
import com.ethan.agent.ui.components.EthanBadge
import com.ethan.agent.ui.components.ToolTimeline
import com.ethan.agent.ui.components.TypingDots
import com.ethan.agent.ui.components.SimpleMarkdown
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import coil.compose.rememberAsyncImagePainter
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.clickable
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.platform.LocalConfiguration

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
internal fun MessageBubble(message: UiMessage, serverUrl: String = "", sessionId: String? = null, signFile: (suspend (String) -> FileSignature?)? = null, userIdentity: UserIdentity = UserIdentity(), onLongPress: () -> Unit, onOpenReading: () -> Unit = {}) {
    val isUser = message.role == "user"
    // 说话方分类 —— 移动端隐藏头像后，**颜色 + 角色名 + 色条** 三者共同承担
    // 「谁在说话」的识别职责（见 BubblePalette 的设计约束说明）。
    val roleKind = MessageRoleKind.of(message.role)
    val bubbleColor = bubbleContainerColor(roleKind)
    val accentColor = bubbleAccentColor(roleKind)
    val textColor = MaterialTheme.colorScheme.onSurface

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 4.dp, vertical = 2.dp),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.Top,
    ) {
        // 移动端**不渲染头像**：头像在窄屏上吃掉 36dp（30dp 圆 + 6dp 间距）的横向
        // 空间，而这正是「头像占宽度过多」的直接来源。识别职责已交给
        // 颜色 / 角色名 / 左侧色条（见下方 Column），不会因为去掉头像而失去区分度。
        //
        // 注意这里**没有**留占位 Spacer —— 去掉头像必须同时去掉它占的宽度，
        // 否则只是把头像变成一块空白，「气泡布局不错乱、不留空位」的要求就没满足。

        // Bubble content —— 宽度对齐 Web 的 max-w-[90%]，四角统一 rounded-2xl（18dp）。
        // 之前是固定 310dp + 不对称的一角切平，换机型/字号后容易显得局促。
        Column(
            modifier = Modifier.weight(1f),
            horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
        ) {
            // 角色名行（替代头像的识别职责）。
            //
            // 用户侧优先显示用户自己设的显示名（那是更有信息量的标识），没设才回落
            // 到「我」；助手/工具/系统用固定角色名。老用户没设名字时也能看到「我」，
            // 所以这一行是**恒定存在**的 —— 靠颜色单独区分对色盲用户不够。
            val roleLabel = if (isUser && userIdentity.displayName.isNotBlank()) {
                userIdentity.displayName
            } else {
                bubbleRoleLabel(roleKind)
            }
            // 角色名行。生成中在这行尾部接一串跳动的三点（对齐 Web 在气泡里放
            // animate-bounce 三点的做法）—— 它是**持续可见**的进行中动画：
            // 正文还没吐字时看得到，吐字过程中也看得到，不需要用户去找页脚那个小圆点。
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    roleLabel,
                    style = MaterialTheme.typography.labelSmall,
                    color = bubbleRoleLabelColor(),
                )
                if (message.isStreaming) {
                    Spacer(Modifier.width(6.dp))
                    TypingDots(color = accentColor.takeIf { it != Color.Transparent }
                        ?: bubbleRoleLabelColor(), dotSize = 3.dp, gap = 2.dp)
                }
            }
            Spacer(Modifier.height(2.dp))
            // 气泡圆角与角色色条协同：带色条的一侧收窄为 6dp 小圆角，另一侧保留 18dp 柔和气泡圆角。
            // 这样 3dp 边线沿直边完整延伸、只在端头微收，不会被 18dp 大圆角斜切出一块尖牙；
            // 用户气泡在右侧（边线靠右、左侧留 32dp 呼吸空间），助手气泡在左侧（边线靠左），左右对称。
            val bubbleShape = when {
                accentColor == Color.Transparent -> MaterialTheme.shapes.extraLarge
                isUser -> RoundedCornerShape(topStart = 18.dp, bottomStart = 18.dp, topEnd = 6.dp, bottomEnd = 6.dp)
                else -> RoundedCornerShape(topStart = 6.dp, bottomStart = 6.dp, topEnd = 18.dp, bottomEnd = 18.dp)
            }
            Surface(
                modifier = Modifier
                    .then(if (isUser) Modifier.padding(start = 32.dp) else Modifier)
                    .combinedClickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null,
                        onClick = {},
                        onLongClick = onLongPress,
                        onDoubleClick = onOpenReading,
                    ),
                shape = bubbleShape,
                color = bubbleColor,
                shadowElevation = 0.dp,
            ) {
                // 侧边色条：隐藏头像后的**主要**角色标记。3dp 实色线画在气泡贴边内缘
                // （用户气泡在右内缘，助手/工具气泡在左内缘）。
                //
                // 用色条而不是给 Surface 加 border：border 会沿整个圆角描一圈，
                // 看起来像「选中态」而不是「角色标记」；这里只要一条边的暗示。
                // 系统消息的 accentColor 是透明（不参与角色区分），不画色条但保留内边距。
                //
                // ⚠️ 这里**刻意不用 `Row(Modifier.height(IntrinsicSize.Min))` + 色条 Box**
                // 那种写法（虽然直觉上更「声明式」）：`IntrinsicSize.Min` 会向整个子树
                // 发起 intrinsic 测量，而本树里可达 `AndroidView`（```mermaid 代码块
                // 走 MermaidBlock → WebView）。AndroidViewHolder 没有实现 intrinsic 测量，
                // Compose 对它的回退是 NoIntrinsicsMeasurePolicy —— 该策略的四个
                // intrinsic 方法**直接抛 IllegalStateException**（已对 ui-android 1.7.8
                // 的字节码确认）。所以只要一条消息里有 mermaid 块，这个气泡就会崩。
                //
                // `drawBehind` 不参与测量，只在已确定尺寸的绘制阶段画一条线，因此
                // 色条高度天然等于气泡内容高度 —— 既拿回了 IntrinsicSize 想要的效果，
                // 又完全不碰 intrinsic 路径。
                Column(
                    Modifier
                        .drawBehind {
                            if (accentColor != Color.Transparent) {
                                val barWidth = 3.dp.toPx()
                                val barX = if (isUser) size.width - barWidth else 0f
                                drawRect(
                                    color = accentColor,
                                    topLeft = Offset(barX, 0f),
                                    size = Size(barWidth, size.height),
                                )
                            }
                        }
                        .padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 12.dp),
                ) {
                    // 用户消息图片（在文本之前）
                    if (message.images.isNotEmpty()) {
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(bottom = if (message.content.isNotBlank() || message.toolSteps.isNotEmpty() || message.quote != null) 6.dp else 0.dp),
                            horizontalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            message.images.forEach { img ->
                                Image(
                                    painter = rememberAsyncImagePainter(img.displayUrl),
                                    contentDescription = null,
                                    modifier = Modifier
                                        .sizeIn(maxHeight = 160.dp, maxWidth = 160.dp)
                                        .clip(MaterialTheme.shapes.small),
                                    contentScale = ContentScale.FillWidth,
                                )
                            }
                        }
                    }
                    message.quote?.let {
                        Text(
                            "↩ ${it.content.take(60)}",
                            style = MaterialTheme.typography.labelSmall,
                            color = if (isUser) textColor.copy(alpha = 0.7f)
                                else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(4.dp))
                    }
                    // 工具调用在前（折叠式）
                    if (message.toolSteps.isNotEmpty()) {
                        CompositionLocalProvider(androidx.compose.material3.LocalContentColor provides textColor) {
                            ToolTimeline(message.toolSteps, isStreaming = message.isStreaming)
                        }
                        if (message.content.isNotBlank()) {
                            Spacer(Modifier.height(6.dp))
                        }
                    }
                    // 文本结论在后
                    if (message.content.isNotBlank()) {
                        if (isUser) {
                            // 用户问题过长时最多展示 5 行，超出部分折叠并给「查看全部 / 收起」。
                            // 直接用 Text 的 maxLines + onTextLayout(hasVisualOverflow) 判定：
                            // 精准到行、自带末尾省略号，短气泡也不会被撑宽。
                            var userExpanded by remember(message.content) { mutableStateOf(false) }
                            var userOverflow by remember(message.content) { mutableStateOf(false) }
                            Column(modifier = Modifier.animateContentSize()) {
                                Text(
                                    text = message.content,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = textColor,
                                    maxLines = if (userExpanded) Int.MAX_VALUE else USER_QUERY_MAX_LINES,
                                    overflow = TextOverflow.Ellipsis,
                                    onTextLayout = { layoutResult ->
                                        if (!userExpanded) {
                                            userOverflow = layoutResult.hasVisualOverflow
                                        }
                                    },
                                )
                                if (userOverflow) {
                                    BubbleActionLink(
                                        label = if (userExpanded) "收起" else "查看全部",
                                        onClick = { userExpanded = !userExpanded },
                                        color = if (userExpanded) textColor.copy(alpha = 0.65f) else MaterialTheme.colorScheme.primary,
                                        fillMaxWidth = false,
                                    )
                                }
                            }
                        } else {
                            // 长消息折叠：超过半屏高就截断，底部给「查看全部 / 收起」。
                            // 只在真实尺寸超过阈值时展开 UI，短消息完全不受影响（无额外高度、无多余按钮）。
                            val density = LocalDensity.current
                            val configuration = LocalConfiguration.current
                            val screenWidthDp = configuration.screenWidthDp.toFloat()
                            val screenHeightDp = configuration.screenHeightDp.toFloat()
                            // 用 remember 而不是 rememberSaveable：MessageCollapseState 是自定义类，
                            // SaveableStateRegistry 只接受能进 Bundle 的类型，直接塞会抛
                            // IllegalArgumentException 把 App 打崩（已踩过）。而「展开/收起」
                            // 本来就属于一次性 UI 状态，进程被回收后恢复成折叠态完全可以接受。
                            //
                            // key 用 isStreaming 而不是 content：流式期间 content 每帧都变，
                            // 拿它做 key 会让「生成中就点开查看全部」立刻被重置回折叠态。
                            val collapseState = remember(message.isStreaming) {
                                messageCollapseState(
                                    text = message.content,
                                    screenWidthDp = screenWidthDp,
                                    screenHeightDp = screenHeightDp,
                                    fontScale = density.fontScale,
                                )
                            }
                            // 流结束后正文才是最终值（最后一轮 tool 之后还有结论），
                            // 此时按最终长度重新判定一次；只更新「可折叠与否 / 高度上限」，
                            // 不动 expanded —— 用户已经手动展开的就别给他收回去。
                            LaunchedEffect(message.isStreaming, message.content) {
                                if (!message.isStreaming) {
                                    collapseState.recompute(
                                        messageCollapseState(
                                            text = message.content,
                                            screenWidthDp = screenWidthDp,
                                            screenHeightDp = screenHeightDp,
                                            fontScale = density.fontScale,
                                        )
                                    )
                                }
                            }
                            Column(
                                modifier = if (collapseState.collapsible) {
                                    Modifier
                                        // animateContentSize 全程只跟约束走，不碰滚动位置，
                                        // 所以展开/收起不会把用户的阅读位置顶走。
                                        .animateContentSize()
                                        .clipToBounds()
                                        .then(
                                            if (collapseState.expanded) Modifier
                                            else Modifier.heightIn(max = collapseState.maxHeight)
                                        )
                                } else {
                                    Modifier
                                },
                            ) {
                                SimpleMarkdown(
                                    text = message.content,
                                    textColor = textColor,
                                )

                                if (collapseState.collapsible) {
                                    // 「收起」放在内容末尾（用户明确要求「内底部」也要有收起交互），
                                    // 展开后在文末出现，不用回头往上滚。
                                    if (collapseState.expanded) {
                                        Spacer(Modifier.height(8.dp))
                                        BubbleActionLink(
                                            label = "收起",
                                            onClick = { collapseState.expanded = false },
                                            color = textColor.copy(alpha = 0.65f),
                                        )
                                    }
                                }
                            }
                            if (collapseState.collapsible && !collapseState.expanded) {
                                // 折叠态：按钮钉在气泡底部。外面包一层跟气泡同色的 Surface，
                                // 让被截断的文字行从按钮底下「透出来」之前先被遮住，
                                // 视觉上明确是「还有内容没显示」，而不是排版断了。
                                Surface(color = bubbleColor) {
                                    BubbleActionLink(
                                        label = "查看全部",
                                        onClick = { collapseState.expanded = true },
                                        color = MaterialTheme.colorScheme.primary,
                                    )
                                }
                            }
                        }
                    }
                    // 文件卡片（图片卡片合并为网格横排，最多每行 3 张，其余文件卡片纵向展示）
                    if (message.cards.isNotEmpty()) {
                        Spacer(Modifier.height(6.dp))
                        val imageCards = message.cards.filter {
                            com.ethan.agent.ui.components.isImageFileCard(it)
                        }
                        val otherCards = message.cards.filterNot {
                            com.ethan.agent.ui.components.isImageFileCard(it)
                        }
                        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            if (imageCards.isNotEmpty()) {
                                com.ethan.agent.ui.components.ImageFileGrid(
                                    cards = imageCards,
                                    serverUrl = serverUrl,
                                    sessionId = sessionId,
                                    signFile = signFile,
                                )
                            }
                            otherCards.forEach { card ->
                                com.ethan.agent.ui.components.FileCardView(
                                    card = card,
                                    serverUrl = serverUrl,
                                    sessionId = sessionId,
                                    signFile = signFile,
                                )
                            }
                        }
                    }
                    // 流式过程中的「还在跑」提示。
                    //
                    // 之前条件是 `content.isEmpty() && toolSteps.isEmpty()` —— 两个都必须为空。
                    // 问题：外部内核（DSH/Claude）是「调工具 → 想 → 再调」的循环，
                    // 一旦有过工具调用，`toolSteps` 就永久非空，这个提示**再也不会出现**；
                    // 而 ToolTimeline 里的 spinner 只在有 step 处于 running 时显示。
                    // 于是在「工具都跑完了、模型正在想下一句」这段最常见的等待期，
                    // 屏幕上**没有任何进行中动画**，看起来像卡死了。
                    //
                    // 新条件：只要在流式且当前没有正文（正在等下一步），就给提示。
                    // 是否已有工具步骤只影响文案措辞，不再决定要不要显示。
                    if (message.isStreaming && message.content.isEmpty()) {
                        val hasTools = message.toolSteps.isNotEmpty()
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            TypingDots(color = textColor.copy(alpha = 0.7f))
                            Text(
                                // 有工具步骤时说明它在「基于结果继续想」，措辞更贴切
                                if (hasTools) "继续处理中…" else "思考中…",
                                style = MaterialTheme.typography.bodySmall,
                                color = textColor.copy(alpha = 0.7f),
                            )
                        }
                    }
            } // end Column（气泡正文）
            } // end Surface

            // Bottom info bar: timestamp + stats pills
            if (!message.isStreaming) {
                MessageStatsBar(message, isUser)
            }
        }

        // 移动端不再渲染用户头像（见上方「不渲染头像」的说明）。
        // 这里同样**不留** Spacer 占位 —— 右侧的 6dp 间距与 30dp 圆的宽度都要还回去，
        // 否则气泡会被挤窄，「隐藏头像」就只完成了一半。
    }
}

/**
 * 长消息折叠的状态：是否可折叠、当前是否展开、折叠高度上限。
 *
 * 不是 data class —— `expanded` 是可变状态，直接放在普通类里让 Compose 观察到；
 * 用 `rememberSaveable(message.content) { ... }` 重建（内容变了就重置回折叠态，
 * 流式追加期间也不会因为闭包捕获旧值而卡住）。
 */
private class MessageCollapseState(
    collapsible: Boolean,
    maxHeight: androidx.compose.ui.unit.Dp,
    expanded: Boolean,
) {
    var collapsible by mutableStateOf(collapsible)
        private set
    var maxHeight by mutableStateOf(maxHeight)
        private set
    var expanded by mutableStateOf(expanded)

    /**
     * 流结束、正文定型后按最终长度重判一次。
     * 只更新「要不要折叠 / 折叠高度」，**保留** expanded —— 用户手动展开的
     * 状态不能被自动重算收回去（否则刚点开就被关上，很像 bug）。
     * 另外：本来不可折叠的消息若在流结束后变长了，这里也会把它切成可折叠。
     */
    fun recompute(next: MessageCollapseState) {
        if (collapsible == next.collapsible && maxHeight == next.maxHeight) return
        collapsible = next.collapsible
        maxHeight = next.maxHeight
        if (!collapsible) expanded = false
    }
}

/** 折叠高度上限：半屏（用户明确要求「半屏高的最大高度」）。 */
private const val COLLAPSE_SCREEN_FRACTION = 0.5f

/** 用户 query 气泡折叠上限：最多展示 5 行。 */
private const val USER_QUERY_MAX_LINES = 5

/**
 * 估算「半屏高」并判断是否值得折叠。
 *
 * 为什么要估算而不是用 BoxWithConstraints 实测：只有**先**知道是不是长消息，
 * 才谈得上决定要不要给约束。用 `heightIn(max=...)` 配合 `clipToBounds` 来做截断效果，
 * animateContentSize 负责展开/收起的过渡——全过程不触碰 LazyColumn 的滚动位置。
 *
 * 估算依据：bodyMedium 的字号（14sp）与默认行高（约 22sp 行距 ≈ 1.6×），
 * 再把字符宽度按 0.55×字号 粗算。只用来判断「要不要折叠」，允许有偏差；
 * 真的按估算折叠了但内容其实不长，用户点一下「查看全部」即可，不会丢内容。
 * 反过来（长内容被漏判）才是问题，所以这里刻意估得保守一点（宁可多折叠）。
 */
private fun messageCollapseState(
    text: String,
    screenWidthDp: Float,
    screenHeightDp: Float,
    fontScale: Float,
): MessageCollapseState {
    val fontSizeDp = 14f * fontScale          // bodyMedium 基准字号
    val lineHeightDp = fontSizeDp * 1.62f     // 默认行高约 1.6×
    val charWidthDp = fontSizeDp * 0.55f      // 中英混排的粗略平均字宽

    // 气泡内可用宽度：屏宽 - 各项横向留白。
    //
    // 这些常量必须与 MessageBubble 的实际布局一致 —— 改布局（加/减 padding、
    // 换圆角、增删头像）时**必须同步这里**，否则估算会系统性偏大或偏小：
    // 偏大会高估行数、把没超屏的消息也折起来；偏小则长消息漏折叠。
    // 拆成具名常量而不是一个 67f：这样改了布局一眼能看出该动哪一项。
    val rowPaddingDp = 12f * 2      // LazyColumn 横向 padding
    val bubblePaddingDp = 16f * 2   // 气泡内 padding（水平）
    val accentBarDp = 3f            // 左侧角色色条
    val outerPaddingDp = 4f * 2     // 外层 padding
    val chromeWidthDp = rowPaddingDp + bubblePaddingDp + accentBarDp + outerPaddingDp

    // 隐藏头像后**宽度变宽了**（少了 30dp 头像 + 6dp 间距）：这个估算只用来判断
    // 「要不要折叠」，估窄一点意味着「宁可多折一次」，是安全方向。
    val contentWidthDp = (screenWidthDp - chromeWidthDp).coerceAtLeast(fontSizeDp * 8f)

    val charsPerLine = (contentWidthDp / charWidthDp).coerceAtLeast(8f)
    val lineCount = text.split('\n').sumOf { line ->
        // 空行也占一行；超长行按字符数折算（Markdown 标记、英文长词会让它偏小，
        // 所以下面乘了 1.15 的安全系数）
        kotlin.math.ceil(line.length / charsPerLine).toInt().coerceAtLeast(1)
    }
    val estimatedDp = lineCount * lineHeightDp * 1.15f + 24f   // +24dp：气泡上下 padding

    val maxHeightDp = screenHeightDp * COLLAPSE_SCREEN_FRACTION
    // 折叠能省下的高度不到 80dp 就不折腾用户了
    val collapsible = estimatedDp > maxHeightDp + 80f
    return MessageCollapseState(collapsible, maxHeightDp.dp, expanded = false)
}

/** 气泡底部的行内文字按钮（「查看全部」/「收起」）——轻量、不抢视觉重心。 */
@Composable
private fun BubbleActionLink(
    label: String,
    onClick: () -> Unit,
    color: Color,
    fillMaxWidth: Boolean = true,
) {
    Text(
        text = label,
        style = MaterialTheme.typography.labelLarge,
        color = color,
        modifier = (if (fillMaxWidth) Modifier.fillMaxWidth() else Modifier)
            .clickable(onClick = onClick)
            .padding(vertical = 6.dp),
    )
}

@Composable
private fun MessageStatsBar(message: UiMessage, isUser: Boolean = false) {
    val hasStats = message.createdAt != null || message.usage != null || message.ttfbMs != null
    if (!hasStats) return

    Row(
        modifier = Modifier
            .padding(top = 3.dp, start = 4.dp, end = 4.dp)
            .horizontalScroll(rememberScrollState()),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = if (isUser) Arrangement.spacedBy(4.dp, Alignment.End) else Arrangement.spacedBy(4.dp),
    ) {
        // Timestamp
        message.createdAt?.let { ts ->
            val timeStr = remember(ts) {
                val sdf = SimpleDateFormat("HH:mm", Locale.getDefault())
                sdf.format(Date(ts * 1000))
            }
            Text(
                text = timeStr,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
            )
        }

        // Token usage pill —— 对齐 Web 的 `bg-green-500/8 text-green-600/50`
        message.usage?.let { u ->
            if (u.input > 0 || u.output > 0) {
                StatPill(
                    text = "↑${formatTokenCount(u.input)} ↓${formatTokenCount(u.output)}" +
                        if (u.cache > 0) " ⚡${formatTokenCount(u.cache)}" else "",
                    color = StatGreen,
                )
            }
        }

        // TTFB pill —— Web 用 amber-500
        message.ttfbMs?.let { ms ->
            StatPill(text = "TTFB ${formatDuration(ms)}", color = StatAmber)
        }

        // 总耗时 pill —— Web 用 purple-500
        message.totalDurationMs?.let { ms ->
            StatPill(text = "总 ${formatDuration(ms)}", color = StatPurple)
        }

        // 实际生成耗时 pill —— Web 用 green-500
        message.generationDurationMs?.let { ms ->
            StatPill(text = "生成 ${formatDuration(ms)}", color = StatGreen)
        }
    }
}

// Tailwind 500 号色阶——与 Web 的 message-bubble.tsx 中统计药丸一一对应。
// 取 600 号（Tailwind 的 text-<hue>-600）作为文字色，因为 Web 的文字是 600 号。
private val StatAmber = Color(0xFFF59E0B)   // amber-500
private val StatPurple = Color(0xFFA855F7)  // purple-500
private val StatGreen = Color(0xFF22C55E)   // green-500

/**
 * 统计小药丸（token / TTFB / 耗时）。
 *
 * 配色对齐 Web 的 `bg-<hue>-500/8 text-<hue>-600/50`：极淡的底色 + 半透明的同色文字。
 * 之前是用 Material 500 号原色（0xFF4CAF50 之类）+ 12% 底，饱和度太高，在一屏浅色里
 * 几个彩色小方块特别扎眼，也和 Web 的克制观感不一致。
 */
@Composable
private fun StatPill(text: String, color: Color) {
    EthanBadge(
        text = text,
        containerColor = color.copy(alpha = 0.08f),
        contentColor = color.copy(alpha = 0.55f),
        modifier = Modifier.padding(end = 4.dp),
    )
}

private fun formatTokenCount(count: Int): String = when {
    count >= 1000 -> "${count / 1000}k"
    else -> count.toString()
}

private fun formatDuration(ms: Long): String = when {
    ms >= 1000 -> "${String.format("%.1f", ms / 1000.0)}s"
    else -> "${ms}ms"
}
