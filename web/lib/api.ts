export const API_URL = typeof window !== "undefined"
  ? (process.env.NEXT_PUBLIC_API_URL
    ? process.env.NEXT_PUBLIC_API_URL
    : window.location.port === "8900"
      ? `${window.location.origin}/api`
      : `${window.location.protocol}//${window.location.hostname === "localhost" ? "127.0.0.1" : window.location.hostname}:8900/api`)
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

function headers(): HeadersInit {
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
}

export async function fetchModels(): Promise<ModelEntry[]> {
  const res = await fetch(`${API_URL}/models`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch models");
  const data = await res.json();
  return data.models;
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

export interface SessionInfo {
  id: string;
  title: string;
  model: string;
  created_at: number;
  updated_at: number;
  snippet?: string;
  source?: string;
}

export interface SessionDetail {
  id: string;
  title: string;
  model: string;
  source?: string;
  messages: {
    role: string;
    content: string;
    created_at?: number;
    usage?: { input: number; output: number; cache: number };
    tool_steps?: Array<{
      tool: string;
      args: string;
      state: string;
      duration_ms?: number | null;
      result_preview?: string;
      result_detail?: string;
      thought?: string;
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

export async function fetchSessions(limit = 50, offset = 0, q?: string): Promise<SessionInfo[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (q) params.set("q", q);
  const res = await fetch(`${API_URL}/sessions?${params}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch sessions");
  const data = await res.json();
  return data.sessions;
}

export async function renameSession(id: string, title: string): Promise<void> {
  await fetch(`${API_URL}/sessions/${id}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify({ title }),
  });
}

export async function createSession(model?: string): Promise<{ id: string; title: string; model: string }> {
  const res = await fetch(`${API_URL}/sessions${model ? `?model=${model}` : ""}`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to create session");
  return res.json();
}

export async function fetchSession(id: string): Promise<SessionDetail> {
  const res = await fetch(`${API_URL}/sessions/${id}`, { headers: headers() });
  if (!res.ok) throw new Error("Session not found");
  return res.json();
}

export async function deleteSession(id: string): Promise<void> {
  await fetch(`${API_URL}/sessions/${id}`, { method: "DELETE", headers: headers() });
}

export async function compactSession(id: string): Promise<{ ok: boolean; summary: string }> {
  const res = await fetch(`${API_URL}/sessions/${id}/compact`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Compact failed");
  return res.json();
}

export async function uploadFile(file: File): Promise<{ path: string; filename: string }> {
  const form = new FormData();
  form.append("file", file);
  const h: HeadersInit = {};
  const token = getAuthToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_URL}/upload`, { method: "POST", headers: h, body: form });
  if (!res.ok) throw new Error("Upload failed");
  return res.json();
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string; created_at?: number;
}

export interface AgentSettings {
  workspace: string;
  agent_name: string;
  language: string;
  default_model: string;
  lite_model: string;
  heartbeat_enabled: boolean;
  heartbeat_interval_minutes: number;
  proxy: string;
  max_tokens: number;
  max_tool_iterations: number;
  fast_keywords: string[];
  fast_max_length: number;
  fast_skill_triggers: string[];
}
export async function fetchAgentSettings(): Promise<AgentSettings> {
  const res = await fetch(`${API_URL}/settings/agent`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch settings");
  return res.json();
}
export async function updateAgentSettings(patch: Partial<AgentSettings>): Promise<void> {
  await fetch(`${API_URL}/settings/agent`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify(patch),
  });
}



export type ProviderSettings = Record<string, { api_key: string, base_url: string | null }>;

export async function fetchProviderSettings(): Promise<ProviderSettings> {
  const res = await fetch(`${API_URL}/settings/providers`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch provider settings");
  return res.json();
}

export async function updateProviderSettings(patch: ProviderSettings): Promise<void> {
  await fetch(`${API_URL}/settings/providers`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify(patch),
  });
}

export interface SystemSettings {
  identity: string;
  soul: string;
  agent: string;
  tools: string;
  heartbeat: string;
}

export async function fetchSystemSettings(): Promise<SystemSettings> {
  const res = await fetch(`${API_URL}/settings/system`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch system settings");
  return res.json();
}

export async function updateSystemSettings(patch: Partial<SystemSettings>): Promise<void> {
  await fetch(`${API_URL}/settings/system`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify(patch),
  });
}

// ── User profile (我的画像) ───────────────────────────────────────

export async function fetchUserProfile(): Promise<string> {
  const res = await fetch(`${API_URL}/settings/profile`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch user profile");
  return (await res.json()).content;
}

export async function updateUserProfile(content: string): Promise<void> {
  await fetch(`${API_URL}/settings/profile`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify({ content }),
  });
}

export interface ToolSchema {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  fast_path: boolean;
}

export interface SystemPromptPreview {
  system_prompt: string;
  tools: ToolSchema[];
  approx_tokens: number;
  approx_tools_tokens: number;
  tool_count: number;
  approx_total_tokens: number;
  chars: number;
}

export async function fetchSystemPromptPreview(): Promise<SystemPromptPreview> {
  const res = await fetch(`${API_URL}/system-prompt-preview`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}


export interface Fact { id: string; content: string; confidence: number; category: string; source: string; created_at: number; superseded_by: string | null; }
export interface Episode { id: string; session_id: string; timestamp: number; summary: string; turn_count: number; keywords: string[]; model: string; }

export interface ScheduleJob {
  id: string;
  name: string;
  next_run_time: string | null;
  trigger: string;
  status: "paused" | "active";
  prompt: string;
  session_id: string;
}

export async function fetchSchedules(): Promise<ScheduleJob[]> {
  const res = await fetch(`${API_URL}/schedule`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(data => data.jobs);
}

export async function deleteSchedule(jobId: string): Promise<void> {
  const res = await fetch(`${API_URL}/schedule/${jobId}`, {
    method: "DELETE",
    headers: headers()
  });
  if (!res.ok) throw new Error("Failed");
}

export async function patchSchedule(jobId: string, state: "paused" | "active"): Promise<void> {
  const res = await fetch(`${API_URL}/schedule/${jobId}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify({ state })
  });
  if (!res.ok) throw new Error("Failed");
}

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

export async function fetchEpisodes(): Promise<Episode[]> {
  const res = await fetch(`${API_URL}/memory/episodes`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(data => data.episodes);
}

export async function deleteEpisode(id: string): Promise<void> {
  await fetch(`${API_URL}/memory/episodes/${id}`, { method: "DELETE", headers: headers() });
}

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

export async function* streamChat(
  messages: ChatMessage[],
  model?: string,
  sessionId?: string,
  quote?: { role: "user" | "assistant"; content: string } | null,
): AsyncGenerator<{ content?: string; done?: boolean; error?: string; model?: string; usage?: Record<string, number>; tool?: string; args?: string; state?: string; id?: string; duration_ms?: number; result_preview?: string; result_detail?: string; sub_steps?: Array<{ tool: string; args: string; state: string; duration_ms?: number | null; result_preview?: string }>; consent_request?: boolean; request_id?: string; description?: string; detail?: string }> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ messages, model, stream: true, session_id: sessionId, quote: quote ?? undefined }),
  });

  if (!res.ok) {
    throw new Error(`Chat failed: ${res.status}`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6));
        } catch {}
      }
    }
  }
}

