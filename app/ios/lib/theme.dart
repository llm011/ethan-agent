import 'package:flutter/material.dart';

class EthanTheme {
  // Warm yellow is kept as a legacy brand constant for content that opts in,
  // but the application chrome uses a neutral iOS-like light palette.
  static const honey = Color(0xfff5a623);
  static const ink = Color(0xff1d2939);

  static ThemeData light() => _theme(Brightness.light);
  static ThemeData dark() => _theme(Brightness.dark);

  static ThemeData _theme(Brightness brightness) {
    final isDark = brightness == Brightness.dark;
    final scheme = ColorScheme.fromSeed(
      seedColor: isDark ? honey : const Color(0xff667085),
      brightness: brightness,
      primary: isDark ? const Color(0xffffc85c) : const Color(0xff475467),
      surface: isDark ? const Color(0xff201d18) : const Color(0xfff8f9fb),
    );
    final lightScheme = scheme.copyWith(
      surface: const Color(0xfff8f9fb),
      surfaceContainerLowest: Colors.white,
      surfaceContainerLow: const Color(0xfffbfcfd),
      surfaceContainer: Colors.white,
      surfaceContainerHigh: const Color(0xfff2f4f7),
      surfaceContainerHighest: const Color(0xffeaecf0),
      outline: const Color(0xffd0d5dd),
      outlineVariant: const Color(0xffeaecf0),
      primaryContainer: const Color(0xffeef2f6),
      onPrimaryContainer: const Color(0xff344054),
      secondaryContainer: const Color(0xfff2f4f7),
      onSecondaryContainer: const Color(0xff344054),
    );
    final activeScheme = isDark ? scheme : lightScheme;
    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: activeScheme,
      scaffoldBackgroundColor: activeScheme.surface,
      appBarTheme: AppBarTheme(
        backgroundColor: Colors.transparent,
        foregroundColor: isDark ? activeScheme.onSurface : ink,
        elevation: 0,
        titleTextStyle: const TextStyle(
          fontSize: 20,
          fontWeight: FontWeight.w800,
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(0, 48),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(0, 44),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        ),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(minimumSize: const Size(44, 44)),
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: isDark ? const Color(0xff2a2620) : Colors.white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: isDark ? const Color(0xff2d2923) : Colors.white,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: activeScheme.outlineVariant),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: activeScheme.outlineVariant),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: activeScheme.primary, width: 1.5),
        ),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 13,
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        height: 76,
        backgroundColor: isDark ? null : Colors.white,
        indicatorColor: activeScheme.primaryContainer,
        labelTextStyle: WidgetStateProperty.all(
          const TextStyle(fontSize: 11, fontWeight: FontWeight.w600),
        ),
      ),
    );
  }
}
