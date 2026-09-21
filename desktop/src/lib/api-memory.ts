/** Memory 相关类型和 API（Facts/Episodes/Procedures/Insights/Signals）。 */

import { LLM_TASK_TIMEOUT_MS, fetchWithTimeout, getApiUrl, headers } from "./api-base";


// ── Facts ─────────────────────────────────────────────────────────

export interface Fact { id: string; content: string; confidence: number; category: string; source: string; created_at: number; superseded_by: string | null; }

export async function fetchFacts(): Promise<Fact[]> {
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/facts`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(data => data.facts);
}

export async function deleteFact(factId: string): Promise<void> {
  await fetchWithTimeout(`${getApiUrl()}/memory/facts/${factId}`, { method: "DELETE", headers: headers() });
}

export async function updateFact(factId: string, content: string): Promise<void> {
  await fetchWithTimeout(`${getApiUrl()}/memory/facts/${factId}`, {
    method: "PATCH",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

// ── Episodes ──────────────────────────────────────────────────────

export interface Episode { id: string; session_id: string; timestamp: number; summary: string; turn_count: number; keywords: string[]; model: string; }

export async function fetchEpisodes(): Promise<Episode[]> {
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/episodes`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(data => data.episodes);
}

export async function deleteEpisode(id: string): Promise<void> {
  await fetchWithTimeout(`${getApiUrl()}/memory/episodes/${id}`, { method: "DELETE", headers: headers() });
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
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/procedures`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(d => d.procedures);
}

export async function deleteProcedure(id: string): Promise<void> {
  await fetchWithTimeout(`${getApiUrl()}/memory/procedures/${id}`, { method: "DELETE", headers: headers() });
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
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/insights?limit=${limit}&offset=${offset}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch insights");
  return res.json();
}

export async function fetchInsightsByDate(dateStr: string): Promise<Insight[]> {
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/insights/date/${dateStr}`, { headers: headers() });
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
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/signals/today`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch today signals");
  return res.json().then(d => d.signals);
}

export async function fetchSignalsByDate(dateStr: string): Promise<Signal[]> {
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/signals/date/${dateStr}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch signals by date");
  return res.json().then(d => d.signals);
}

export async function triggerConsolidation(): Promise<{ ok: boolean; added: number }> {
  // 后端 await 整个「结构化复评 + 做梦 insight」流程才返回，LLM 密集、常需 20~60s，
  // 用默认 15s 会提前 abort（服务端仍在跑），前端误报失败。
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/consolidate`, { method: "POST", headers: headers(), timeoutMs: LLM_TASK_TIMEOUT_MS });
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
  dormant_at: number | null;
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

/** 结构化记忆的分页响应（与 /memory/insights 同形状）。 */
export interface StructuredMemoriesPage {
  items: StructuredMemory[];
  total: number;
  limit: number;
  offset: number;
}

function recordParams(params: {
  type?: StructuredMemoryType | StructuredMemoryType[];
  status?: string;
  domain?: "general" | "companion";
  limit?: number;
  offset?: number;
}): string {
  const q = new URLSearchParams();
  // 多 type 用逗号分隔发一个请求 —— 分页要的是「合并后切页」，
  // 各 type 各发一个请求再 flat 会出现「两半各自还有下一页」，offset 无意义。
  if (params.type) {
    const types = Array.isArray(params.type) ? params.type : [params.type];
    if (types.length > 0) q.set("type", types.join(","));
  }
  if (params.status) q.set("status", params.status);
  if (params.domain) q.set("domain", params.domain);
  if (params.limit !== undefined) q.set("limit", String(params.limit));
  if (params.offset !== undefined) q.set("offset", String(params.offset));
  const suffix = q.toString();
  return suffix ? `?${suffix}` : "";
}

/** 分页拉取结构化记忆（返回 total，供「还有没有下一页」判断）。 */
export async function fetchStructuredMemoriesPage(params: {
  type?: StructuredMemoryType | StructuredMemoryType[];
  status?: string;
  domain?: "general" | "companion";
  limit?: number;
  offset?: number;
} = {}): Promise<StructuredMemoriesPage> {
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/records${recordParams(params)}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch structured memories");
  const data = await res.json();
  return {
    items: data.items ?? [],
    total: data.total ?? (data.items?.length ?? 0),
    limit: data.limit ?? params.limit ?? 0,
    offset: data.offset ?? params.offset ?? 0,
  };
}

