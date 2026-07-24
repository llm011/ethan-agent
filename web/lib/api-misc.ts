/** 杂项 API（Schedule/BackgroundTasks/Knowledge/Poll/Logs/Skills/Onboarding/Channels/Docs/APIKeys）。 */

import { API_URL, headers } from "./api-base";
import type { SessionInfo } from "./api-sessions";

// ── Schedule ──────────────────────────────────────────────────────

export type ScheduleCategory = "one_off" | "recurring" | "timeline";

export interface ScheduleJob {
  id: string;
  name: string;
  next_run_time: string | null;
  trigger: string;
  status: "paused" | "active";
  prompt: string;
  session_id: string;
  category: ScheduleCategory;
  source_timeline?: string;
  source_phase?: string;
  scene?: string;
}

export async function fetchSchedules(): Promise<ScheduleJob[]> {
  const res = await fetch(`${API_URL}/schedule`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(data => data.jobs.map((j: any) => ({ ...j, name: j.title || j.name || j.id })));
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
    body: JSON.stringify({ title: name })
  });
  if (!res.ok) throw new Error("Failed");
}

export async function updateSchedulePrompt(jobId: string, prompt: string): Promise<void> {
  const res = await fetch(`${API_URL}/schedule/${jobId}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify({ prompt })
  });
  if (!res.ok) throw new Error("Failed");
}

export async function triggerSchedule(jobId: string): Promise<void> {
  const res = await fetch(`${API_URL}/schedule/${jobId}/trigger`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed");
}

// ── Timeline ──────────────────────────────────────────────────────

export interface TimelineTask {
  job_id: string;
  kind: "once" | "recurring";
  fire_at: string | null;
  cron: string | null;
  active_from: string | null;
  active_until: string | null;
  message: string;
  source_phase: string;
  passed: boolean | null;
}

export interface TimelineStatus {
  id: string;
  name: string;
  scene: string;
  anchor_date: string;
  current_phase: string | null;
  phase_start: string | null;
  phase_end: string | null;
  next_phase: string | null;
  next_anchor: string;
  tasks: TimelineTask[];
}

export async function fetchTimelineStatus(): Promise<TimelineStatus[]> {
  const res = await fetch(`${API_URL}/schedule/timeline-status`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(d => d.timelines);
}

export async function syncTimelines(): Promise<{ ok: boolean; added: number; removed: number; updated: number; kept: number }> {
  const res = await fetch(`${API_URL}/schedule/sync-timelines`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}

export async function timelineLifecycle(timelineId: string, action: "skip_phase" | "advance_phase" | "pause" | "resume" | "cleanup"): Promise<Record<string, any>> {
  const res = await fetch(`${API_URL}/schedule/timeline/${encodeURIComponent(timelineId)}/${action}`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}

// ── Background Tasks ──────────────────────────────────────────────

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

// ── Knowledge ─────────────────────────────────────────────────────

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

// ── Poll ──────────────────────────────────────────────────────────

export interface PollData {
  sessions: Pick<SessionInfo, "id" | "title" | "model" | "updated_at" | "source" | "mode">[];
}

export async function fetchPoll(hideHeartbeat?: boolean, hideScheduled?: boolean): Promise<PollData> {
  const params = new URLSearchParams();
  if (hideHeartbeat) params.set("hide_heartbeat", "true");
  if (hideScheduled) params.set("hide_scheduled", "true");
  const qs = params.toString();
  const res = await fetch(`${API_URL}/poll${qs ? `?${qs}` : ""}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}

// ── Logs ──────────────────────────────────────────────────────────

export async function fetchLogs(type: "backend" | "frontend" = "backend", lines: number = 500, q?: string): Promise<string> {
  const params = new URLSearchParams({ type, lines: String(lines) });
  if (q) params.set("q", q);
  const res = await fetch(`${API_URL}/logs?${params}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch logs");
  const data = await res.json();
  return data.content || "";
}

// ── Skills ────────────────────────────────────────────────────────

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

// ── Skill Context ─────────────────────────────────────────────────

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

// ── Onboarding ────────────────────────────────────────────────────

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

// ── Channels ──────────────────────────────────────────────────────

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

// ── Docs ──────────────────────────────────────────────────────────

/** 静态文档基路径（GitHub Pages 部署时由 CI 注入）。未设置时走后端 API。 */
const STATIC_DOCS_BASE = process.env.NEXT_PUBLIC_DOCS_BASE || "";

export interface DocMeta { slug: string; title: string; filename: string; }

export async function fetchDocsList(): Promise<DocMeta[]> {
  const res = await fetch(`${API_URL}/docs`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json().then(d => d.docs);
}

export async function fetchDoc(slug: string): Promise<{ slug: string; content: string }> {
  if (STATIC_DOCS_BASE) {
    const res = await fetch(`${STATIC_DOCS_BASE}/${slug}.json`);
    if (!res.ok) throw new Error("Failed");
    return res.json();
  }
  const res = await fetch(`${API_URL}/docs/${slug}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}

/** 解析文档中的图片路径（静态模式用 STATIC_DOCS_BASE，否则用 API_URL） */
export function resolveDocsImageUrl(src: string): string {
  if (src.startsWith("./images/")) {
    const filename = src.slice("./images/".length);
    return STATIC_DOCS_BASE
      ? `${STATIC_DOCS_BASE}/images/${filename}`
      : `${API_URL}/docs/images/${filename}`;
  }
  return src;
}

// ── API Keys ──────────────────────────────────────────────────────

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
