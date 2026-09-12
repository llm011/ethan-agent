package com.ethan.agent.ui.theme

import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.ui.graphics.Color

/**
 * 主题注册表 —— 与 Web(`web/components/chat/themes.ts`) / Desktop 共享同一份定义。
 *
 * 每套主题的来源是 `web/app/globals.css` 里的一组 CSS 变量，这里的十六进制值是把
 * 那些 OKLCH 值离线精确转换到 sRGB 的结果（Compose 的 Color 是 sRGB 空间）。
 * **改动需三端同步**：Web / Desktop / Android。
 *
 * 只有 Web 上存在的主题才会出现在这里 —— 历史遗留的 honey / matcha / lavender /
 * sky_blue 已移除（它们从未在 Web 上出现过，选出来和 Web 完全对不上）。
 */
enum class EthanThemeId(
    val id: String,
    val label: String,
    /** 调色盘预览用的三个代表色（背景 / 主色 / 辅色），纯展示、不参与实际配色 */
    val swatch: List<Color>,
    val isDark: Boolean,
) {
    QINGWA(
        id = "qingwa",
        label = "青瓦",
        swatch = listOf(Color(0xFFF5F7F2), Color(0xFF6F9B86), Color(0xFF8FB4C9)),
        isDark = false,
    ),
    WARM(
        id = "warm",
        label = "暖橙",
        swatch = listOf(Color(0xFFFDFBF8), Color(0xFFC98A52), Color(0xFFE8D9C8)),
        isDark = false,
    ),
    PAPER(
        id = "paper",
        label = "素纸",
        swatch = listOf(Color(0xFFFBFAF7), Color(0xFF8A7F6D), Color(0xFFE7E2D8)),
        isDark = false,
    ),
    MIST(
        id = "mist",
        label = "微雾",
        swatch = listOf(Color(0xFFFBFCFD), Color(0xFF6B7787), Color(0xFFE4E8EC)),
        isDark = false,
    ),
    DARK(
        id = "dark",
        label = "深色",
        swatch = listOf(Color(0xFF1F1F1F), Color(0xFFE8E8E8), Color(0xFF3A3A3A)),
        isDark = true,
    ),
    ;

    companion object {
        val DEFAULT = QINGWA

        fun fromIdOrNull(raw: String?): EthanThemeId? =
            raw?.let { v -> entries.firstOrNull { it.id == v } }
    }
}

/** 跟随系统亮暗模式时使用的伪主题 id（不是 EthanThemeId 的成员）。 */
const val THEME_FOLLOW_SYSTEM = "system"
private const val THEME_LEGACY_LIGHT = "light"

/**
 * 把任意历史配置值规范化为合法主题 —— 照搬 Web 的 `normalizeThemeId`。
 *
 * 兼容早期只有 dark/light 的版本，以及那些已被删除的主题（映射到观感最接近的
 * 一套，而不是粗暴地回落到默认值，免得用户升级后发现主题「自己变了」）。
 */
fun normalizeThemeId(raw: String?): String {
    if (raw.isNullOrBlank()) return THEME_FOLLOW_SYSTEM
    if (raw == THEME_FOLLOW_SYSTEM) return THEME_FOLLOW_SYSTEM
    if (EthanThemeId.fromIdOrNull(raw) != null) return raw
    return when (raw) {
        // 早期 light 即暖橙
        THEME_LEGACY_LIGHT -> EthanThemeId.WARM.id
        "honey" -> EthanThemeId.WARM.id        // 发黄暖调 → 暖橙
        "warm_orange" -> EthanThemeId.WARM.id
        "matcha" -> EthanThemeId.QINGWA.id     // 绿调 → 青瓦
        "lavender" -> EthanThemeId.MIST.id     // 淡紫冷调 → 微雾
        "sky_blue" -> EthanThemeId.MIST.id     // 蓝调 → 微雾
        "plain_paper" -> EthanThemeId.PAPER.id
        else -> EthanThemeId.DEFAULT.id
    }
}

// ── 青瓦（默认）：取自吉卜力水彩——粉墙、青瓦、林荫绿、天空蓝 ──────────────────

