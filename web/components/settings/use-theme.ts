"use client";

import { useState, useCallback } from "react";

export function useTheme() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    if (typeof window !== "undefined") {
      return (localStorage.getItem("ethan-theme") as "dark" | "light") || "dark";
    }
    return "dark";
  });

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      localStorage.setItem("ethan-theme", next);
      document.documentElement.classList.toggle("dark", next === "dark");
      document.documentElement.classList.toggle("light", next === "light");
      return next;
    });
  }, []);

  return { theme, toggle };
}
