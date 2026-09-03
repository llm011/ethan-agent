import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter/material.dart';

import '../models/app_models.dart';

class ConfigStore {
  static const _serverKey = 'server_url';
  static const _tokenKey = 'access_token';
  static const _themeKey = 'theme_mode';

  Future<ApiConfig?> read() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString(_tokenKey);
    if (token == null || token.isEmpty) return null;
    return ApiConfig(
      baseUrl: prefs.getString(_serverKey) ?? 'http://127.0.0.1:8900',
      token: token,
    );
  }

  Future<void> save(ApiConfig config) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_serverKey, config.baseUrl);
    await prefs.setString(_tokenKey, config.token);
  }

  Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_serverKey);
    await prefs.remove(_tokenKey);
  }

  Future<ThemeMode> readTheme() async {
    final value = (await SharedPreferences.getInstance()).getString(_themeKey);
    return switch (value) {
      'light' => ThemeMode.light,
      'dark' => ThemeMode.dark,
      _ => ThemeMode.system,
    };
  }

  Future<void> saveTheme(ThemeMode mode) async {
    await (await SharedPreferences.getInstance())
        .setString(_themeKey, mode.name);
  }
}