private val QingwaLight = lightColorScheme(
    primary = Color(0xFF4F8566),
    onPrimary = Color(0xFFF9FDFA),
    primaryContainer = Color(0xFFC7E9EA),
    onPrimaryContainer = Color(0xFF11393E),
    secondary = Color(0xFFD8EDEB),
    onSecondary = Color(0xFF223A3B),
    secondaryContainer = Color(0xFFD8EDEB),
    onSecondaryContainer = Color(0xFF223A3B),
    tertiary = Color(0xFF5A8D72),
    onTertiary = Color(0xFFF9FDFA),
    tertiaryContainer = Color(0xFFC7E9EA),
    onTertiaryContainer = Color(0xFF11393E),
    background = Color(0xFFF8FCF9),
    onBackground = Color(0xFF22322B),
    surface = Color(0xFFFBFEFC),
    onSurface = Color(0xFF22322B),
    surfaceVariant = Color(0xFFE7F2EB),
    onSurfaceVariant = Color(0xFF4E6359),
    surfaceContainerLowest = Color(0xFFFCFFFC),
    surfaceContainerLow = Color(0xFFFBFEFC),
    surfaceContainer = Color(0xFFE7F4EE),
    surfaceContainerHigh = Color(0xFFE7F2EB),
    surfaceContainerHighest = Color(0xFFE7F2EB),
    outline = Color(0xFFDDE8E2),
    outlineVariant = Color(0xFFD5E1DB),
    error = Color(0xFFE7000B),
    onError = Color(0xFFFFFFFF),
    errorContainer = Color(0xFFFFDAD6),
    onErrorContainer = Color(0xFF410002),
    scrim = Color(0xFF000000),
    inverseSurface = Color(0xFF273730),
    inverseOnSurface = Color(0xFFE7F4EE),
)

private val QingwaDark = darkColorScheme(
    primary = Color(0xFF8FC7A8),
    onPrimary = Color(0xFF17352A),
    primaryContainer = Color(0xFF2C4E40),
    onPrimaryContainer = Color(0xFFC7E9EA),
    secondary = Color(0xFF6F9B86),
    onSecondary = Color(0xFFF9FDFA),
    secondaryContainer = Color(0xFF2C4E40),
    onSecondaryContainer = Color(0xFFD8EDEB),
    tertiary = Color(0xFF8FB4C9),
    onTertiary = Color(0xFF11393E),
    tertiaryContainer = Color(0xFF33505A),
    onTertiaryContainer = Color(0xFFC7E9EA),
    background = Color(0xFF0F1512),
    onBackground = Color(0xFFDDE8E2),
    surface = Color(0xFF151B18),
    onSurface = Color(0xFFDDE8E2),
    surfaceVariant = Color(0xFF2B3630),
    onSurfaceVariant = Color(0xFFA8BBB2),
    surfaceContainerLowest = Color(0xFF0B100D),
    surfaceContainerLow = Color(0xFF151B18),
    surfaceContainer = Color(0xFF1C231F),
    surfaceContainerHigh = Color(0xFF242C27),
    surfaceContainerHighest = Color(0xFF2B3630),
    outline = Color(0xFF7A8C83),
    outlineVariant = Color(0xFF3B4741),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
    errorContainer = Color(0xFF93000A),
    onErrorContainer = Color(0xFFFFDAD6),
    scrim = Color(0xFF000000),
    inverseSurface = Color(0xFFDDE8E2),
    inverseOnSurface = Color(0xFF22322B),
)

// ── 暖橙：原橙色主题整体调浅、降饱和 ────────────────────────────────────────

