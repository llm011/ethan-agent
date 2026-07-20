"use client";

import { useState, useCallback, useEffect } from "react";

export function useTheme() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    if (typeof window !== "undefined") {
      return (localStorage.getItem("ethan-theme") as "dark" | "light") || "dark";
    }
    return "dark";
  });

  // mount 时把 localStorage 里的 theme 同步到 <html> classList，
  // 避免 main.tsx 未同步时初次加载走 :root 默认值，toggle 一次后又走 .light/.dark
  // 造成主题切换前后颜色漂移。
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.classList.toggle("light", theme === "light");
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      localStorage.setItem("ethan-theme", next);
      // 同步更新 DOM，不依赖 useEffect 异步生效（避免 toggle 后到 paint 之间有闪）
      document.documentElement.classList.toggle("dark", next === "dark");
      document.documentElement.classList.toggle("light", next === "light");
      return next;
    });
  }, []);

  return { theme, toggle };
}
