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