private val WarmLight = lightColorScheme(
    primary = Color(0xFFC3805A),
    onPrimary = Color(0xFFFCFCFC),
    primaryContainer = Color(0xFFF9E3D5),
    onPrimaryContainer = Color(0xFF4D3020),
    secondary = Color(0xFFF7ECE4),
    onSecondary = Color(0xFF45342A),
    secondaryContainer = Color(0xFFF7ECE4),
    onSecondaryContainer = Color(0xFF45342A),
    tertiary = Color(0xFF9C6B4A),
    onTertiary = Color(0xFFFCFCFC),
    tertiaryContainer = Color(0xFFF9E3D5),
    onTertiaryContainer = Color(0xFF4D3020),
    background = Color(0xFFFFFDFB),
    onBackground = Color(0xFF2B221C),
    surface = Color(0xFFFFFEFC),
    onSurface = Color(0xFF2B221C),
    surfaceVariant = Color(0xFFF7EEE8),
    onSurfaceVariant = Color(0xFF7D6659),
    surfaceContainerLowest = Color(0xFFFFFEFC),
    surfaceContainerLow = Color(0xFFFFFEFC),
    surfaceContainer = Color(0xFFFDF5EF),
    surfaceContainerHigh = Color(0xFFF7EEE8),
    surfaceContainerHighest = Color(0xFFF7EEE8),
    outline = Color(0xFFEEE6E0),
    outlineVariant = Color(0xFFE9DFD9),
    error = Color(0xFFE7000B),
    onError = Color(0xFFFFFFFF),
    errorContainer = Color(0xFFFFDAD6),
    onErrorContainer = Color(0xFF410002),
    scrim = Color(0xFF000000),
    inverseSurface = Color(0xFF312620),
    inverseOnSurface = Color(0xFFFDF5EF),
)

private val WarmDark = darkColorScheme(
    primary = Color(0xFFE0A986),
    onPrimary = Color(0xFF442A18),
    primaryContainer = Color(0xFF63422B),
    onPrimaryContainer = Color(0xFFF9E3D5),
    secondary = Color(0xFFC3805A),
    onSecondary = Color(0xFFFCFCFC),
    secondaryContainer = Color(0xFF63422B),
    onSecondaryContainer = Color(0xFFF7ECE4),
    tertiary = Color(0xFFE0B48F),
    onTertiary = Color(0xFF4D3020),
    tertiaryContainer = Color(0xFF6B4630),
    onTertiaryContainer = Color(0xFFF9E3D5),
    background = Color(0xFF17120F),
    onBackground = Color(0xFFEEE6E0),
    surface = Color(0xFF1D1713),
    onSurface = Color(0xFFEEE6E0),
    surfaceVariant = Color(0xFF382E28),
    onSurfaceVariant = Color(0xFFC4B0A4),
    surfaceContainerLowest = Color(0xFF120D0A),
    surfaceContainerLow = Color(0xFF1D1713),
    surfaceContainer = Color(0xFF241D19),
    surfaceContainerHigh = Color(0xFF2D2620),
    surfaceContainerHighest = Color(0xFF382E28),
    outline = Color(0xFF9C8878),
    outlineVariant = Color(0xFF4A3E36),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
    errorContainer = Color(0xFF93000A),
    onErrorContainer = Color(0xFFFFDAD6),
    scrim = Color(0xFF000000),
    inverseSurface = Color(0xFFEEE6E0),
    inverseOnSurface = Color(0xFF2B221C),
)

// ── 素纸：暖白 / 米色 / 淡棕，极低饱和，安静朴素 ─────────────────────────────

private val PaperLight = lightColorScheme(
    primary = Color(0xFF70685B),
    onPrimary = Color(0xFFFDFCF9),
    primaryContainer = Color(0xFFECE7DF),
    onPrimaryContainer = Color(0xFF383229),
    secondary = Color(0xFFF1EEE9),
    onSecondary = Color(0xFF3C3730),
    secondaryContainer = Color(0xFFF1EEE9),
    onSecondaryContainer = Color(0xFF3C3730),
    tertiary = Color(0xFF8A7F6D),
    onTertiary = Color(0xFFFDFCF9),
    tertiaryContainer = Color(0xFFECE7DF),
    onTertiaryContainer = Color(0xFF383229),
    background = Color(0xFFFEFDFA),
    onBackground = Color(0xFF2B2823),
    surface = Color(0xFFFFFEFC),
    onSurface = Color(0xFF2B2823),
    surfaceVariant = Color(0xFFF2F0EB),
    onSurfaceVariant = Color(0xFF6D6860),
    surfaceContainerLowest = Color(0xFFFFFEFC),
    surfaceContainerLow = Color(0xFFFFFEFC),
    surfaceContainer = Color(0xFFF7F4EE),
    surfaceContainerHigh = Color(0xFFF2F0EB),
    surfaceContainerHighest = Color(0xFFF2F0EB),
    outline = Color(0xFFE8E6E1),
    outlineVariant = Color(0xFFE2DFDA),
    error = Color(0xFFE7000B),
    onError = Color(0xFFFFFFFF),
    errorContainer = Color(0xFFFFDAD6),
    onErrorContainer = Color(0xFF410002),
    scrim = Color(0xFF000000),
    inverseSurface = Color(0xFF312D27),
    inverseOnSurface = Color(0xFFF7F4EE),
)

