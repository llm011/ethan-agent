import { readFileSync, writeFileSync } from 'fs';

const p = 'lib/api.ts';
let c = readFileSync(p, 'utf-8');

c = c.replace(
  /export async function fetchSessions\(limit = 50, q\?: string\): Promise<SessionInfo\[\]> \{/,
  'export async function fetchSessions(limit = 50, offset = 0, q?: string): Promise<SessionInfo[]> {'
);

c = c.replace(
  /const params = new URLSearchParams\(\{ limit: String\(limit\) \}\);/,
  'const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });'
);

writeFileSync(p, c);
