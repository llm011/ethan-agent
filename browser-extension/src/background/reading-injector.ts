/* eslint-disable */
// 辅助阅读模式的背景侧支持：
//   1. 把 content/reading-mode.js 注入目标 tab
//   2. 转发 AI 请求到 /api/chat（流式 SSE），逐块推回 content script
//   3. 标注 CRUD 转发到 /api/reading
//   4. 存知识库转发到 /api/knowledge
//
// content script 无法跨域 fetch 后端，所有网络请求都由背景代理。
// 流式回传：background fetch SSE → 逐 data 块用 chrome.tabs.sendMessage 推回 tab。

interface ServerConfig {
  httpBase: string;
  token: string;
}

/** 把 ws://host/ws/browser 转成 http://host（与 context-menu 一致）。 */
function wsToHttp(wsUrl: string): string {
  return wsUrl
    .replace(/^wss:/, 'https:')
    .replace(/^ws:/, 'http:')
    .replace(/\/ws\/browser\/?$/, '');
}

async function readConfig(): Promise<ServerConfig | null> {
  const { serverUrl, token } = await chrome.storage.local.get(['serverUrl', 'token']);
  if (!serverUrl || !token) return null;
  return { httpBase: wsToHttp(serverUrl), token };
}

const injectedTabs = new Set<number>();

chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.status === 'loading' && injectedTabs.has(tabId)) {
    injectedTabs.delete(tabId);
  }
});
chrome.tabs.onRemoved.addListener(tabId => {
  injectedTabs.delete(tabId);
});

/** 注入 reading-mode content script（每 tab 一次）。 */
export async function ensureReadingInjected(tabId: number): Promise<boolean> {
  if (injectedTabs.has(tabId)) return true;
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['content/reading-mode.js'],
    });
    injectedTabs.add(tabId);
    return true;
  } catch {
    return false;
  }
}

/** 触发目标页进入阅读模式（content script 收到后自行渲染面板）。 */
export async function startReading(tabId: number): Promise<{ ok: boolean; error?: string }> {
  const ok = await ensureReadingInjected(tabId);
  if (!ok) return { ok: false, error: 'inject_failed' };
  try {
    await chrome.tabs.sendMessage(tabId, { target: 'reading', type: 'start' });
    return { ok: true };
  } catch (e: any) {
    return { ok: false, error: String(e?.message || e) };
  }
}

/** 流式 AI：POST /api/chat（stream+btw），逐块把 delta 推回 content script。 */
export async function readingChat(
  tabId: number,
  requestId: string,
  prompt: string,
): Promise<void> {
  const push = (msg: Record<string, unknown>) => {
    chrome.tabs.sendMessage(tabId, { target: 'reading', ...msg }).catch(() => {});
  };

  const cfg = await readConfig();
  if (!cfg) {
    push({ type: 'chatDone', requestId, error: '未配置 Ethan Server 地址或 Token' });
    return;
  }

  let res: Response;
  try {
    res = await fetch(`${cfg.httpBase}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${cfg.token}`,
      },
      body: JSON.stringify({
        messages: [{ role: 'user', content: prompt }],
        stream: true,
        btw: true,
        channel: 'browser-extension',
      }),
    });
  } catch (e: any) {
    push({ type: 'chatDone', requestId, error: '连接不上 Ethan 服务，请确认后端已启动' });
    return;
  }

  if (!res.ok || !res.body) {
    push({ type: 'chatDone', requestId, error: `请求失败 (${res.status})` });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let sawDone = false;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let chunk: any;
        try {
          chunk = JSON.parse(line.slice(6));
        } catch {
          continue;
        }
        if (chunk.error) {
          push({ type: 'chatDone', requestId, error: String(chunk.error) });
          sawDone = true;
          continue;
        }
        if (typeof chunk.content === 'string' && chunk.content) {
          push({ type: 'chatChunk', requestId, delta: chunk.content });
        }
        if (chunk.done) {
          sawDone = true;
          push({ type: 'chatDone', requestId });
        }
      }
    }
    if (!sawDone) push({ type: 'chatDone', requestId });
  } catch (e: any) {
    push({ type: 'chatDone', requestId, error: String(e?.message || e) });
  }
}

/** 取某 URL 下全部标注。 */
export async function readingListAnnotations(url: string): Promise<any[]> {
  const cfg = await readConfig();
  if (!cfg) return [];
  try {
    const res = await fetch(
      `${cfg.httpBase}/api/reading/annotations?url=${encodeURIComponent(url)}`,
      { headers: { Authorization: `Bearer ${cfg.token}` } },
    );
    if (!res.ok) return [];
    return (await res.json()).annotations || [];
  } catch {
    return [];
  }
}

/** 新建标注，返回后端分配的 id。 */
export async function readingCreateAnnotation(payload: Record<string, unknown>): Promise<number | null> {
  const cfg = await readConfig();
  if (!cfg) return null;
  try {
    const res = await fetch(`${cfg.httpBase}/api/reading/annotations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${cfg.token}` },
      body: JSON.stringify(payload),
    });
    if (!res.ok) return null;
    return (await res.json()).id ?? null;
  } catch {
    return null;
  }
}

/** 删除标注。 */
export async function readingDeleteAnnotation(url: string, id: number): Promise<boolean> {
  const cfg = await readConfig();
  if (!cfg) return false;
  try {
    const res = await fetch(`${cfg.httpBase}/api/reading/annotations`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${cfg.token}` },
      body: JSON.stringify({ url, id }),
    });
    if (!res.ok) return false;
    return !!(await res.json()).ok;
  } catch {
    return false;
  }
}

/** 存知识库：把改写后的 Markdown 写入 /api/knowledge。 */
export async function readingSaveKnowledge(
  title: string,
  content: string,
  tags?: string[],
): Promise<{ ok: boolean; error?: string }> {
  const cfg = await readConfig();
  if (!cfg) return { ok: false, error: '未配置 Server' };
  try {
    const res = await fetch(`${cfg.httpBase}/api/knowledge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${cfg.token}` },
      body: JSON.stringify({ title, content, tags: tags ?? null }),
    });
    if (!res.ok) return { ok: false, error: `保存失败 (${res.status})` };
    return { ok: true };
  } catch (e: any) {
    return { ok: false, error: String(e?.message || e) };
  }
}
