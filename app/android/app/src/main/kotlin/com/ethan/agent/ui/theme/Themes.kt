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
