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
  pinned_at?: number;
  last_read_at?: number;
}

export interface SessionDetail {
  id: string;
  title: string;
  model: string;
  source?: string;
  mode?: string;
  pinned_at?: number;
  active_run?: boolean;
  pending_injected?: Array<{ id: string; content: string }>;
  messages: {
    role: string;
    content: string;
    created_at?: number;
    quote?: { role: "user" | "assistant"; content: string } | null;
    usage?: { input: number; output: number; cache: number };
    intermediate_blob_id?: number;
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
      injected?: string[];
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

export async function fetchSessions(limit = 50, offset = 0, q?: string, source?: string, mode?: string, hideHeartbeat?: boolean, hideScheduled?: boolean, titlePrefixes?: string, hasImages?: boolean): Promise<SessionInfo[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (q) params.set("q", q);
  if (source) params.set("source", source);
  if (mode !== undefined) params.set("mode", mode);
  if (hideHeartbeat) params.set("hide_heartbeat", "true");
  if (hideScheduled) params.set("hide_scheduled", "true");
  if (titlePrefixes) params.set("title_prefixes", titlePrefixes);
  if (hasImages) params.set("has_images", "true");
  const res = await fetch(`${getApiUrl()}/sessions?${params}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch sessions");
  const data = await res.json();
  const sessions = data.sessions as SessionInfo[];
  (sessions as SessionInfo[] & { total?: number }).total = data.total ?? undefined;
  return sessions;
}

/** 标记会话已读：未读水位推进到 updated_at（消除红点）。返回是否有实际推进。 */
export async function markSessionRead(id: string): Promise<boolean> {
  const res = await fetch(`${getApiUrl()}/sessions/${id}/read`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to mark session read");
  const data = await res.json();
  return !!data.advanced;
}

export async function renameSession(id: string, title: string): Promise<void> {
  await fetch(`${getApiUrl()}/sessions/${id}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify({ title }),
  });
}

export async function pinSession(id: string): Promise<void> {
  const res = await fetch(`${getApiUrl()}/sessions/${id}/pin`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to pin session");
}

export async function unpinSession(id: string): Promise<void> {
  const res = await fetch(`${getApiUrl()}/sessions/${id}/pin`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to unpin session");
}

export async function fetchPinnedSessions(): Promise<SessionInfo[]> {
  const res = await fetch(`${getApiUrl()}/sessions/pinned`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch pinned sessions");
  const data = await res.json();
  return data.sessions as SessionInfo[];
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

/** 将会话绑定的模型写回后端，用于「点击重名候选 → 持久化到当前会话」场景。
 *  PATCH /sessions/{id} 接受 { model }，与 updateSessionMode 复用同一端点。 */
export async function updateSessionModel(id: string, model: string): Promise<void> {
  await fetch(`${getApiUrl()}/sessions/${id}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify({ model }),
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

export async function deleteMessage(sessionId: string, messageId: number): Promise<void> {
  const res = await fetch(`${getApiUrl()}/sessions/${sessionId}/messages/${messageId}`, { method: "DELETE", headers: headers() });
  if (!res.ok) throw new Error("Delete message failed");
}

/** 编辑消息正文（阅读模式编辑）。后续对话上下文使用编辑后的版本。 */
export async function updateMessage(sessionId: string, messageId: number, content: string): Promise<void> {
  const res = await fetch(`${getApiUrl()}/sessions/${sessionId}/messages/${messageId}`, {
    method: "PATCH",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error("Update message failed");
}

export async function fetchMessageIntermediate(sessionId: string, messageId: number): Promise<string> {
  const res = await fetch(`${getApiUrl()}/sessions/${sessionId}/messages/${messageId}/intermediate`, { headers: headers() });
  if (!res.ok) {
    let detail = "过程记录加载失败";
    try {
      const body = await res.clone().json();
      detail = typeof body?.detail === "string" ? body.detail : detail;
    } catch {}
    throw new Error(detail);
  }
  return res.text();
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
