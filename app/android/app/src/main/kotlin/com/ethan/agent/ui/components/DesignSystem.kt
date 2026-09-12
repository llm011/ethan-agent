package com.ethan.agent.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

/**
 * 应用级设计系统组件。
 *
 * 这里的所有组件都是 **Material 3 组件的薄封装**——只改尺寸/圆角/配色角色，
 * 不重新发明交互。之前项目里手搓的「假 Card / 假 Button」（Surface + Box）看着像
 * Material，但没有水波纹、没有 state layer、没有 disabled 语义，是「塑料感」的根源。
 *
 * 规则：
 * - 一律走 `MaterialTheme.colorScheme` 和 `MaterialTheme.shapes`，不写死颜色/圆角，
 *   这样切换主题时全部一起变。
 * - **不要给卡片加彩色描边**。M3 靠 surface 色阶 + elevation 表达层级，满屏
 *   淡色描边是廉价观感的最大来源。
 */

/**
 * 标准区块卡片。无阴影，靠 `surfaceContainerLow` 的色阶 + 一条 `outlineVariant` 发丝边
 * 与背景区分。
 *
 * 为什么需要这条描边：浅色主题里 Web 的 `--card`(#FFFEFC) 与 `--background`(#FFFDFB)
 * 对比度只有 1.007——单靠色阶是**看不见**的（实测 5 套主题最亮也只有 1.02）。Web 之所以
 * 能分级，是因为它的卡片带 `border: 1px solid var(--border)`。这里照做。
 * 注意用的是中性的 `outlineVariant`，不是早期的 `primary.copy(alpha=.1)` 彩色描边——
 * 后者才是「塑料感」的来源。
 *
 * @param onClick 传入后走 `Card(onClick=...)`，获得真实的涟漪反馈与无障碍语义
 */
@Composable
fun EthanCard(
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    val colors = CardDefaults.cardColors(
        containerColor = MaterialTheme.colorScheme.surfaceContainerLow,
        contentColor = MaterialTheme.colorScheme.onSurface,
    )
    val shape = MaterialTheme.shapes.large
    val border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant)
    if (onClick != null) {
        Card(
            onClick = onClick,
            modifier = modifier.fillMaxWidth(),
            shape = shape,
            colors = colors,
            elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
            border = border,
        ) { content() }
    } else {
        Card(
            modifier = modifier.fillMaxWidth(),
            shape = shape,
            colors = colors,
            elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
            border = border,
        ) { content() }
    }
}

/** 带内边距的卡片，省掉调用点重复写 `Column(Modifier.padding(...))`。 */
@Composable
fun EthanCard(
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    contentPadding: PaddingValues,
    content: @Composable ColumnScope.() -> Unit,
) {
    EthanCard(modifier = modifier, onClick = onClick) {
        Column(Modifier.padding(contentPadding), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            content()
        }
    }
}

/**
 * 区块标题。用于替代各屏幕里手写的标题 Row。
 *
 * @param action 右侧可选操作（如「新建」「全部」）
 */
@Composable
fun EthanSectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    action: (@Composable () -> Unit)? = null,
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                title,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            if (subtitle != null) {
                Text(
                    subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        action?.invoke()
    }
}

/**
 * 统一的空状态：图标 + 标题 + 说明，垂直居中。
 * 替代此前散落各处的「一行灰字」式空状态。
 */
@Composable
fun EthanEmptyState(
    title: String,
    modifier: Modifier = Modifier,
    description: String? = null,
    icon: ImageVector? = null,
    action: (@Composable () -> Unit)? = null,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 32.dp, vertical = 48.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        if (icon != null) {
            Surface(
                shape = CircleShape,
                color = MaterialTheme.colorScheme.surfaceContainerHigh,
                modifier = Modifier.size(56.dp),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        icon,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(26.dp),
                    )
                }
            }
            Spacer(Modifier.height(16.dp))
        }
        Text(
            title,
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.onSurface,
            textAlign = TextAlign.Center,
        )
        if (description != null) {
            Spacer(Modifier.height(6.dp))
            Text(
                description,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
        }
        if (action != null) {
            Spacer(Modifier.height(16.dp))
            action()
        }
    }
}

/**
 * 统一徽章：小圆角药丸 + 低饱和底色。
 * 替代此前 3 种各写一遍的徽章实现。
 *
 * @param containerColor 默认用中性色；语义色（error/primary 等）由调用方传入
 */
@Composable
fun EthanBadge(
    text: String,
    modifier: Modifier = Modifier,
    containerColor: Color = MaterialTheme.colorScheme.secondaryContainer,
    contentColor: Color = MaterialTheme.colorScheme.onSecondaryContainer,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(50),
        color = containerColor,
        contentColor = contentColor,
    ) {
        Text(
            text,
            style = MaterialTheme.typography.labelSmall,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

/**
 * 统一的列表行：左侧图标（可选）、标题 + 副标题、右侧尾部（可选）。
 *
 * 替代 `AppDrawer` 与 `MoreScreen` 里两份几乎相同的图标行实现。用真正的
 * `Card(onClick)` 以获得涟漪反馈。
 */
@Composable
fun EthanListRow(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    icon: ImageVector? = null,
    onClick: (() -> Unit)? = null,
    trailing: (@Composable RowScope.() -> Unit)? = null,
) {
    val rowContent: @Composable RowScope.() -> Unit = {
        if (icon != null) {
            Surface(
                shape = MaterialTheme.shapes.small,
                color = MaterialTheme.colorScheme.secondaryContainer,
                contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                modifier = Modifier.size(34.dp),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp))
                }
            }
            Spacer(Modifier.width(12.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(
                title,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (subtitle != null) {
                Text(
                    subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        trailing?.invoke(this)
    }

    val colors = CardDefaults.cardColors(
        containerColor = Color.Transparent,
        contentColor = MaterialTheme.colorScheme.onSurface,
    )
    val shape = MaterialTheme.shapes.medium
    if (onClick != null) {
        Card(
            onClick = onClick,
            modifier = modifier.fillMaxWidth(),
            shape = shape,
            colors = colors,
            elevation = CardDefaults.cardElevation(defaultElevation = 0.dp),
        ) {
            Row(
                Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                content = rowContent,
            )
        }
    } else {
        Row(
            modifier = modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            content = rowContent,
        )
    }
}

/** 分组容器：把若干行/卡片包成一个视觉整体（替代满屏带描边的小卡片）。 */
@Composable
fun EthanGroup(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.large,
        color = MaterialTheme.colorScheme.surfaceContainerLow,
    ) {
        Column(content = content)
    }
}

/** 组内分隔线，两侧留白与内容对齐。 */
@Composable
fun EthanGroupDivider() {
    androidx.compose.material3.HorizontalDivider(
        modifier = Modifier.padding(horizontal = 12.dp),
        color = MaterialTheme.colorScheme.outlineVariant,
        thickness = 1.dp,
    )
}

// ── 语义状态色 ────────────────────────────────────────────────────────────────
// 成功/失败这类「状态」色不属于任何一套主题的配色，切主题时不应该变——所以不放进
// ColorScheme，而是固定常量。取值对齐 Web 用的 Tailwind green-500 / red-500，
// 避免各处再写 0xFF43A047、0xFF4CAF50 这种各写各的绿。
// 注意：失败态在能拿到 MaterialTheme 的地方优先用 `colorScheme.error`（它随主题走，
// 深色下会自动变亮），这里的 StatusError 只给非 Composable 上下文兜底。

/** green-500 */
val StatusSuccess = Color(0xFF22C55E)

/** red-500 */
val StatusError = Color(0xFFE53935)
