package com.ethan.agent.ui.theme

import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color

// ── Global theme state ───────────────────────────────────────────────────────
// Updated by SettingsViewModel.setTheme(); read by EthanTheme composable.
object ThemeState {
    var themeId by mutableStateOf("system")
}

// ── Cute Theme Palette Helpers ────────────────────────────────────────────────

// Shared warm background tones for cute themes
private val CuteBackground = Color(0xFFFFFDF7)
private val CuteSurface = Color(0xFFFFFFFF)
private val CuteOnBackground = Color(0xFF5D4E37) // 暖棕色文字
private val CuteOnSurface = Color(0xFF5D4E37)
private val CuteSecondaryText = Color(0xFF9E8E7E)

// ── Honey 暖黄蜜糖 ──────────────────────────────────────────────────────────
val HoneyLight = lightColorScheme(
    primary            = Color(0xFFF5A623),
    onPrimary          = Color(0xFFFFFFFF),
    primaryContainer   = Color(0xFFFFF3D6),
    onPrimaryContainer = Color(0xFF4A3800),
    secondary          = Color(0xFFE8985A),
    onSecondary        = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFFFE8D0),
    surface            = CuteSurface,
    surfaceVariant     = Color(0xFFFFF8E7),
    background         = CuteBackground,
    onBackground       = CuteOnBackground,
    onSurface          = CuteOnSurface,
    onSurfaceVariant   = CuteSecondaryText,
    outline            = Color(0xFFE8D5B0),
    outlineVariant     = Color(0xFFF0E6D0),
)

val HoneyDark = darkColorScheme(
    primary            = Color(0xFFFFCA6B),
    onPrimary          = Color(0xFF3D2E00),
    primaryContainer   = Color(0xFF5A4500),
    onPrimaryContainer = Color(0xFFFFE0A0),
    secondary          = Color(0xFFFFBB8A),
    onSecondary        = Color(0xFF4A2800),
    secondaryContainer = Color(0xFF6B3D00),
    surface            = Color(0xFF1F1A10),
    surfaceVariant     = Color(0xFF2E2618),
    background         = Color(0xFF1A1508),
    onBackground       = Color(0xFFF5E6C8),
    onSurface          = Color(0xFFF5E6C8),
    onSurfaceVariant   = Color(0xFFD0BFA0),
    outline            = Color(0xFF8A7A5A),
    outlineVariant     = Color(0xFF4A4030),
)

// ── Matcha 抹茶 ──────────────────────────────────────────────────────────────
val MatchaLight = lightColorScheme(
    primary            = Color(0xFF7BAE6B),
    onPrimary          = Color(0xFFFFFFFF),
    primaryContainer   = Color(0xFFD8F0D0),
    onPrimaryContainer = Color(0xFF1A3D12),
    secondary          = Color(0xFFA8C686),
    onSecondary        = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFE8F5E0),
    surface            = CuteSurface,
    surfaceVariant     = Color(0xFFF2F8ED),
    background         = Color(0xFFF8FCF5),
    onBackground       = CuteOnBackground,
    onSurface          = CuteOnSurface,
    onSurfaceVariant   = CuteSecondaryText,
    outline            = Color(0xFFC0D8B0),
    outlineVariant     = Color(0xFFD8E8D0),
)

val MatchaDark = darkColorScheme(
    primary            = Color(0xFFA8D898),
    onPrimary          = Color(0xFF1A3D12),
    primaryContainer   = Color(0xFF2E5A24),
    onPrimaryContainer = Color(0xFFC8F0B8),
    secondary          = Color(0xFFC0E0A8),
    onSecondary        = Color(0xFF243A18),
    secondaryContainer = Color(0xFF3A5230),
    surface            = Color(0xFF141E10),
    surfaceVariant     = Color(0xFF1E2A18),
    background         = Color(0xFF101A0C),
    onBackground       = Color(0xFFD0E8C0),
    onSurface          = Color(0xFFD0E8C0),
    onSurfaceVariant   = Color(0xFFA8C098),
    outline            = Color(0xFF6A8A5A),
    outlineVariant     = Color(0xFF3A5030),
)

