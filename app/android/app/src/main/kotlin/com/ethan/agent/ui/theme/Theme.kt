package com.ethan.agent.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.runtime.Composable
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * 排版 —— 对齐 Web 的实际用量：正文基准 14sp（`text-sm`）、标题 Medium 字重、
 * 行高偏宽松（`leading-relaxed` ≈ 1.6×）。
 *
 * 上一版是 15sp 正文 + 偏紧行高，正文显得又大又挤，是「不像专业产品」的一部分。
 */
private val EthanTypography = Typography(
    displayLarge = TextStyle(fontWeight = FontWeight.Bold, fontSize = 32.sp, lineHeight = 40.sp, letterSpacing = 0.sp),
    displayMedium = TextStyle(fontWeight = FontWeight.Bold, fontSize = 28.sp, lineHeight = 36.sp, letterSpacing = 0.sp),
    displaySmall = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 24.sp, lineHeight = 32.sp, letterSpacing = 0.sp),
    headlineLarge = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 22.sp, lineHeight = 30.sp, letterSpacing = 0.sp),
    headlineMedium = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 20.sp, lineHeight = 28.sp, letterSpacing = 0.sp),
    headlineSmall = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 18.sp, lineHeight = 26.sp, letterSpacing = 0.sp),
    titleLarge = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 17.sp, lineHeight = 24.sp, letterSpacing = 0.sp),
    titleMedium = TextStyle(fontWeight = FontWeight.Medium, fontSize = 15.sp, lineHeight = 22.sp, letterSpacing = 0.sp),
    titleSmall = TextStyle(fontWeight = FontWeight.Medium, fontSize = 13.sp, lineHeight = 18.sp, letterSpacing = 0.sp),
    bodyLarge = TextStyle(fontWeight = FontWeight.Normal, fontSize = 15.sp, lineHeight = 24.sp, letterSpacing = 0.sp),
    bodyMedium = TextStyle(fontWeight = FontWeight.Normal, fontSize = 14.sp, lineHeight = 22.sp, letterSpacing = 0.sp),
    bodySmall = TextStyle(fontWeight = FontWeight.Normal, fontSize = 12.sp, lineHeight = 18.sp, letterSpacing = 0.sp),
    labelLarge = TextStyle(fontWeight = FontWeight.Medium, fontSize = 14.sp, lineHeight = 20.sp, letterSpacing = 0.sp),
    labelMedium = TextStyle(fontWeight = FontWeight.Medium, fontSize = 12.sp, lineHeight = 16.sp, letterSpacing = 0.sp),
    labelSmall = TextStyle(fontWeight = FontWeight.Medium, fontSize = 11.sp, lineHeight = 15.sp, letterSpacing = 0.1.sp),
)

/**
 * 圆角 —— 对齐 Web 的 `--radius: 0.625rem`（10dp）派生体系。
 *
 * M3 的 shape 阶梯名字是给组件用的，Web 那份是数值阶梯，这里按 M3 的语义把
 * 最常用的档位映射过去：medium=10dp 用作默认（卡片/输入框），large=14dp 用作
 * 大卡片/按钮，extraLarge=18dp 用作气泡/对话框。
 *
 * 上一版是 8/12/16/20/28，整体偏「圆胖可爱」，是塑料感的来源之一。
 */
private val EthanShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(8.dp),
    medium = RoundedCornerShape(10.dp),
    large = RoundedCornerShape(14.dp),
    extraLarge = RoundedCornerShape(18.dp),
)

/**
 * 应用主题。
 *
 * 不做 Android 12+ 动态取色 —— 那会让 Android 配色和 Web/Desktop 彻底脱节，
 * 正是「三端对不上」的原因之一。三端共用同一份主题定义（见 Themes.kt）。
 *
 * @param themeId 原始主题 id（可能是历史值，内部会规范化）
 */
@Composable
fun EthanTheme(
    themeId: String = THEME_FOLLOW_SYSTEM,
    content: @Composable () -> Unit,
) {
    val normalized = normalizeThemeId(themeId)
    val systemDark = isSystemInDarkTheme()

    MaterialTheme(
        colorScheme = colorSchemeFor(normalized, systemDark),
        typography = EthanTypography,
        shapes = EthanShapes,
        content = content,
    )
}
