package com.ethan.agent.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

private val LightColors = lightColorScheme(
    primary = androidx.compose.ui.graphics.Color(0xFF6750A4),
    onPrimary = androidx.compose.ui.graphics.Color(0xFFFFFFFF),
    primaryContainer = androidx.compose.ui.graphics.Color(0xFFEADDFF),
    secondary = androidx.compose.ui.graphics.Color(0xFF625B71),
    tertiary = androidx.compose.ui.graphics.Color(0xFF7D5260),
    surface = androidx.compose.ui.graphics.Color(0xFFFFFBFE),
    surfaceVariant = androidx.compose.ui.graphics.Color(0xFFE7E0EC),
)

private val DarkColors = darkColorScheme(
    primary = androidx.compose.ui.graphics.Color(0xFFD0BCFF),
    onPrimary = androidx.compose.ui.graphics.Color(0xFF381E72),
    primaryContainer = androidx.compose.ui.graphics.Color(0xFF4F378B),
    secondary = androidx.compose.ui.graphics.Color(0xFFCCC2DC),
    tertiary = androidx.compose.ui.graphics.Color(0xFFEFB8C8),
    surface = androidx.compose.ui.graphics.Color(0xFF1C1B1F),
    surfaceVariant = androidx.compose.ui.graphics.Color(0xFF49454F),
)

@Composable
fun EthanTheme(
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit,
) {
    val systemDark = isSystemInDarkTheme()
    val themeId = ThemeState.themeId

    val colorScheme = when (themeId) {
        "dark" -> DarkColors
        "qingwa" -> if (systemDark) QingwaDark else QingwaLight
        "warm_orange" -> if (systemDark) WarmOrangeDark else WarmOrangeLight
        "plain_paper" -> if (systemDark) PlainPaperDark else PlainPaperLight
        "mist" -> if (systemDark) MistDark else MistLight
        "light" -> LightColors
        else -> {
            // "system" — respect dynamic color on Android 12+
            if (dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val context = LocalContext.current
                if (systemDark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
            } else {
                if (systemDark) DarkColors else LightColors
            }
        }
    }

    MaterialTheme(
        colorScheme = colorScheme,
        content = content,
    )
}
