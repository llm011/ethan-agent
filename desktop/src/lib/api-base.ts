/** 基础设施：API URL、认证、headers、通用接口（Models/Modes/Version）。 */

const STORAGE_KEY_API_URL = "ethan_api_url";
const DEFAULT_API_URL = "http://127.0.0.1:8989/api";

/** 桌面端：API URL 存在 localStorage，可在 Settings 中修改。 */
export function getApiUrl(): string {
  if (typeof window === "undefined") return DEFAULT_API_URL;
  return localStorage.getItem(STORAGE_KEY_API_URL) || DEFAULT_API_URL;
}

export function setApiUrl(url: string): void {
  const trimmed = url.replace(/\/+$/, "");
  localStorage.setItem(STORAGE_KEY_API_URL, trimmed);
}

/**
 * @deprecated 桌面端使用 getApiUrl() 获取实时 URL。
 * 此处保留只是为了兼容 web 端迁移过来的代码中 `import { API_URL } from "./api-base"`。
 * 实际所有 `${API_URL}` 模板字符串都已在迁移时被替换为 `${getApiUrl()}`。
 */
export const API_URL = DEFAULT_API_URL;

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

export function headers(): HeadersInit {
  const h: HeadersInit = { "Content-Type": "application/json" };
  const token = getAuthToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

export async function verifyAuth(token: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/auth`, {
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
  const res = await fetch(`${API_URL}/models`, { headers: headers() });
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
  const res = await fetch(`${API_URL}/modes`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch modes");
  const data = await res.json();
  return data.modes;
}

export async function addModel(m: ModelEntry): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${API_URL}/models`, {
    method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(m),
  });
  return res.json();
}

export async function deleteModel(provider: string, modelId: string): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${API_URL}/models/${encodeURIComponent(provider)}/${encodeURIComponent(modelId)}`, {
    method: "DELETE", headers: headers(),
  });
  return res.json();
}

export async function discoverModels(provider: string): Promise<{ ok: boolean; models?: (ModelEntry & { exists?: boolean })[]; error?: string; url?: string }> {
  const res = await fetch(`${API_URL}/models/discover`, {
    method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ provider }),
  });
  return res.json();
}

export async function respondConsent(requestId: string, allowed: boolean): Promise<{ ok: boolean }> {
  const res = await fetch(`${API_URL}/consent/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ allowed }),
  });
  return res.json();
}

/** Tool UI resources: 按 ui:// URI 获取工具 UI 模板 HTML（前端缓存，模板只拉一次）。 */
export async function fetchUiResource(uri: string): Promise<{ text: string; _meta?: unknown }> {
  const res = await fetch(`${API_URL}/ui-resources/read?uri=${encodeURIComponent(uri)}`, {
    headers: headers(),
  });
  if (!res.ok) throw new Error(`Failed to fetch UI resource: ${uri}`);
  return res.json();
}

/** 获取后端版本号（与 PyPI 版本一致，来自 ethan.__version__） */
export async function fetchVersion(): Promise<string | null> {
  try {
    const res = await fetch(`${API_URL}/health`);
    const data = await res.json();
    return data.version ?? null;
  } catch {
    return null;
  }
}
