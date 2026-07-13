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
    matched_skills?: Array<{ name: string; is_default?: boolean }>;
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

export async function fetchSessions(limit = 50, offset = 0, q?: string, source?: string, mode?: string, hideHeartbeat?: boolean, hideScheduled?: boolean): Promise<SessionInfo[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (q) params.set("q", q);
  if (source) params.set("source", source);
  if (mode !== undefined) params.set("mode", mode);
  if (hideHeartbeat) params.set("hide_heartbeat", "true");
  if (hideScheduled) params.set("hide_scheduled", "true");
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


export async function regenSessionTitle(id: string): Promise<string | null> {
  const res = await fetch(`${API_URL}/sessions/${id}/regen-title`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data.ok ? data.title : null;
}
export async function updateSessionMode(id: string, mode: string): Promise<void> {
  await fetch(`${API_URL}/sessions/${id}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify({ mode }),
  });
}

export async function createSession(model?: string, mode?: string): Promise<{ id: string; title: string; model: string; mode?: string }> {
  const params = new URLSearchParams();
  if (model) params.append("model", model);
  if (mode) params.append("mode", mode);
  const qs = params.toString();
  const res = await fetch(`${API_URL}/sessions${qs ? `?${qs}` : ""}`, {
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

export async function cleanupTrivialSessions(): Promise<{ deleted: number; deleted_ids: string[] }> {
  const res = await fetch(`${API_URL}/sessions/cleanup-trivial`, {
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
  const res = await fetch(`${API_URL}/upload`, { method: "POST", headers: h, body: form });
  if (!res.ok) throw new Error("Upload failed");
  return res.json();
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  created_at?: number;
  images?: { data: string; media_type: string }[];  // base64 raw (no data: prefix)
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


export interface TierTool {
  name: string;
  description: string;
  fast_path: boolean;
  side_effect: boolean;
  no_compress: boolean;
}

export interface ToolTier {
  key: "fast" | "medium" | "full";
  label: string;
  desc: string;
  tools: TierTool[];
}

export interface ToolTiers {
  tiers: ToolTier[];
  fast_count: number;
  fast_rule_tool_count: number;
  total_count: number;
  medium_max_length: number;
}

export async function fetchToolTiers(): Promise<ToolTiers> {
  const res = await fetch(`${API_URL}/tool-tiers`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}

export interface FastRule {
  name: string;
  keywords: string[];
  tools: string[];
  skills: string[];
}

export interface FastRules {
  fast_base_tools: string[];
  fast_rules: FastRule[];
}

export interface FastRuleOption { name: string; description: string; }
export interface FastRuleOptions {
  tools: FastRuleOption[];
  skills: FastRuleOption[];
}

export async function fetchFastRules(): Promise<FastRules> {
  const res = await fetch(`${API_URL}/fast-rules`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}

export async function fetchFastRuleOptions(): Promise<FastRuleOptions> {
  const res = await fetch(`${API_URL}/fast-rules/options`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}

export async function updateFastRules(patch: Partial<FastRules>): Promise<void> {
  await fetch(`${API_URL}/fast-rules`, {
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

export interface BackgroundTask {
  id: string;
  title: string;
  status: "running" | "done" | "error" | "stopped";
  channel: string;
  started_at: number;
  elapsed_seconds: number;
}

export async function fetchBackgroundTasks(): Promise<BackgroundTask[]> {
  const res = await fetch(`${API_URL}/background-tasks`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(data => data.tasks);
}

export async function stopBackgroundTask(taskId: string): Promise<void> {
  const res = await fetch(`${API_URL}/background-tasks/${encodeURIComponent(taskId)}/stop`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed");
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

export async function renameSchedule(jobId: string, name: string): Promise<void> {
  const res = await fetch(`${API_URL}/schedule/${jobId}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify({ name })
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

export type StreamChunk = { content?: string; done?: boolean; stopped?: boolean; error?: string; model?: string; usage?: Record<string, number>; ttfb_ms?: number; total_ms?: number; tool?: string; args?: string; intent?: string; state?: string; id?: string; duration_ms?: number; result_preview?: string; result_detail?: string; entity_type?: string; entity_id?: string; sub_steps?: Array<{ tool: string; args: string; state: string; duration_ms?: number | null; result_preview?: string }>; ui?: unknown[]; consent_request?: boolean; request_id?: string; description?: string; detail?: string; thinking?: boolean; heartbeat?: boolean; elapsed?: number; skills_matched?: Array<{ name: string; is_default?: boolean }> };

/** 把一个 SSE Response body 解析成事件流（streamChat / streamResume 共用）。 */
async function* parseSSE(res: Response): AsyncGenerator<StreamChunk> {
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

export async function* streamChat(
  messages: ChatMessage[],
  model?: string,
  sessionId?: string,
  quote?: { role: "user" | "assistant"; content: string } | null,
  mode?: string,
  btw?: boolean,
  review?: boolean,
): AsyncGenerator<StreamChunk> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: headers(),
    // review 模式（/review）预授权：自动批准本次请求内的所有工具授权，
    // 不再弹「需要授权 · 执行 shell 命令」等确认框（见后端 ChatRequest.auto_consent）。
    body: JSON.stringify({ messages, model, stream: true, session_id: sessionId, quote: quote ?? undefined, mode: mode || undefined, btw: btw || undefined, auto_consent: review || undefined }),
  });

  if (!res.ok) {
    throw new Error(`Chat failed: ${res.status}`);
  }

  yield* parseSSE(res);
}

/** 重连一个仍在进行的生成：刷新页面后调此函数，回放缓冲 + 继续实时。
 *  无活跃 run 时后端返回 204，这里返回 null，调用方走普通 fetchSession。 */
export async function streamResume(sessionId: string): Promise<AsyncGenerator<StreamChunk> | null> {
  const res = await fetch(`${API_URL}/chat/${encodeURIComponent(sessionId)}/stream`, {
    headers: headers(),
  });
  if (res.status === 204 || !res.ok) return null;
  return parseSSE(res);
}

/** 停止某 session 进行中的生成；已生成内容会被保存并标记 [已停止]。 */
export async function stopGeneration(sessionId: string): Promise<{ ok: boolean; stopped: boolean }> {
  const res = await fetch(`${API_URL}/chat/${encodeURIComponent(sessionId)}/stop`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) return { ok: false, stopped: false };
  return res.json();
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
  sessions: Pick<SessionInfo, "id" | "title" | "model" | "updated_at" | "source" | "mode">[];
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

// ── Skill 上下文管理 ──────────────────────────────────────────────

export interface SkillContextItem {
  name: string;
  description: string;
  trigger: string[];
  category: string;  // "default" | "discoverable" | "plugin" | "disabled"
  is_default: boolean;
  full_tokens: number;
  brief_tokens: number;
  has_references: boolean;
  reference_count: number;
}

export interface SkillContextSummary {
  default_count: number;
  discoverable_count: number;
  plugin_count: number;
  total_default_tokens: number;
  total_discoverable_tokens: number;
  total_tokens: number;
}

export interface SkillContextResult {
  skills: SkillContextItem[];
  summary: SkillContextSummary;
}

export async function fetchSkillContext(): Promise<SkillContextResult> {
  const res = await fetch(`${API_URL}/skill-context`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch skill context");
  return res.json();
}

export async function updateSkillCategory(skillName: string, category: string): Promise<void> {
  const res = await fetch(`${API_URL}/skill-context`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify({ skill_name: skillName, category }),
  });
  if (!res.ok) throw new Error("Failed to update skill category");
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

export interface LarkDepsStatus {
  lark_oapi_installed: boolean;
  lark_cli_installed: boolean;
  lark_cli_app_synced: boolean;
  lark_cli_app_matches: boolean;
  installing: boolean;
  last_error: string;
  last_run_at: string;
  installed_by: string;
}

export async function fetchLarkDepsStatus(): Promise<LarkDepsStatus> {
  const res = await fetch(`${API_URL}/channels/lark/deps-status`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}

export async function installLarkDeps(): Promise<void> {
  const res = await fetch(`${API_URL}/channels/lark/install-deps`, {
    method: "POST",
    headers: headers(),
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

