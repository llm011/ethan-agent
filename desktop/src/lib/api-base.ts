/** 基础设施：API URL、认证、headers、通用接口（Models/Modes/Version）。 */

import { bustCache } from "./local-cache";

const STORAGE_KEY_API_URL = "ethan_api_url";
const DEFAULT_SERVER_URL = "http://127.0.0.1:8900";

function normalizeServerUrl(raw: string | null): string {
  if (!raw) return DEFAULT_SERVER_URL;
  let url = raw.replace(/\/+$/, "");
  // 兼容：用户存了带 /api 的旧值，剥离后存储 base
  if (url.endsWith("/api")) url = url.slice(0, -4);
  return url;
}

/** 获取完整 API URL（含 /api 后缀），供 fetch 调用使用。 */
export function getApiUrl(): string {
  if (typeof window === "undefined") return `${DEFAULT_SERVER_URL}/api`;
  return `${normalizeServerUrl(localStorage.getItem(STORAGE_KEY_API_URL))}/api`;
}

/** 获取 Server 基础地址（不含 /api），用于 WebSocket 等非 REST 连接。 */
export function getServerUrl(): string {
  if (typeof window === "undefined") return DEFAULT_SERVER_URL;
  return normalizeServerUrl(localStorage.getItem(STORAGE_KEY_API_URL));
}

/** 保存 Server 地址（用户只需填写 base，如 http://127.0.0.1:8900）。 */
export function setApiUrl(url: string): void {
  localStorage.setItem(STORAGE_KEY_API_URL, normalizeServerUrl(url));
}

/**
 * @deprecated 桌面端使用 getApiUrl() 获取实时 URL。
 * 此处保留只是为了兼容 web 端迁移过来的代码中 `import { API_URL } from "./api-base"`。
 * 注意：所有 fetch 调用必须使用 `${getApiUrl()}` 而非 `${API_URL}`，否则用户在
 * Settings 中修改的 API URL 不会生效（auth/models/modes 等接口会走默认端口 8900）。
 */
export const API_URL = `${DEFAULT_SERVER_URL}/api`;

let authToken = "";

export function setAuthToken(token: string) {
  authToken = token;
  if (typeof window !== "undefined") {
    localStorage.setItem("ethan_token", token);
    document.cookie = `ethan_token=${encodeURIComponent(token)}; max-age=2592000; path=/`; // 30 days
  }
}

export function getAuthToken(): string {
  if (authToken) return authToken;
  if (typeof window !== "undefined") {
    authToken = localStorage.getItem("ethan_token") || "";
    if (!authToken) {
      const match = document.cookie.match(/(?:^|; )ethan_token=([^;]+)/);
      if (match) authToken = decodeURIComponent(match[1]);
    }
  }
  return authToken;
}

export function assetUrl(relativePath: string): string {
  const url = `${getApiUrl()}/${relativePath}`;
  const token = getAuthToken();
  if (token) return `${url}?token=${encodeURIComponent(token)}`;
  return url;
}

export function headers(): HeadersInit {
  const h: HeadersInit = { "Content-Type": "application/json" };
  const token = getAuthToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

export async function verifyAuth(token: string): Promise<boolean> {
  const res = await fetch(`${getApiUrl()}/auth`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  return res.ok;
}

export interface ModelEntry {
  id: string;
  provider: string;
  description: string;
  alias: string[];
  vision: boolean;
}

export async function fetchModels(): Promise<ModelEntry[]> {
  const res = await fetch(`${getApiUrl()}/models`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch models");
  const data = await res.json();
  return data.models;
}

export interface ModeEntry {
  key: string;
  label: string;
  icon: string;
  accent: string;
  blurb: string;
}

export async function fetchModes(): Promise<ModeEntry[]> {
  const res = await fetch(`${getApiUrl()}/modes`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch modes");
  const data = await res.json();
  return data.modes;
}

export async function addModel(m: ModelEntry): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${getApiUrl()}/models`, {
    method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(m),
  });
  const data = await res.json();
  // 写操作成功后失效缓存，所有 useCachedResource("models") 自动 refetch
  if (data.ok) bustCache("models");
  return data;
}

export async function deleteModel(provider: string, modelId: string): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${getApiUrl()}/models/${encodeURIComponent(provider)}/${encodeURIComponent(modelId)}`, {
    method: "DELETE", headers: headers(),
  });
  const data = await res.json();
  if (data.ok) bustCache("models");
  return data;
}

export async function addModelsBatch(models: ModelEntry[]): Promise<{ ok: boolean; added: number; skipped: { id: string; provider: string; reason: string }[]; error?: string }> {
  const res = await fetch(`${getApiUrl()}/models/batch`, {
    method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ models }),
  });
  const data = await res.json();
  if (data.ok) bustCache("models");
  return data;
}

export async function deleteModelsBatch(items: { provider: string; id: string }[]): Promise<{ ok: boolean; deleted: number; error?: string }> {
  const res = await fetch(`${getApiUrl()}/models/delete-batch`, {
    method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  const data = await res.json();
  if (data.ok) bustCache("models");
  return data;
}

export async function discoverModels(provider: string): Promise<{ ok: boolean; models?: (ModelEntry & { exists?: boolean })[]; error?: string; url?: string }> {
  const res = await fetch(`${getApiUrl()}/models/discover`, {
    method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ provider }),
  });
  return res.json();
}

export async function respondConsent(requestId: string, allowed: boolean, message?: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiUrl()}/consent/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ allowed, message: message || "" }),
  });
  return res.json();
}

/** 响应 ask_user 选择卡片：POST 用户选中的 value。 */
export async function respondAskUser(requestId: string, value: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiUrl()}/ask-user/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  return res.json();
}

/** 响应 wait_for_user 等待卡片：POST 用户的确认/取消/文本输入。 */
export async function respondWaitForUser(requestId: string, value: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiUrl()}/wait-for-user/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed (${res.status})`);
  }
  return res.json();
}

/** 响应浏览器清理确认卡片：action="close" 关闭 tab group，action="keep" 保留。 */
export async function respondBrowserCleanup(requestId: string, action: "close" | "keep"): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiUrl()}/browser/cleanup/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  return res.json();
}

/** Tool UI resources: 按 ui:// URI 获取工具 UI 模板 HTML（前端缓存，模板只拉一次）。 */
export async function fetchUiResource(uri: string): Promise<{ text: string; _meta?: unknown }> {
  const res = await fetch(`${getApiUrl()}/ui-resources/read?uri=${encodeURIComponent(uri)}`, {
    headers: headers(),
  });
  if (!res.ok) throw new Error(`Failed to fetch UI resource: ${uri}`);
  return res.json();
}

/** 获取后端版本号（与 PyPI 版本一致，来自 ethan.__version__） */
export async function fetchVersion(): Promise<string | null> {
  try {
    const res = await fetch(`${getApiUrl()}/health`);
    const data = await res.json();
    return data.version ?? null;
  } catch {
    return null;
  }
}