private val PaperDark = darkColorScheme(
    primary = Color(0xFFBDB3A1),
    onPrimary = Color(0xFF2E2A23),
    primaryContainer = Color(0xFF453E34),
    onPrimaryContainer = Color(0xFFECE7DF),
    secondary = Color(0xFF70685B),
    onSecondary = Color(0xFFFDFCF9),
    secondaryContainer = Color(0xFF453E34),
    onSecondaryContainer = Color(0xFFF1EEE9),
    tertiary = Color(0xFFB0A48F),
    onTertiary = Color(0xFF383229),
    tertiaryContainer = Color(0xFF4C4636),
    onTertiaryContainer = Color(0xFFECE7DF),
    background = Color(0xFF141310),
    onBackground = Color(0xFFE8E6E1),
    surface = Color(0xFF1A1815),
    onSurface = Color(0xFFE8E6E1),
    surfaceVariant = Color(0xFF332F29),
    onSurfaceVariant = Color(0xFFB8B2A8),
    surfaceContainerLowest = Color(0xFF0F0E0C),
    surfaceContainerLow = Color(0xFF1A1815),
    surfaceContainer = Color(0xFF211E1A),
    surfaceContainerHigh = Color(0xFF2A2722),
    surfaceContainerHighest = Color(0xFF332F29),
    outline = Color(0xFF918A7E),
    outlineVariant = Color(0xFF443F38),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
    errorContainer = Color(0xFF93000A),
    onErrorContainer = Color(0xFFFFDAD6),
    scrim = Color(0xFF000000),
    inverseSurface = Color(0xFFE8E6E1),
    inverseOnSurface = Color(0xFF2B2823),
)

// ── 微雾：冷调白 / 灰 / 蓝灰，克制干净，适合久看 ─────────────────────────────

private val MistLight = lightColorScheme(
    primary = Color(0xFF5E6E7E),
    onPrimary = Color(0xFFFBFCFD),
    primaryContainer = Color(0xFFDEE8EF),
    onPrimaryContainer = Color(0xFF2C3741),
    secondary = Color(0xFFE8EEF2),
    onSecondary = Color(0xFF313941),
    secondaryContainer = Color(0xFFE8EEF2),
    onSecondaryContainer = Color(0xFF313941),
    tertiary = Color(0xFF6B7787),
    onTertiary = Color(0xFFFBFCFD),
    tertiaryContainer = Color(0xFFDEE8EF),
    onTertiaryContainer = Color(0xFF2C3741),
    background = Color(0xFFFCFDFE),
    onBackground = Color(0xFF25292F),
    surface = Color(0xFFFDFEFF),
    onSurface = Color(0xFF25292F),
    surfaceVariant = Color(0xFFEBEFF2),
    onSurfaceVariant = Color(0xFF636D77),
    surfaceContainerLowest = Color(0xFFFDFEFF),
    surfaceContainerLow = Color(0xFFFDFEFF),
    surfaceContainer = Color(0xFFF0F4F7),
    surfaceContainerHigh = Color(0xFFEBEFF2),
    surfaceContainerHighest = Color(0xFFEBEFF2),
    outline = Color(0xFFE2E7EA),
    outlineVariant = Color(0xFFDBE0E4),
    error = Color(0xFFE7000B),
    onError = Color(0xFFFFFFFF),
    errorContainer = Color(0xFFFFDAD6),
    onErrorContainer = Color(0xFF410002),
    scrim = Color(0xFF000000),
    inverseSurface = Color(0xFF292E35),
    inverseOnSurface = Color(0xFFF0F4F7),
)

