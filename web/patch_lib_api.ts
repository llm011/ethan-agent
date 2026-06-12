import * as fs from 'fs';

const path = 'lib/api.ts';
let content = fs.readFileSync(path, 'utf8');

const newCode = `
export interface SkillInfo {
  name: string;
  description: string;
  trigger: string[];
  content: string;
}

export async function fetchSkills(): Promise<SkillInfo[]> {
  const res = await fetch(\`\${API_URL}/skills\`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch skills");
  return res.json().then(data => data.skills);
}

export async function fetchSkill(name: string): Promise<SkillInfo> {
  const res = await fetch(\`\${API_URL}/skills/\${encodeURIComponent(name)}\`, { headers: headers() });
  if (!res.ok) throw new Error("Skill not found");
  return res.json();
}

export async function saveSkill(skill: SkillInfo): Promise<{ name: string }> {
  const res = await fetch(\`\${API_URL}/skills\`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(skill)
  });
  if (!res.ok) throw new Error("Failed to save skill");
  return res.json();
}
`;

if (!content.includes('fetchSkills')) {
  content += '\n' + newCode;
  fs.writeFileSync(path, content);
  console.log('Patched lib/api.ts');
} else {
  console.log('Already patched lib/api.ts');
}
