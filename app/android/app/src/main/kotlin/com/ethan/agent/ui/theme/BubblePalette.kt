package com.ethan.agent.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.ui.graphics.Color
import com.ethan.agent.shared.viewmodel.MessageRoleKind

/**
 * 消息气泡的角色配色（**移动端专用**）。
 *
 * 背景：移动端要隐藏头像（头像在窄屏上吃掉 36dp 横向空间，正文被挤得只剩一半），
 * 而头像原本承担了「谁在说话」的识别职责。隐藏之后必须换一种不占宽度的线索 ——
 * 颜色。桌面端不受影响，仍走 Web 那套「头像 + 单色气泡」。
 *
 * 设计约束（按重要性排序）：
 *  1. **不能只靠颜色区分**：色盲用户看不到红绿差别。所以每种角色除了颜色，
 *     都还有一个**文字角色名**（[bubbleRoleLabel]：我 / Ethan / 工具 / 系统）。
 *     颜色是加速识别的线索，不是唯一线索 —— 去掉头像时如果把识别职责全押在颜色上，
 *     对色盲用户就是净损失。
 *  2. **必须跟主题走**：全部从 `MaterialTheme.colorScheme` 的角色色派生（`primary`
 *     / `tertiary` / `secondary` / `outline`），不写死十六进制。5 套主题 + 亮暗
 *     切换时自动一起变，这正是设计系统要求「不写死颜色」的原因。
 *  3. **对比度**：气泡底色用极低透明度（0.08~0.10）压在 surface 上，正文仍用
 *     `onSurface`。这样无论主题是深是浅，文字对比度都有保证（不是「浅底浅字」）。
 *
 * 为什么不用 `surfaceVariant` 这类中性色做底色：中性色无法区分角色，而给每个角色
 * 一个低饱和的彩色底，既能区分又不会像早期那种「实心 primary + onPrimary 文字」
 * 一样刺眼。
 */
@Composable
@ReadOnlyComposable
fun bubbleContainerColor(kind: MessageRoleKind): Color = when (kind) {
    // 用户：主色（蓝系）。与 Web 的 `bg-primary/10` 同源，视觉上延续而非另起一套。
    MessageRoleKind.User -> MaterialTheme.colorScheme.primary.copy(alpha = 0.10f)
    // 助手：tertiary（青绿系）。刻意避开 primary，否则用户和助手是两个深浅不同的蓝，
    // 在色弱视角下几乎一样。
    MessageRoleKind.Assistant -> MaterialTheme.colorScheme.tertiary.copy(alpha = 0.10f)
    // 工具：secondary（紫系），比对话内容更「中性」，不喧宾夺主。
    MessageRoleKind.Tool -> MaterialTheme.colorScheme.secondary.copy(alpha = 0.08f)
    // 系统：纯中性，因为它本来就不代表任何一个「说话的人」。
    MessageRoleKind.System -> MaterialTheme.colorScheme.surfaceVariant
}

/**
 * 气泡左侧的强调色条 —— 隐藏头像后的主要识别标记。
 *
 * 与 [bubbleContainerColor] 用同一个色但**不透明**：低透明度的底色在大面积上很柔和，
 * 但一条 3dp 的细线如果也是 10% 透明度就彻底看不见了。所以色条取实色，
 * 靠「细 + 短」来控制视觉重量，而不是靠透明度。
 */
@Composable
@ReadOnlyComposable
fun bubbleAccentColor(kind: MessageRoleKind): Color = when (kind) {
    MessageRoleKind.User -> MaterialTheme.colorScheme.primary
    MessageRoleKind.Assistant -> MaterialTheme.colorScheme.tertiary
    MessageRoleKind.Tool -> MaterialTheme.colorScheme.secondary
    // 系统消息不参与角色区分，不给色条（返回透明，绘制时会被跳过）。
    MessageRoleKind.System -> Color.Transparent
}

/**
 * 角色名称，显示在气泡上方的小字行。
 *
 * 这是**无障碍的主要兜底**：颜色可能被色盲用户忽略、可能被截图压缩糊掉，
 * 但「Ethan」「我」这两个词一定读得出来。桌面端的头像旁边也有同样的名字行。
 */
@Composable
@ReadOnlyComposable
fun bubbleRoleLabel(kind: MessageRoleKind): String = when (kind) {
    MessageRoleKind.User -> "我"
    MessageRoleKind.Assistant -> "Ethan"
    MessageRoleKind.Tool -> "工具"
    MessageRoleKind.System -> "系统"
}

/**
 * 角色名的文字色。
 *
 * 一律用中性色（`onSurfaceVariant`），**刻意不跟随角色的彩色**：小字号的彩色文字
 * 在低饱和主题下对比度容易不达标，而名字行已经紧挨着一条实色色条了，
 * 颜色信息足够，文字只需保证可读。
 */
@Composable
@ReadOnlyComposable
fun bubbleRoleLabelColor(): Color = MaterialTheme.colorScheme.onSurfaceVariant
