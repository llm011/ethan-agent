/** 基础设施：API URL、认证、headers、通用接口（Models/Modes/Version）。 */

export const API_URL = typeof window !== "undefined"
  ? (process.env.NEXT_PUBLIC_API_URL
    ? process.env.NEXT_PUBLIC_API_URL
    : window.location.port === "3000"
      ? `${window.location.protocol}//127.0.0.1:8900/api`
      : `${window.location.origin}/api`)
  : (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8900/api");

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

/** 构建 assets URL（图片等静态资源），自动处理跨域鉴权。
 * 生产模式同源，cookie 自动携带；开发模式跨端口，追加 ?token= query 参数。
 */
export function assetUrl(relativePath: string): string {
  const url = `${API_URL}/${relativePath}`;
  if (typeof window !== "undefined" && window.location.port === "3000") {
    const token = getAuthToken();
    if (token) return `${url}?token=${encodeURIComponent(token)}`;
  }
  return url;
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

export async function respondConsent(requestId: string, allowed: boolean, message?: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${API_URL}/consent/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ allowed, message: message || "" }),
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

/** 获取后端 health 信息（版本号 + agent_name，来自 /health 端点）。
 * 左上角标题用 agent_name 显示用户设置的 agent 名（见 config.defaults.agent_name）。
 */
export interface ServerHealthInfo {
  version: string | null;
  agent_name: string | null;
}
export async function fetchHealth(): Promise<ServerHealthInfo> {
  try {
    const res = await fetch(`${API_URL}/health`);
    const data = await res.json();
    return { version: data.version ?? null, agent_name: data.agent_name ?? null };
  } catch {
    return { version: null, agent_name: null };
  }
}