private val MistDark = darkColorScheme(
    primary = Color(0xFFA9BACC),
    onPrimary = Color(0xFF23303B),
    primaryContainer = Color(0xFF3A4854),
    onPrimaryContainer = Color(0xFFDEE8EF),
    secondary = Color(0xFF5E6E7E),
    onSecondary = Color(0xFFFBFCFD),
    secondaryContainer = Color(0xFF3A4854),
    onSecondaryContainer = Color(0xFFE8EEF2),
    tertiary = Color(0xFF9FB0C0),
    onTertiary = Color(0xFF2C3741),
    tertiaryContainer = Color(0xFF41505D),
    onTertiaryContainer = Color(0xFFDEE8EF),
    background = Color(0xFF0F1216),
    onBackground = Color(0xFFE2E7EA),
    surface = Color(0xFF15191D),
    onSurface = Color(0xFFE2E7EA),
    surfaceVariant = Color(0xFF2C333A),
    onSurfaceVariant = Color(0xFFAEB8C2),
    surfaceContainerLowest = Color(0xFF0A0D10),
    surfaceContainerLow = Color(0xFF15191D),
    surfaceContainer = Color(0xFF1C2126),
    surfaceContainerHigh = Color(0xFF242A30),
    surfaceContainerHighest = Color(0xFF2C333A),
    outline = Color(0xFF8892A0),
    outlineVariant = Color(0xFF3D454E),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
    errorContainer = Color(0xFF93000A),
    onErrorContainer = Color(0xFFFFDAD6),
    scrim = Color(0xFF000000),
    inverseSurface = Color(0xFFE2E7EA),
    inverseOnSurface = Color(0xFF25292F),
)

// ── 深色：中性黑白灰（与 Web `.dark` 的色板一致） ────────────────────────────

private val NeutralDark = darkColorScheme(
    primary = Color(0xFFE5E5E5),
    onPrimary = Color(0xFF171717),
    primaryContainer = Color(0xFF262626),
    onPrimaryContainer = Color(0xFFFAFAFA),
    secondary = Color(0xFF262626),
    onSecondary = Color(0xFFFAFAFA),
    secondaryContainer = Color(0xFF262626),
    onSecondaryContainer = Color(0xFFFAFAFA),
    tertiary = Color(0xFFA1A1A1),
    onTertiary = Color(0xFF171717),
    tertiaryContainer = Color(0xFF262626),
    onTertiaryContainer = Color(0xFFFAFAFA),
    background = Color(0xFF0A0A0A),
    onBackground = Color(0xFFFAFAFA),
    surface = Color(0xFF171717),
    onSurface = Color(0xFFFAFAFA),
    // Web 的 --border / --input 是白色的 10% / 15% alpha
    surfaceVariant = Color(0x14FFFFFF),
    onSurfaceVariant = Color(0xFFA1A1A1),
    surfaceContainerLowest = Color(0xFF0A0A0A),
    surfaceContainerLow = Color(0xFF171717),
    surfaceContainer = Color(0xFF171717),
    surfaceContainerHigh = Color(0xFF262626),
    surfaceContainerHighest = Color(0xFF262626),
    outline = Color(0x26FFFFFF),
    outlineVariant = Color(0x1AFFFFFF),
    error = Color(0xFFFF6467),
    onError = Color(0xFF171717),
    errorContainer = Color(0xFF5C1A1C),
    onErrorContainer = Color(0xFFFFDAD6),
    scrim = Color(0xFF000000),
    inverseSurface = Color(0xFFFAFAFA),
    inverseOnSurface = Color(0xFF171717),
)

/**
 * 取主题对应的 ColorScheme。
 *
 * @param themeId 已规范化的主题 id；`THEME_FOLLOW_SYSTEM` 时在青瓦的亮/暗两套之间跟随系统
 * @param systemDark 系统是否处于深色模式
 */
fun colorSchemeFor(themeId: String, systemDark: Boolean) = when (themeId) {
    EthanThemeId.WARM.id -> if (systemDark) WarmDark else WarmLight
    EthanThemeId.PAPER.id -> if (systemDark) PaperDark else PaperLight
    EthanThemeId.MIST.id -> if (systemDark) MistDark else MistLight
    EthanThemeId.DARK.id -> NeutralDark
    // 青瓦 + 跟随系统（默认）
    else -> if (systemDark) QingwaDark else QingwaLight
}
