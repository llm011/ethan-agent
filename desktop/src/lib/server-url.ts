/**
 * 桌面端服务地址。
 *
 * 服务真正监听在哪由 Ethan 的 `~/.ethan/config.yaml` 决定，不能在前端再复制一份
 * 端口常量。Rust 侧在启动时读取配置；这里缓存它，保证所有 REST / WebSocket 调用
 * 在 React mount 前拿到同一个地址。用户在 Settings 手动填的地址仍优先。
 */
import { invoke } from "@tauri-apps/api/core";

const STORAGE_KEY_API_URL = "ethan_api_url";

let configuredServerUrl = "";

function normalizeServerUrl(raw: string | null | undefined): string {
  if (!raw) return "";
  let url = raw.replace(/\/+$/, "");
  // 兼容：用户存了带 /api 的旧值，剥离后存储 base。
  if (url.endsWith("/api")) url = url.slice(0, -4);
  return url;
}

/**
 * 在 mount 前读取 Ethan 服务配置。invoke 失败时不猜端口；调用方会得到空地址，
 * Settings 仍可让用户显式填写远程服务地址。
 */
export async function initServerUrl(): Promise<void> {
  try {
    configuredServerUrl = normalizeServerUrl(await invoke<string>("get_ethan_server_url"));
  } catch {
    configuredServerUrl = "";
  }
}

/** 用户在 Settings 填过的地址优先于本机 Ethan 配置。 */
export function getServerUrl(): string {
  if (typeof window !== "undefined") {
    const saved = normalizeServerUrl(localStorage.getItem(STORAGE_KEY_API_URL));
    if (saved) return saved;
  }
  return configuredServerUrl;
}

/** 获取完整 API URL（含 /api 后缀），供 fetch 调用使用。 */
export function getApiUrl(): string {
  return `${getServerUrl()}/api`;
}

/** 保存 Server 地址（用户只需填写 base，如 http://127.0.0.1:8989）。 */
export function setServerUrl(url: string): void {
  const normalized = normalizeServerUrl(url);
  configuredServerUrl = normalized;
  localStorage.setItem(STORAGE_KEY_API_URL, normalized);
}
