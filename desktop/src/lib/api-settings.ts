/** Settings 相关类型和 API（Agent/Provider/System/Profile/ToolTiers/FastRules）。 */

import { fetchWithTimeout, getApiUrl, getAuthToken, headers } from "./api-base";
import { bustCache } from "./local-cache";
import type { UserIdentity } from "@ethan/shared/chat/user-identity";

// ── Agent Settings ────────────────────────────────────────────────

export interface AgentSettings {
  workspace: string;
  agent_name: string;
  language: string;
  default_model: string;
  lite_model: string;
  heartbeat_enabled: boolean;
  heartbeat_interval_minutes: number;
  heartbeat_model: string;
  schedule_model: string;
  /** true（默认）时定时/心跳任务跟随默认模型；false 时各自独立配置 */
  model_sync: boolean;
  proxy: string;
  max_tokens: number;
  max_tool_iterations: number;
}

export async function fetchAgentSettings(): Promise<AgentSettings> {
  const res = await fetchWithTimeout(`${getApiUrl()}/settings/agent`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch settings");
  return res.json();
}

export async function updateAgentSettings(patch: Partial<AgentSettings>): Promise<void> {
  await fetchWithTimeout(`${getApiUrl()}/settings/agent`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify(patch),
  });
  // 写操作成功后失效缓存，所有 useCachedResource("agentSettings") 自动 refetch
  bustCache("agentSettings");
}

// ── Provider Settings ─────────────────────────────────────────────

export type ProviderType = "anthropic" | "openai_compat";

export interface ProviderConfig {
  api_key: string;
  base_url: string | null;
  type: ProviderType;
  disable_prompt_cache: boolean;
}

export type ProviderSettings = Record<string, ProviderConfig>;

export async function fetchProviderSettings(): Promise<ProviderSettings> {
  const res = await fetchWithTimeout(`${getApiUrl()}/settings/providers`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch provider settings");
  return res.json();
}

export async function updateProviderSettings(patch: ProviderSettings): Promise<void> {
  await fetchWithTimeout(`${getApiUrl()}/settings/providers`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify(patch),
  });
}

