/** Memory 相关类型和 API（Facts/Episodes/Procedures/Insights/Signals）。 */

import { API_URL, headers } from "./api-base";

// ── Facts ─────────────────────────────────────────────────────────

export interface Fact { id: string; content: string; confidence: number; category: string; source: string; created_at: number; superseded_by: string | null; }

export async function fetchFacts(): Promise<Fact[]> {
  const res = await fetch(`${API_URL}/memory/facts`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(data => data.facts);
}

export async function deleteFact(factId: string): Promise<void> {
  await fetch(`${API_URL}/memory/facts/${factId}`, { method: "DELETE", headers: headers() });
}

export async function updateFact(factId: string, content: string): Promise<void> {
  await fetch(`${API_URL}/memory/facts/${factId}`, {
    method: "PATCH",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

// ── Episodes ──────────────────────────────────────────────────────

export interface Episode { id: string; session_id: string; timestamp: number; summary: string; turn_count: number; keywords: string[]; model: string; }

export async function fetchEpisodes(): Promise<Episode[]> {
  const res = await fetch(`${API_URL}/memory/episodes`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(data => data.episodes);
}

export async function deleteEpisode(id: string): Promise<void> {
  await fetch(`${API_URL}/memory/episodes/${id}`, { method: "DELETE", headers: headers() });
}

// ── Procedures ────────────────────────────────────────────────────

export interface Procedure {
  id: string;
  rule: string;
  context: string;
  hit_count: number;
  created_at: number;
}

export async function fetchProcedures(): Promise<Procedure[]> {
  const res = await fetch(`${API_URL}/memory/procedures`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(d => d.procedures);
}

export async function deleteProcedure(id: string): Promise<void> {
  await fetch(`${API_URL}/memory/procedures/${id}`, { method: "DELETE", headers: headers() });
}

// ── Insights (永久记忆) ───────────────────────────────────────────

export interface Insight {
  id: string;
  text: string;
  metadata: { type?: string; date?: string; created_at?: number; [key: string]: unknown };
}

export interface InsightsResponse {
  total: number;
  items: Insight[];
  limit: number;
  offset: number;
}

export async function fetchInsights(limit = 20, offset = 0): Promise<InsightsResponse> {
  const res = await fetch(`${API_URL}/memory/insights?limit=${limit}&offset=${offset}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch insights");
  return res.json();
}

export async function fetchInsightsByDate(dateStr: string): Promise<Insight[]> {
  const res = await fetch(`${API_URL}/memory/insights/date/${dateStr}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch insights by date");
  return res.json().then(d => d.items);
}

// ── Signals (每日信号) ────────────────────────────────────────────

export interface Signal {
  type: string;
  ts?: number;
  pattern?: string;
  count?: number;
  suggestion?: string;
  context?: string;
  resolution?: string;
  scenario?: string;
  method?: string;
}

export async function fetchTodaySignals(): Promise<Signal[]> {
  const res = await fetch(`${API_URL}/memory/signals/today`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch today signals");
  return res.json().then(d => d.signals);
}

export async function fetchSignalsByDate(dateStr: string): Promise<Signal[]> {
  const res = await fetch(`${API_URL}/memory/signals/date/${dateStr}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch signals by date");
  return res.json().then(d => d.signals);
}

export async function triggerConsolidation(): Promise<{ ok: boolean; added: number }> {
  const res = await fetch(`${API_URL}/memory/consolidate`, { method: "POST", headers: headers() });
  if (!res.ok) throw new Error("Failed to trigger consolidation");
  return res.json();
}

// ── Structured memory records ──────────────────────────────────────

export type StructuredMemoryType =
  | "personal_information"
  | "preference"
  | "methodology"
  | "activity"
  | "decision"
  | "relationship"
  | "companion"
  | "skill_experience";

export interface StructuredMemory {
  id: string;
  memory_type: StructuredMemoryType;
  dimension: string;
  memory_key: string;
  content: string;
  structured_data: Record<string, unknown>;
  scope_type: string;
  scope_id: string;
  memory_domain: "general" | "companion";
  status: string;
  evidence_level: string;
  confidence: number;
  importance: number;
  sensitivity: string;
  valid_from: number | null;
  valid_until: number | null;
  source_session_id: string;
  source_message_id: string;
  created_at: number;
  updated_at: number;
  last_recalled_at: number | null;
  superseded_by: string | null;
}

export interface StructuredMemoryPatch {
  content?: string;
  structured_data?: Record<string, unknown>;
  confidence?: number;
  importance?: number;
  valid_from?: number | null;
  valid_until?: number | null;
  clear_valid_from?: boolean;
  clear_valid_until?: boolean;
}

export interface DailySummary {
  id: string;
  user_id: string;
  local_date: string;
  pipeline_version: string;
  memory_domain: "general" | "companion";
  summary_text: string;
  structured_data: Record<string, unknown[]>;
  source_from: number | null;
  source_until: number | null;
  created_at: number;
  updated_at: number;
}

function recordParams(params: {
  type?: StructuredMemoryType;
  status?: string;
  domain?: "general" | "companion";
  limit?: number;
  offset?: number;
}): string {
  const q = new URLSearchParams();
  if (params.type) q.set("type", params.type);
  if (params.status) q.set("status", params.status);
  if (params.domain) q.set("domain", params.domain);
  if (params.limit !== undefined) q.set("limit", String(params.limit));
  if (params.offset !== undefined) q.set("offset", String(params.offset));
  const suffix = q.toString();
  return suffix ? `?${suffix}` : "";
}

export async function fetchStructuredMemories(params: {
  type?: StructuredMemoryType;
  status?: string;
  domain?: "general" | "companion";
  limit?: number;
  offset?: number;
} = {}): Promise<StructuredMemory[]> {
  const res = await fetch(`${API_URL}/memory/records${recordParams(params)}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch structured memories");
  return res.json().then(data => data.items);
}

export async function searchStructuredMemories(
  query: string,
  params: { type?: StructuredMemoryType; domain?: "general" | "companion"; status?: string } = {},
): Promise<StructuredMemory[]> {
  const q = new URLSearchParams({ q: query });
  if (params.type) q.set("type", params.type);
  if (params.domain) q.set("domain", params.domain);
  if (params.status) q.set("status", params.status);
  const res = await fetch(`${API_URL}/memory/records/search?${q.toString()}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to search structured memories");
  return res.json().then(data => data.items);
}

export async function updateStructuredMemory(id: string, patch: StructuredMemoryPatch): Promise<StructuredMemory> {
  const body: Record<string, unknown> = { ...patch };
  if (patch.valid_from === null) {
    delete body.valid_from;
    body.clear_valid_from = true;
  }
  if (patch.valid_until === null) {
    delete body.valid_until;
    body.clear_valid_until = true;
  }
  const res = await fetch(`${API_URL}/memory/records/${id}`, {
    method: "PATCH",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to update structured memory");
  return res.json().then(data => data.record);
}

export async function forgetStructuredMemory(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/memory/records/${id}`, { method: "DELETE", headers: headers() });
  if (!res.ok) throw new Error("Failed to forget structured memory");
}

export async function confirmStructuredCandidate(id: string): Promise<StructuredMemory | null> {
  const res = await fetch(`${API_URL}/memory/records/${id}/confirm`, { method: "POST", headers: headers() });
  if (!res.ok) throw new Error("Failed to confirm memory candidate");
  return res.json().then(data => data.record ?? null);
}

export async function fetchDailySummaries(params: {
  date?: string;
  domain?: "general" | "companion";
  limit?: number;
} = {}): Promise<DailySummary[]> {
  const q = new URLSearchParams();
  if (params.domain) q.set("domain", params.domain);
  if (params.limit !== undefined) q.set("limit", String(params.limit));
  const path = params.date
    ? `/memory/records/summaries/${params.date}`
    : "/memory/records/summaries";
  const suffix = q.toString() ? `?${q.toString()}` : "";
  const res = await fetch(`${API_URL}${path}${suffix}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch daily summaries");
  return res.json().then(data => data.items);
}

export async function triggerStructuredConsolidation(targetDate?: string): Promise<{ ok: boolean; result: Record<string, unknown> }> {
  const suffix = targetDate ? `?target_date=${encodeURIComponent(targetDate)}` : "";
  const res = await fetch(`${API_URL}/memory/records/consolidate${suffix}`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to trigger structured consolidation");
  return res.json();
}
