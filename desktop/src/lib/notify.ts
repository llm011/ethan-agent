/**
 * 桌面端系统通知助手。
 *
 * - notifyDesktop({ title, body })：发送 OS 原生通知，错误静默吞掉。
 *   仅在窗口未聚焦时由调用方判断是否触发（避免前台聊天时弹通知打扰）。
 * - 非 Tauri 环境（web dev）下自动降级为 no-op。
 */

type NotificationModule = typeof import("@tauri-apps/plugin-notification");

let _mod: NotificationModule | null | undefined;

async function loadNotification(): Promise<NotificationModule | null> {
  if (_mod !== undefined) return _mod;
  if (typeof window === "undefined" || !(window as any).__TAURI_INTERNALS__) {
    _mod = null;
    return null;
  }
  try {
    _mod = await import("@tauri-apps/plugin-notification");
    return _mod;
  } catch {
    _mod = null;
    return null;
  }
}

export interface NotifyOptions {
  title: string;
  body: string;
}

/** 发送一条系统通知；任何错误均静默吞掉，绝不打断对话流。 */
export async function notifyDesktop({ title, body }: NotifyOptions): Promise<void> {
  const mod = await loadNotification();
  if (!mod) return;
  try {
    let permission = await mod.isPermissionGranted();
    if (!permission) {
      const req = await mod.requestPermission();
      permission = req === "granted";
    }
    if (!permission) return;
    await mod.sendNotification({ title, body });
  } catch {
    // 通知失败不影响主流程
  }
}
