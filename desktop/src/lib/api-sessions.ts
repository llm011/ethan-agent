/** Session 相关类型和 API。 */

import { getApiUrl, getAuthToken, headers  } from "./api-base";

export interface SessionInfo {
  id: string;
  title: string;
  model: string;
  created_at: number;
  updated_at: number;
  snippet?: string;
  source?: string;
  mode?: string;
}

export interface SessionDetail {
  id: string;
  title: string;
  model: string;
  source?: string;
  mode?: string;
  active_run?: boolean;
  messages: {
    role: string;
    content: string;
    created_at?: number;
    quote?: { role: "user" | "assistant"; content: string } | null;
    usage?: { input: number; output: number; cache: number };
    a2ui?: unknown[];
    mcp_apps?: Array<{ uri: string; data?: Record<string, unknown>; html?: string; csp?: Record<string, string[]> }>;
    images?: Array<{ data?: string; media_type?: string; dataUrl?: string }>;
    matched_skills?: Array<{ name: string; is_default?: boolean }>;
    ttfb_ms?: number;
    total_ms?: number;
    tool_steps?: Array<{
      tool: string;
      args: string;
      intent?: string;
      state: string;
      duration_ms?: number | null;
      result_preview?: string;
      result_detail?: string;
      thought?: string;
      entity_type?: string;
      entity_id?: string;
      sub_steps?: Array<{
        tool: string;
        args: string;
        state: string;
        duration_ms?: number | null;
        result_preview?: string;
      }>;
    }>;
  }[];
}

export async function fetchSessions(limit = 50, offset = 0, q?: string, source?: string, mode?: string, hideHeartbeat?: boolean, hideScheduled?: boolean, titlePrefixes?: string): Promise<SessionInfo[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (q) params.set("q", q);
  if (source) params.set("source", source);
  if (mode !== undefined) params.set("mode", mode);
  if (hideHeartbeat) params.set("hide_heartbeat", "true");
  if (hideScheduled) params.set("hide_scheduled", "true");
  if (titlePrefixes) params.set("title_prefixes", titlePrefixes);
  const res = await fetch(`${getApiUrl()}/sessions?${params}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch sessions");
  const data = await res.json();
  return data.sessions;
}

export async function renameSession(id: string, title: string): Promise<void> {
  await fetch(`${getApiUrl()}/sessions/${id}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify({ title }),
  });
}

export async function regenSessionTitle(id: string): Promise<string | null> {
  const res = await fetch(`${getApiUrl()}/sessions/${id}/regen-title`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data.ok ? data.title : null;
}

export async function updateSessionMode(id: string, mode: string): Promise<void> {
  await fetch(`${getApiUrl()}/sessions/${id}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify({ mode }),
  });
}

export async function createSession(model?: string, mode?: string, source?: string): Promise<{ id: string; title: string; model: string; mode?: string; source?: string }> {
  const params = new URLSearchParams();
  if (model) params.append("model", model);
  if (mode) params.append("mode", mode);
  if (source) params.append("source", source);
  const qs = params.toString();
  const res = await fetch(`${getApiUrl()}/sessions${qs ? `?${qs}` : ""}`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to create session");
  return res.json();
}

export async function fetchSession(id: string): Promise<SessionDetail> {
  const res = await fetch(`${getApiUrl()}/sessions/${id}`, { headers: headers() });
  if (!res.ok) throw new Error("Session not found");
  return res.json();
}

export async function deleteSession(id: string): Promise<void> {
  await fetch(`${getApiUrl()}/sessions/${id}`, { method: "DELETE", headers: headers() });
}

export async function compactSession(id: string): Promise<{ ok: boolean; summary: string }> {
  const res = await fetch(`${getApiUrl()}/sessions/${id}/compact`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Compact failed");
  return res.json();
}

// 生成当前会话的总结（只读，不修改历史）
export async function summarySession(id: string): Promise<{ ok: boolean; summary: string }> {
  const res = await fetch(`${getApiUrl()}/sessions/${id}/summary`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Summary failed");
  return res.json();
}

export async function cleanupTrivialSessions(): Promise<{ deleted: number; deleted_ids: string[] }> {
  const res = await fetch(`${getApiUrl()}/sessions/cleanup-trivial`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Cleanup failed");
  return res.json();
}

export async function uploadFile(file: File): Promise<{ path: string; filename: string }> {
  const form = new FormData();
  form.append("file", file);
  const h: HeadersInit = {};
  const token = getAuthToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${getApiUrl()}/upload`, { method: "POST", headers: h, body: form });
  if (!res.ok) throw new Error("Upload failed");
  return res.json();
}