export async function fetchStructuredMemories(params: {
  type?: StructuredMemoryType | StructuredMemoryType[];
  status?: string;
  domain?: "general" | "companion";
  limit?: number;
  offset?: number;
} = {}): Promise<StructuredMemory[]> {
  return (await fetchStructuredMemoriesPage(params)).items;
}

export async function searchStructuredMemories(
  query: string,
  params: { type?: StructuredMemoryType; domain?: "general" | "companion"; status?: string } = {},
): Promise<StructuredMemory[]> {
  const q = new URLSearchParams({ q: query });
  if (params.type) q.set("type", params.type);
  if (params.domain) q.set("domain", params.domain);
  if (params.status) q.set("status", params.status);
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/records/search?${q.toString()}`, { headers: headers() });
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
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/records/${id}`, {
    method: "PATCH",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to update structured memory");
  return res.json().then(data => data.record);
}

export async function forgetStructuredMemory(id: string): Promise<void> {
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/records/${id}`, { method: "DELETE", headers: headers() });
  if (!res.ok) throw new Error("Failed to forget structured memory");
}

export async function confirmStructuredCandidate(id: string): Promise<StructuredMemory | null> {
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/records/${id}/confirm`, { method: "POST", headers: headers() });
  if (!res.ok) throw new Error("Failed to confirm memory candidate");
  return res.json().then(data => data.record ?? null);
}

export async function wakeStructuredMemory(id: string): Promise<StructuredMemory | null> {
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/records/${id}/wake`, { method: "POST", headers: headers() });
  if (!res.ok) throw new Error("Failed to wake dormant memory");
  return res.json().then(data => data.record ?? null);
}

export async function wakeScopeMemories(scopeType: string, scopeId: string): Promise<number> {
  const q = new URLSearchParams({ scope_type: scopeType, scope_id: scopeId });
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/records/wake-scope?${q.toString()}`, { method: "POST", headers: headers() });
  if (!res.ok) throw new Error("Failed to wake dormant memories in scope");
  return res.json().then(data => data.woken ?? 0);
}

export interface DailySummariesPage {
  items: DailySummary[];
  /** 后端返回的总条数（用于判断「还有没有下一页」）。null 只为兼容不返回 total 的旧后端。 */
  total: number | null;
}

/**
 * 分页拉取每日摘要。
 *
 * 注意按日期查时**不分页**（一天通常 1-2 条，一次到位）；只有「全部日期」
 * 才走 offset 分页。日摘要是按 local_date DESC 的只读归档，offset 不会错位。
 */
export async function fetchDailySummariesPage(params: {
  date?: string;
  domain?: "general" | "companion";
  limit?: number;
  offset?: number;
} = {}): Promise<DailySummariesPage> {
  const q = new URLSearchParams();
  if (params.domain) q.set("domain", params.domain);
  if (params.limit !== undefined) q.set("limit", String(params.limit));
  if (params.offset !== undefined && !params.date) q.set("offset", String(params.offset));
  const path = params.date
    ? `/memory/records/summaries/${params.date}`
    : "/memory/records/summaries";
  const suffix = q.toString() ? `?${q.toString()}` : "";
  const res = await fetchWithTimeout(`${getApiUrl()}${path}${suffix}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch daily summaries");
  const data = await res.json();
  return {
    items: data.items ?? [],
    total: typeof data.total === "number" ? data.total : null,
  };
}

export async function fetchDailySummaries(params: {
  date?: string;
  domain?: "general" | "companion";
  limit?: number;
  offset?: number;
} = {}): Promise<DailySummary[]> {
  return (await fetchDailySummariesPage(params)).items;
}

export async function triggerStructuredConsolidation(targetDate?: string): Promise<{ ok: boolean; result: Record<string, unknown> }> {
  const suffix = targetDate ? `?target_date=${encodeURIComponent(targetDate)}` : "";
  const res = await fetchWithTimeout(`${getApiUrl()}/memory/records/consolidate${suffix}`, {
    method: "POST",
    headers: headers(),
    // 同 triggerConsolidation：LLM 密集的长任务，用默认 15s 会误报失败
    timeoutMs: LLM_TASK_TIMEOUT_MS,
  });
  if (!res.ok) throw new Error("Failed to trigger structured consolidation");
  return res.json();
}