export async function deleteProvider(key: string): Promise<void> {
  const res = await fetchWithTimeout(`${getApiUrl()}/settings/providers/${encodeURIComponent(key)}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to delete provider");
}

export async function renameProvider(oldKey: string, newKey: string): Promise<void> {
  const res = await fetchWithTimeout(`${getApiUrl()}/settings/providers/${encodeURIComponent(oldKey)}/rename`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ new_key: newKey }),
  });
  if (!res.ok) throw new Error("Failed to rename provider");
}

// ── Provider Presets ──────────────────────────────────────────────

export interface ProviderPreset {
  key: string;
  base_url: string;
  type: ProviderType;
  disable_prompt_cache?: boolean;
  description: string;
  models: string[];
}

export async function fetchProviderPresets(): Promise<ProviderPreset[]> {
  const res = await fetchWithTimeout(`${getApiUrl()}/settings/providers/presets`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch provider presets");
  const data = await res.json();
  return data.presets;
}

// ── System Settings ───────────────────────────────────────────────

export interface SystemSettings {
  identity: string;
  soul: string;
  agent: string;
  tools: string;
  heartbeat: string;
  naming: string;
}

export async function fetchSystemSettings(): Promise<SystemSettings> {
  const res = await fetchWithTimeout(`${getApiUrl()}/settings/system`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch system settings");
  return res.json();
}

export async function updateSystemSettings(patch: Partial<SystemSettings>): Promise<void> {
  await fetchWithTimeout(`${getApiUrl()}/settings/system`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify(patch),
  });
}

// ── User Profile (我的画像) ───────────────────────────────────────

export interface UserProfileData {
  content: string;
  display_name: string;
  /** 相对 URL（`images/img_avatar.<ext>`）；未设置头像时为空串 */
  avatar_url: string;
}

export async function fetchUserProfile(): Promise<string> {
  const res = await fetchWithTimeout(`${getApiUrl()}/settings/profile`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch user profile");
  return (await res.json()).content;
}

/** 与 fetchUserProfile 同源，但一并取回头像/显示名（设置页预览用）。 */
export async function fetchUserProfileData(): Promise<UserProfileData> {
  const res = await fetchWithTimeout(`${getApiUrl()}/settings/profile`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch user profile");
  const data = await res.json();
  return {
    content: data.content ?? "",
    display_name: data.display_name ?? "",
    avatar_url: data.avatar_url ?? "",
  };
}

export async function updateUserProfile(content: string): Promise<void> {
  await fetchWithTimeout(`${getApiUrl()}/settings/profile`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify({ content }),
  });
}

// ── 气泡身份（头像 / 显示名） ─────────────────────────────────────

export type { UserIdentity } from "@ethan/shared/chat/user-identity";

/** 对话气泡用的身份信息。轻量接口，聊天页挂载时读一次。 */
export async function fetchUserIdentity(): Promise<UserIdentity> {
  const res = await fetchWithTimeout(`${getApiUrl()}/user/identity`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch user identity");
  const data = await res.json();
  return {
    user_id: data.user_id ?? "",
    display_name: data.display_name ?? "",
    avatar_url: data.avatar_url ?? "",
  };
}

/** 上传头像（唯一设置头像的途径），返回新的相对 URL。 */
export async function uploadAvatar(file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  // 多部分请求不能手写 Content-Type —— 必须让浏览器补上带 boundary 的那个，
  // 否则后端 multipart 解析拿不到文件。
  const h: HeadersInit = {};
  const token = getAuthToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  const res = await fetchWithTimeout(`${getApiUrl()}/user/avatar`, {
    method: "PUT",
    headers: h,
    body: form,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || "头像上传失败");
  }
  bustCache("userIdentity");
  return (await res.json()).avatar_url;
}

/** 清除头像，回到默认占位。 */
export async function clearAvatar(): Promise<void> {
  const res = await fetchWithTimeout(`${getApiUrl()}/user/avatar`, {
    method: "PATCH",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ avatar_url: "" }),
  });
  if (!res.ok) throw new Error("清除头像失败");
  bustCache("userIdentity");
}

/** 设置显示名（空串 = 清除）。名字会写进画像文档，气泡随即生效。 */
export async function updateDisplayName(displayName: string): Promise<string> {
  const res = await fetchWithTimeout(`${getApiUrl()}/user/name`, {
    method: "PATCH",
    headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName }),
  });
  if (!res.ok) throw new Error("保存名字失败");
  bustCache("userIdentity");
  return (await res.json()).display_name;
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
  const res = await fetchWithTimeout(`${getApiUrl()}/system-prompt-preview`, { headers: headers() });
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
  const res = await fetchWithTimeout(`${getApiUrl()}/tool-tiers`, { headers: headers() });
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
  const res = await fetchWithTimeout(`${getApiUrl()}/fast-rules`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}

export async function fetchFastRuleOptions(): Promise<FastRuleOptions> {
  const res = await fetchWithTimeout(`${getApiUrl()}/fast-rules/options`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}

export async function updateFastRules(patch: Partial<FastRules>): Promise<void> {
  await fetchWithTimeout(`${getApiUrl()}/fast-rules`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify(patch),
  });
}

// ── Plugins ─────────────────────────────────────────────────────

export interface PluginField {
  key: string;
  label: string;
  secret: boolean;
  default: string;
  hint: string;
  boolean: boolean;
}

export interface PluginInfo {
  name: string;
  label: string;
  description: string;
  category: "config" | "preset" | "builtin";
  status: "enabled" | "disabled" | "not_installed" | "always";
  fields: PluginField[];
  config_path: string;
  current_values: Record<string, string>;
}

export async function fetchPlugins(): Promise<PluginInfo[]> {
  const res = await fetchWithTimeout(`${getApiUrl()}/plugins`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch plugins");
  const data = await res.json();
  return data.plugins;
}

export async function addPlugin(name: string, values: Record<string, string> = {}): Promise<{ ok: boolean; message: string; restart_required: boolean }> {
  const res = await fetchWithTimeout(`${getApiUrl()}/plugins/${encodeURIComponent(name)}`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ values }),
  });
  if (!res.ok) throw new Error("Failed to add plugin");
  return res.json();
}

export async function removePlugin(name: string): Promise<{ ok: boolean; message: string; restart_required: boolean }> {
  const res = await fetchWithTimeout(`${getApiUrl()}/plugins/${encodeURIComponent(name)}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to remove plugin");
  return res.json();
}

export async function restartServer(): Promise<{ ok: boolean; message: string }> {
  const res = await fetchWithTimeout(`${getApiUrl()}/server/restart`, {
    method: "POST",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to restart server");
  return res.json();
}
