// 主题注册表 —— 桌面端与 Web 端共享同一份定义（改动需两端同步）。
// 每个主题对应 styles.css / globals.css 里的一段 CSS 变量（通过 className 挂到 <html>）。
// swatch 是给右上角调色盘图标做「预览小圆点」用的代表色，纯展示、不参与实际配色。

export type ThemeId = "qingwa" | "warm" | "paper" | "mist" | "dark";

export interface ThemeDef {
  id: ThemeId;
  label: string;
  /** 挂到 <html> 上的 class；dark 主题额外带上 `dark` 让 tailwind dark: 变体生效 */
  className: string;
  /** 是否深色（决定是否附加 `dark` class） */
  isDark: boolean;
  /** 调色盘预览用的三个代表色（背景 / 主色 / 辅色） */
  swatch: [string, string, string];
}

export const THEMES: ThemeDef[] = [
  {
    id: "qingwa",
    label: "青瓦",
    className: "theme-qingwa",
    isDark: false,
    swatch: ["#f5f7f2", "#6f9b86", "#8fb4c9"],
  },
  {
    id: "warm",
    label: "暖橙",
    className: "theme-warm",
    isDark: false,
    swatch: ["#fdfbf8", "#c98a52", "#e8d9c8"],
  },
  {
    id: "paper",
    label: "素纸",
    className: "theme-paper",
    isDark: false,
    swatch: ["#fbfaf7", "#8a7f6d", "#e7e2d8"],
  },
  {
    id: "mist",
    label: "微雾",
    className: "theme-mist",
    isDark: false,
    swatch: ["#fbfcfd", "#6b7787", "#e4e8ec"],
  },
  {
    id: "dark",
    label: "深色",
    className: "dark",
    isDark: true,
    swatch: ["#1f1f1f", "#e8e8e8", "#3a3a3a"],
  },
];

export const DEFAULT_THEME: ThemeId = "qingwa";

const ALL_CLASSES = THEMES.map((t) => t.className);

/** 兼容旧值：早期只有 dark/light 两种，light 即原暖橙主题 */
export function normalizeThemeId(raw: string | null | undefined): ThemeId {
  if (!raw) return DEFAULT_THEME;
  if (raw === "light") return "warm";
  if (THEMES.some((t) => t.id === raw)) return raw as ThemeId;
  return DEFAULT_THEME;
}

/** 把目标主题的 class 挂到 <html>，并清掉其它主题遗留的 class */
export function applyThemeClass(id: ThemeId) {
  if (typeof document === "undefined") return;
  const theme = THEMES.find((t) => t.id === id) ?? THEMES[0];
  const el = document.documentElement;
  el.classList.remove(...ALL_CLASSES, "dark", "light");
  el.classList.add(theme.className);
  // dark: 变体依赖 .dark class，深色主题额外补上（className 已是 dark 时不重复）
  if (theme.isDark) el.classList.add("dark");
}
