import { open } from "@tauri-apps/plugin-shell";

// 是否为应在外部浏览器打开的链接（http/https/mailto/tel 等）。
// 锚点（#xxx）、相对路径、blob/data URL 不走外部浏览器。
export function isExternalUrl(href: string): boolean {
  if (!href) return false;
  if (href.startsWith("#")) return false;
  // blob:/data: 不能也不需要走系统浏览器
  if (/^(blob|data|javascript):/i.test(href)) return false;
  // 绝对 URL（含协议）→ 外部
  if (/^[a-z][a-z0-9+.-]*:/i.test(href)) return true;
  // 其余（相对路径、/xxx、./xxx）→ 站内导航，不外开
  return false;
}

// 在系统默认浏览器中打开外链；失败时回退到 window.open。
// 桌面端 webview 内部直接点击外链会被顶走（无法返回），所以所有外链
// 都必须经此函数走系统浏览器。
export async function openUrl(href: string): Promise<void> {
  try {
    await open(href);
  } catch {
    // plugin 不可用（例如浏览器环境调试）时退回 window.open
    window.open(href, "_blank", "noopener,noreferrer");
  }
}