// ── Lavender 薰衣草 ──────────────────────────────────────────────────────────
val LavenderLight = lightColorScheme(
    primary            = Color(0xFF9B7EC8),
    onPrimary          = Color(0xFFFFFFFF),
    primaryContainer   = Color(0xFFEDE0FF),
    onPrimaryContainer = Color(0xFF2D1650),
    secondary          = Color(0xFFB8A9D4),
    onSecondary        = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFF0E8FF),
    surface            = CuteSurface,
    surfaceVariant     = Color(0xFFF8F2FF),
    background         = Color(0xFFFCF8FF),
    onBackground       = CuteOnBackground,
    onSurface          = CuteOnSurface,
    onSurfaceVariant   = CuteSecondaryText,
    outline            = Color(0xFFD0C0E8),
    outlineVariant     = Color(0xFFE0D8F0),
)

val LavenderDark = darkColorScheme(
    primary            = Color(0xFFC8A8F0),
    onPrimary          = Color(0xFF2D1650),
    primaryContainer   = Color(0xFF4A2E70),
    onPrimaryContainer = Color(0xFFE8D0FF),
    secondary          = Color(0xFFD0B8F0),
    onSecondary        = Color(0xFF2A1848),
    secondaryContainer = Color(0xFF3E2A5A),
    surface            = Color(0xFF1A1420),
    surfaceVariant     = Color(0xFF261E30),
    background         = Color(0xFF14101A),
    onBackground       = Color(0xFFE0D0F0),
    onSurface          = Color(0xFFE0D0F0),
    onSurfaceVariant   = Color(0xFFB8A0D0),
    outline            = Color(0xFF7A6090),
    outlineVariant     = Color(0xFF3E3050),
)

// ── SkyBlue 天蓝 ─────────────────────────────────────────────────────────────
val SkyBlueLight = lightColorScheme(
    primary            = Color(0xFF5BA4D9),
    onPrimary          = Color(0xFFFFFFFF),
    primaryContainer   = Color(0xFFD6EEFF),
    onPrimaryContainer = Color(0xFF0A2D4A),
    secondary          = Color(0xFF8ECAE6),
    onSecondary        = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFE0F4FF),
    surface            = CuteSurface,
    surfaceVariant     = Color(0xFFF0F8FF),
    background         = Color(0xFFF5FBFF),
    onBackground       = CuteOnBackground,
    onSurface          = CuteOnSurface,
    onSurfaceVariant   = CuteSecondaryText,
    outline            = Color(0xFFB0D8F0),
    outlineVariant     = Color(0xFFD0E8F8),
)

val SkyBlueDark = darkColorScheme(
    primary            = Color(0xFF8ECAE6),
    onPrimary          = Color(0xFF0A2D4A),
    primaryContainer   = Color(0xFF1A4A6B),
    onPrimaryContainer = Color(0xFFC0E8FF),
    secondary          = Color(0xFFA8D8F0),
    onSecondary        = Color(0xFF102838),
    secondaryContainer = Color(0xFF1E3A4A),
    surface            = Color(0xFF101820),
    surfaceVariant     = Color(0xFF182430),
    background         = Color(0xFF0C141A),
    onBackground       = Color(0xFFC8E0F0),
    onSurface          = Color(0xFFC8E0F0),
    onSurfaceVariant   = Color(0xFF90B8D0),
    outline            = Color(0xFF5080A0),
    outlineVariant     = Color(0xFF284050),
)

// ── Qingwa 青瓦 (blue-grey) ──────────────────────────────────────────────────
val QingwaLight = lightColorScheme(
    primary            = Color(0xFF4A6572),
    onPrimary          = Color(0xFFFFFFFF),
    primaryContainer   = Color(0xFFCDE5F0),
    onPrimaryContainer = Color(0xFF0A1F2A),
    secondary          = Color(0xFF586D78),
    surface            = Color(0xFFF5F8FA),
    surfaceVariant     = Color(0xFFDCE4E9),
    background         = Color(0xFFF5F8FA),
    onBackground       = Color(0xFF1A2A32),
    onSurface          = Color(0xFF1A2A32),
)

