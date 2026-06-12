const API_URL = typeof window !== "undefined" 
  ? `${window.location.protocol}//${window.location.hostname === "localhost" ? "127.0.0.1" : window.location.hostname}:8900`
  : (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8900");

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

export async function fetchModels(): Promise<{ id: string; description: string; alias: string[] }[]> {
  const res = await fetch(`${API_URL}/models`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch models");
  const data = await res.json();
  return data.models;
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
  messages: { role: string; content: string; created_at?: number }[];
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
  system_prompt: string;
  agent_name: string;
  language: string;
  default_model: string;
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
  format: string;
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

export async function fetchEpisodes(): Promise<Episode[]> {
  const res = await fetch(`${API_URL}/memory/episodes`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(data => data.episodes);
}

export async function* streamChat(
  messages: ChatMessage[],
  model?: string,
  sessionId?: string,
): AsyncGenerator<{ content?: string; done?: boolean; error?: string; model?: string; usage?: Record<string, number>; tool?: string; args?: string; state?: string }> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ messages, model, stream: true, session_id: sessionId }),
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

export async function deleteKnowledge(source: string): Promise<void> {
  const res = await fetch(`${API_URL}/knowledge/${encodeURIComponent(source)}`, {
    method: "DELETE",
    headers: headers()
  });
  if (!res.ok) throw new Error("Failed");
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
