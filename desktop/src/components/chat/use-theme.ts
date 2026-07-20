"use client";

import { useState, useCallback, useEffect } from "react";
import { type ThemeId, normalizeThemeId, applyThemeClass } from "./themes";

const STORAGE_KEY = "ethan-theme";

export function useTheme() {
  const [theme, setThemeState] = useState<ThemeId>(() => {
    if (typeof window !== "undefined") {
      return normalizeThemeId(localStorage.getItem(STORAGE_KEY));
    }
    return normalizeThemeId(null);
  });

  // mount 时把当前主题 class 同步到 <html>，避免 main.tsx 未同步时初次加载走 :root 默认值，
  // 切换一次后又走 .theme-* 造成主题漂移。
  useEffect(() => {
    applyThemeClass(theme);
  }, [theme]);

  const setTheme = useCallback((next: ThemeId) => {
    localStorage.setItem(STORAGE_KEY, next);
    // 同步更新 DOM，不依赖 useEffect 异步生效（避免切换后到 paint 之间有闪）
    applyThemeClass(next);
    setThemeState(next);
  }, []);

  return { theme, setTheme };
}