val QingwaDark = darkColorScheme(
    primary            = Color(0xFF8FBFD0),
    onPrimary          = Color(0xFF0D2C3A),
    primaryContainer   = Color(0xFF2C4E5E),
    onPrimaryContainer = Color(0xFFBFDEED),
    secondary          = Color(0xFF9BB5C1),
    surface            = Color(0xFF111C22),
    surfaceVariant     = Color(0xFF1E2F38),
    background         = Color(0xFF0D1A22),
    onBackground       = Color(0xFFD0E5EF),
    onSurface          = Color(0xFFD0E5EF),
)

// ── Warm Orange 暖橙 ────────────────────────────────────────────────────────
val WarmOrangeLight = lightColorScheme(
    primary            = Color(0xFFBF5B17),
    onPrimary          = Color(0xFFFFFFFF),
    primaryContainer   = Color(0xFFFFDBC8),
    onPrimaryContainer = Color(0xFF3B1400),
    secondary          = Color(0xFF976249),
    surface            = Color(0xFFFFF8F5),
    surfaceVariant     = Color(0xFFF4DDD3),
    background         = Color(0xFFFFF8F5),
    onBackground       = Color(0xFF3B1400),
    onSurface          = Color(0xFF3B1400),
)

val WarmOrangeDark = darkColorScheme(
    primary            = Color(0xFFFFB58A),
    onPrimary          = Color(0xFF612200),
    primaryContainer   = Color(0xFF8A3900),
    onPrimaryContainer = Color(0xFFFFDBC8),
    secondary          = Color(0xFFEDB89B),
    surface            = Color(0xFF201208),
    surfaceVariant     = Color(0xFF3A1E0F),
    background         = Color(0xFF201208),
    onBackground       = Color(0xFFFFDBC8),
    onSurface          = Color(0xFFFFDBC8),
)

// ── Plain Paper 素纸 ─────────────────────────────────────────────────────────
val PlainPaperLight = lightColorScheme(
    primary            = Color(0xFF5A5347),
    onPrimary          = Color(0xFFFFFFFF),
    primaryContainer   = Color(0xFFE8E2D6),
    onPrimaryContainer = Color(0xFF1A1510),
    secondary          = Color(0xFF76706A),
    surface            = Color(0xFFF9F6F0),
    surfaceVariant     = Color(0xFFEDE9E2),
    background         = Color(0xFFF9F6F0),
    onBackground       = Color(0xFF1A1510),
    onSurface          = Color(0xFF1A1510),
)

val PlainPaperDark = darkColorScheme(
    primary            = Color(0xFFCEC8BC),
    onPrimary          = Color(0xFF2A2520),
    primaryContainer   = Color(0xFF413C37),
    onPrimaryContainer = Color(0xFFE8E2D6),
    secondary          = Color(0xFFBBB5AF),
    surface            = Color(0xFF1A1710),
    surfaceVariant     = Color(0xFF282420),
    background         = Color(0xFF1A1710),
    onBackground       = Color(0xFFE8E2D6),
    onSurface          = Color(0xFFE8E2D6),
)

// ── Mist 微雾 ───────────────────────────────────────────────────────────────
val MistLight = lightColorScheme(
    primary            = Color(0xFF636B74),
    onPrimary          = Color(0xFFFFFFFF),
    primaryContainer   = Color(0xFFDDE4EA),
    onPrimaryContainer = Color(0xFF1B2428),
    secondary          = Color(0xFF70797E),
    surface            = Color(0xFFF4F6F8),
    surfaceVariant     = Color(0xFFDEE4E8),
    background         = Color(0xFFF4F6F8),
    onBackground       = Color(0xFF1B2428),
    onSurface          = Color(0xFF1B2428),
)

val MistDark = darkColorScheme(
    primary            = Color(0xFFABB5BD),
    onPrimary          = Color(0xFF272F35),
    primaryContainer   = Color(0xFF3A4248),
    onPrimaryContainer = Color(0xFFDDE4EA),
    secondary          = Color(0xFFA0AAAF),
    surface            = Color(0xFF141A1E),
    surfaceVariant     = Color(0xFF222A2E),
    background         = Color(0xFF141A1E),
    onBackground       = Color(0xFFDDE4EA),
    onSurface          = Color(0xFFDDE4EA),
)
