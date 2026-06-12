import re

with open('../web/lib/api.ts', 'r') as f:
    content = f.read()

system_api = '''
export interface SystemSettings {
  identity: string;
  soul: string;
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
'''

pattern = re.compile(r'export async function updateAgentSettings\(patch: Partial<AgentSettings>\): Promise<void> \{\n  await fetch\(`\$\{API_URL\}/settings/agent`, \{\n    method: "PATCH",\n    headers: headers\(\),\n    body: JSON.stringify\(patch\),\n  \}\);\n\}')
if pattern.search(content):
    content = content[:pattern.search(content).end()] + '\n\n' + system_api + content[pattern.search(content).end():]
    with open('../web/lib/api.ts', 'w') as f:
        f.write(content)
    print("Web API patched")
else:
    print("Could not find insertion point for web API")
