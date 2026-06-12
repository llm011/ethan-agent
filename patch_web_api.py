with open("web/lib/api.ts", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("""export interface AgentSettings {
  system_prompt: string;
  agent_name: string;
  language: string;
  default_model: string;
}""", """export interface AgentSettings {
  workspace: string;
  system_prompt: string;
  agent_name: string;
  language: string;
  default_model: string;
}""")

content = content.replace("""export interface SystemSettings {
  identity: string;
  soul: string;
}""", """export interface SystemSettings {
  identity: string;
  soul: string;
  format: string;
}""")

provider_api = """
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
"""

content = content.replace("""export interface SystemSettings {""", provider_api + "\nexport interface SystemSettings {")

with open("web/lib/api.ts", "w", encoding="utf-8") as f:
    f.write(content)
