/** Settings 相关类型和 API（Agent/Provider/System/Profile/ToolTiers/FastRules）。 */

import { API_URL, headers } from "./api-base";

// ── Agent Settings ────────────────────────────────────────────────

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

// ── Provider Settings ─────────────────────────────────────────────

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

// ── System Settings ───────────────────────────────────────────────

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

// ── User Profile (我的画像) ───────────────────────────────────────

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

// ── System Prompt Preview ─────────────────────────────────────────

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

// ── Tool Tiers ────────────────────────────────────────────────────

export interface TierTool {
  name: string;
  description: string;
  fast_path: boolean;
  in_full_base: boolean;
  side_effect: boolean;
  no_compress: boolean;
}

export interface ToolTier {
  key: "fast" | "full";
  label: string;
  desc: string;
  tools: TierTool[];
}

export interface ToolTiers {
  tiers: ToolTier[];
  fast_count: number;
  fast_rule_tool_count: number;
  full_count: number;
  longtail_count: number;
  total_count: number;
}

export async function fetchToolTiers(): Promise<ToolTiers> {
  const res = await fetch(`${API_URL}/tool-tiers`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}

// ── Fast Rules ────────────────────────────────────────────────────

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
