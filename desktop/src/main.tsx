import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";
import { isExternalUrl, openUrl } from "@/lib/external-link";
import { normalizeThemeId, applyThemeClass } from "@/components/chat/themes";

// 启动时同步主题 class 到 <html>，避免 React mount 前的首帧走 :root 默认值
// 造成主题切换前后的视觉漂移。必须在 createRoot 之前执行，确保首屏 paint 时
// <html> 已带上正确 class。
(() => {
  try {
    applyThemeClass(normalizeThemeId(localStorage.getItem("ethan-theme")));
  } catch {
    // localStorage 不可用时静默回退到 :root 默认值（青瓦）
  }
})();

// 全局外链拦截器：桌面端 webview 内点击外链会被顶走（回不去），
// 任何 <a href="http...">（含 markdown 渲染、docs、md-editor 等漏网链接）
// 都在 capture 阶段拦截，改走系统默认浏览器打开。
// 锚点（#xxx）、相对路径保持默认站内行为。
document.addEventListener("click", (e) => {
  const target = e.target as HTMLElement | null;
  const a = target?.closest("a");
  if (!a) return;
  const href = a.getAttribute("href") || "";
  if (!isExternalUrl(href)) return;
  e.preventDefault();
  e.stopPropagation();
  openUrl(href);
}, true);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