export interface KnowledgeItem {
  source: string;
  title: string;
  content?: string;
  tags?: string[];
  score?: number | null;
}

export async function searchKnowledge(q: string, limit = 10, semantic = true): Promise<KnowledgeItem[]> {
  const params = new URLSearchParams({ q, limit: String(limit), semantic: String(semantic) });
  const res = await fetch(`${API_URL}/knowledge/search?${params}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(d => d.results);
}

export async function fetchKnowledge(query?: string, mode: "keyword" | "semantic" = "keyword"): Promise<KnowledgeItem[]> {
  const params = new URLSearchParams();
  if (query) params.set("q", query);
  if (query && mode !== "keyword") params.set("mode", mode);
  const url = params.toString() ? `${API_URL}/knowledge?${params}` : `${API_URL}/knowledge`;
  const res = await fetch(url, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(data => data.items);
}

export async function addKnowledge(item: { title: string; content: string; created_at?: number; tags: string[] }): Promise<void> {
  const res = await fetch(`${API_URL}/knowledge`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(item)
  });
  if (!res.ok) throw new Error("Failed");
}

export async function updateKnowledge(source: string, item: { title: string; content: string; tags: string[] }): Promise<void> {
  const res = await fetch(`${API_URL}/knowledge/${encodeURIComponent(source)}`, {
    method: "PUT",
    headers: headers(),
    body: JSON.stringify(item),
  });
  if (!res.ok) throw new Error("Failed");
}

export async function deleteKnowledge(source: string): Promise<void> {
  const res = await fetch(`${API_URL}/knowledge/${encodeURIComponent(source)}`, {
    method: "DELETE",
    headers: headers()
  });
  if (!res.ok) throw new Error("Failed");
}

export interface PollData {
  sessions: Pick<SessionInfo, "id" | "title" | "model" | "updated_at" | "source">[];
}

export async function fetchPoll(): Promise<PollData> {
  const res = await fetch(`${API_URL}/poll`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}

export async function fetchLogs(type: "backend" | "frontend" = "backend", lines: number = 500, q?: string): Promise<string> {
  const params = new URLSearchParams({ type, lines: String(lines) });
  if (q) params.set("q", q);
  const res = await fetch(`${API_URL}/logs?${params}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch logs");
  const data = await res.json();
  return data.content || "";
}


export interface SkillInfo {
  name: string;
  description: string;
  trigger: string[];
  content: string;
}

export async function fetchSkills(): Promise<SkillInfo[]> {
  const res = await fetch(`${API_URL}/skills`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch skills");
  return res.json().then(data => data.skills);
}

export async function fetchSkill(name: string): Promise<SkillInfo> {
  const res = await fetch(`${API_URL}/skills/${encodeURIComponent(name)}`, { headers: headers() });
  if (!res.ok) throw new Error("Skill not found");
  return res.json();
}

export async function saveSkill(skill: SkillInfo): Promise<{ name: string }> {
  const res = await fetch(`${API_URL}/skills`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(skill)
  });
  if (!res.ok) throw new Error("Failed to save skill");
  return res.json();
}

export async function deleteSkill(name: string): Promise<{ ok: boolean; removed?: string[]; error?: string }> {
  const res = await fetch(`${API_URL}/skills/${encodeURIComponent(name)}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    return { ok: false, error: err.detail || `Failed (${res.status})` };
  }
  return res.json();
}

export interface OnboardingStatus {
  first_time: boolean;
  message: string;
}

export async function fetchOnboardingStatus(): Promise<OnboardingStatus> {
  const res = await fetch(`${API_URL}/onboarding/status`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch onboarding status");
  return res.json();
}

export async function completeOnboarding(agent_name: string, user_info: string): Promise<{ ok: boolean; agent_name: string }> {
  const res = await fetch(`${API_URL}/onboarding/complete`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ agent_name, user_info }),
  });
  if (!res.ok) throw new Error("Failed to complete onboarding");
  return res.json();
}

export interface ChannelInfo {
  id: string;
  name: string;
  enabled: boolean;
  config: Record<string, string>;
}

export async function fetchChannels(): Promise<ChannelInfo[]> {
  const res = await fetch(`${API_URL}/channels`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(d => d.channels);
}

export async function patchChannel(channelId: string, config: Record<string, string>): Promise<void> {
  const res = await fetch(`${API_URL}/channels`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify({ channel_id: channelId, config }),
  });
  if (!res.ok) throw new Error("Failed");
}

export interface DocMeta { slug: string; title: string; filename: string; }

export async function fetchDocsList(): Promise<DocMeta[]> {
  const res = await fetch(`${API_URL}/docs`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(d => d.docs);
}

export async function fetchDoc(slug: string): Promise<{ slug: string; content: string }> {
  const res = await fetch(`${API_URL}/docs/${slug}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}

// ── API Keys ─────────────────────────────────────────────────────

export interface APIKeyInfo {
  id: string;
  name: string;
  key_preview: string;
  created_at: number;
  last_used_at: number | null;
}

export interface APIKeyCreated extends APIKeyInfo {
  key: string; // full key, only returned on creation
}

export async function fetchAPIKeys(): Promise<APIKeyInfo[]> {
  const res = await fetch(`${API_URL}/api-keys`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(d => d.keys);
}

export async function createAPIKey(name: string): Promise<APIKeyCreated> {
  const res = await fetch(`${API_URL}/api-keys`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}

export async function deleteAPIKey(keyId: string): Promise<void> {
  const res = await fetch(`${API_URL}/api-keys/${keyId}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed");
}

