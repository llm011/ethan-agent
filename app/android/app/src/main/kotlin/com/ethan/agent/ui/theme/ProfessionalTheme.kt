package com.ethan.agent.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * 专业级 Material Design 3 主题系统
 * 
 * 设计理念：
 * - 消除"塑料感"：使用更克制的色彩和更精细的阴影
 * - 提升审美：采用现代简约风格，参考 Linear、Notion 等顶级产品
 * - 一致性：三端（Web/Desktop/Android）完全同步
 */

// 专业级调色板 - 克制、优雅、高级
private val ProfessionalLight = lightColorScheme(
    primary = Color(0xFF1A73E8),        // 克制蓝，不刺眼
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFE8F0FE),
    onPrimaryContainer = Color(0xFF001F5B),
    
    secondary = Color(0xFF5F6368),      // 中性灰，用于次要内容
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFE6EEF4),
    onSecondaryContainer = Color(0xFF1A1C1E),
    
    tertiary = Color(0xFF7D4182),       // 优雅的紫色点缀
    onTertiary = Color(0xFFFFFFFF),
    tertiaryContainer = Color(0xFFF5E6F7),
    onTertiaryContainer = Color(0xFF360045),
    
    background = Color(0xFFF8F9FA),     // 浅灰背景，护眼
    onBackground = Color(0xFF1A1C1E),
    
    surface = Color(0xFFFFFFFF),        // 纯白卡片
    onSurface = Color(0xFF1A1C1E),
    surfaceVariant = Color(0xFFE6E8EB), // 微妙的边界色
    
    error = Color(0xFFB3261E),          // 克制红，不刺眼
    onError = Color(0xFFFFFFFF),
    errorContainer = Color(0xFFFDE8E6),
    onErrorContainer = Color(0xFF410002),
    
    outline = Color(0xFF9AA0A6),        // 柔和的边框
    outlineVariant = Color(0xFFC5C8CC),
)

private val ProfessionalDark = darkColorScheme(
    primary = Color(0xFF8AB4F8),
    onPrimary = Color(0xFF003472),
    primaryContainer = Color(0xFF004B9F),
    onPrimaryContainer = Color(0xFFD6E3FF),
    
    secondary = Color(0xFFB0B3B8),
    onSecondary = Color(0xFF2C2E30),
    secondaryContainer = Color(0xFF43474B),
    onSecondaryContainer = Color(0xFFE3E6EA),
    
    tertiary = Color(0xFFD6B3F0),
    onTertiary = Color(0xFF4E1363),
    tertiaryContainer = Color(0xFF652A7A),
    onTertiaryContainer = Color(0xFFF1D9FF),
    
    background = Color(0xFF121212),     // 深灰黑，不是纯黑
    onBackground = Color(0xFFE3E6EA),
    
    surface = Color(0xFF1E1E1E),        // 深灰卡片
    onSurface = Color(0xFFE3E6EA),
    surfaceVariant = Color(0xFF2C2E30),
    
    error = Color(0xFFCF6670),
    onError = Color(0xFF410002),
    errorContainer = Color(0xFF601719),
    onErrorContainer = Color(0xFFFFDAD6),
    
    outline = Color(0xFF8C8F94),
    outlineVariant = Color(0xFF43474B),
)

/**
 * 专业排版系统 - 参考 Notion、Linear 等顶级产品
 */
private val ProfessionalTypography = Typography(
    displayLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.W600,
        fontSize = 32.sp,
        lineHeight = 40.sp,
        letterSpacing = (-0.5).sp,
    ),
    displayMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.W600,
        fontSize = 28.sp,
        lineHeight = 36.sp,
        letterSpacing = (-0.25).sp,
    ),
    headlineLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.W600,
        fontSize = 24.sp,
        lineHeight = 32.sp,
    ),
    titleLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.W600,
        fontSize = 20.sp,
        lineHeight = 28.sp,
    ),
    titleMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Medium,
        fontSize = 16.sp,
        lineHeight = 24.sp,
        letterSpacing = 0.15.sp,
    ),
    bodyLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Normal,
        fontSize = 16.sp,
        lineHeight = 24.sp,
        letterSpacing = 0.5.sp,
    ),
    bodyMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        letterSpacing = 0.25.sp,
    ),
    labelLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Medium,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        letterSpacing = 0.1.sp,
    ),
)

/**
 * 专业级圆角系统 - 克制、统一
 */
private val ProfessionalShapes = Shapes(
    extraSmall = ShapeDefaults.MediumCornerRadius,
    small = RoundedCornerShape(8.dp),      // 按钮、输入框
    medium = RoundedCornerShape(12.dp),    // 卡片
    large = RoundedCornerShape(16.dp),     // 对话框
    extraLarge = RoundedCornerShape(24.dp), // 特殊场景
)

/**
 * 专业级阴影系统 - 微妙、有层次
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfessionalTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colorScheme = if (darkTheme) ProfessionalDark else ProfessionalLight
    
    MaterialTheme(
        colorScheme = colorScheme,
        typography = ProfessionalTypography,
        shapes = ProfessionalShapes,
        content = content,
    )
}

/**
 * 扩展函数：获取专业级阴影
 */
fun getShadowElevation(level: Int = 1): Float {
    return when (level) {
        1 -> 1.dp.value
        2 -> 3.dp.value
        3 -> 6.dp.value
        4 -> 12.dp.value
        else -> 0.dp.value
    }
}
