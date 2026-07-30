/* eslint-disable */
// 辅助阅读模式的背景侧支持：
//   1. 把 content/reading-mode.js 注入目标 tab
//   2. 转发 AI 请求到 /api/chat（流式 SSE），逐块推回 content script
//   3. 标注 CRUD 转发到 /api/reading
//   4. 存知识库转发到 /api/knowledge
//
// content script 无法跨域 fetch 后端，所有网络请求都由背景代理。
// 流式回传：background fetch SSE → 逐 data 块用 chrome.tabs.sendMessage 推回 tab。

import { wsToHttp, readServerConfig } from '../shared';
import { streamChat } from './chat-proxy';

interface HttpConfig {
  httpBase: string;
  token: string;
}

async function readConfig(): Promise<HttpConfig | null> {
  const cfg = await readServerConfig();
  if (!cfg) return null;
  return { httpBase: wsToHttp(cfg.serverUrl), token: cfg.token };
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
    // reading-mode 依赖 window.__ethanReader（detectArticle/cleanArticle/htmlToMarkdown），
    // 先注入共享正文提取脚本，再注入阅读模式脚本。
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['content/reader-extract.js', 'content/reading-mode.js'],
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

/**
 * 阅读模式的流式 AI：薄封装 streamChat，推回 target='reading'。
 *
 * opts.sessionId 传入时走多轮对话（服务端按 session 拼历史），不传走单轮（摘要）。
 */
export async function readingChat(
  tabId: number,
  requestId: string,
  prompt: string,
  opts: { sessionId?: string } = {},
): Promise<void> {
  await streamChat(tabId, requestId, prompt, {
    uiTarget: 'reading',
    sessionId: opts.sessionId,
  });
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
