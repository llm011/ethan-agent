/** 基础设施：可配置的 API URL、认证、headers。 */

const STORAGE_KEY_API_URL = "ethan_api_url";
const STORAGE_KEY_TOKEN = "ethan_token";
const DEFAULT_API_URL = "http://127.0.0.1:8900/api";

export function getApiUrl(): string {
  if (typeof window === "undefined") return DEFAULT_API_URL;
  return localStorage.getItem(STORAGE_KEY_API_URL) || DEFAULT_API_URL;
}

export function setApiUrl(url: string) {
  const trimmed = url.replace(/\/+$/, "");
  localStorage.setItem(STORAGE_KEY_API_URL, trimmed);
}

let authToken = "";

export function setAuthToken(token: string) {
  authToken = token;
  localStorage.setItem(STORAGE_KEY_TOKEN, token);
}

export function getAuthToken(): string {
  if (authToken) return authToken;
  authToken = localStorage.getItem(STORAGE_KEY_TOKEN) || "";
  return authToken;
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

export async function fetchHealth(): Promise<{ version: string; status: string } | null> {
  try {
    const res = await fetch(`${getApiUrl()}/health`);
    return res.json();
  } catch {
    return null;
  }
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

export async function respondConsent(requestId: string, allowed: boolean): Promise<{ ok: boolean }> {
  const res = await fetch(`${getApiUrl()}/consent/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ allowed }),
  });
  return res.json();
}
