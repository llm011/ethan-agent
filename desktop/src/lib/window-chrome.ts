/** 桌面壳窗口装饰相关的布局常量。
 *
 * 主窗口在 `src-tauri/tauri.conf.json` 里用 `titleBarStyle: "Overlay"`：macOS 的
 * 交通灯（关闭/最小化/全屏）是悬浮在 webview 左上角的原生控件，网页内容会铺到
 * 它们下面。普通页面靠 Sidebar 顶部的 `pt-[28px]` 让开，但像阅读模式这种
 * `fixed inset-0` 的全窗口覆盖层，顶部条从最左边起排，关闭按钮就会压在交通灯上。
 */

/** 是否运行在 Tauri 桌面壳里（web 端为 false）。 */
export function isTauriRuntime(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as { isTauri?: boolean; __TAURI_INTERNALS__?: unknown };
  return w.isTauri === true || "__TAURI_INTERNALS__" in w;
}

/** 是否是 macOS 桌面壳——只有这种组合下才有覆盖在内容上的交通灯。 */
export function isMacTauriRuntime(): boolean {
  if (!isTauriRuntime() || typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  // 同时看 platform 与 UA：WKWebView 两者都带 Mac 标识，任一命中即可
  return /Mac/i.test(navigator.platform || "") || /Macintosh|Mac OS X/i.test(ua);
}

/** macOS 交通灯占用区宽度（px）：20px 左边距 + 3 个 12px 圆点 + 2 个 8px 间距
 *  = 72px，再留 12px 呼吸位。非 macOS 桌面壳（含 web）返回 0。 */
export function overlayTitlebarLeftInset(): number {
  return isMacTauriRuntime() ? 84 : 0;
}
