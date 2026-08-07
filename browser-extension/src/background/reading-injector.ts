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

/** 触发目标页进入阅读模式（content script 收到后自行渲染面板）。
 * 对飞书文档页：background 先抓全文 Markdown（带缓存），再把 presetMarkdown 传给阅读模式，
 * 直接渲染全文，绕开虚拟滚动 DOM 拿不全的问题。 */
export async function startReading(tabId: number, opts?: { nocache?: boolean }): Promise<{ ok: boolean; error?: string }> {
  const ok = await ensureReadingInjected(tabId);
  if (!ok) return { ok: false, error: 'inject_failed' };
  try {
    const tab = await chrome.tabs.get(tabId);
    const url = tab?.url || '';
    console.log('[EthanBrowser] reading:start tab url =', url);
    let payload: any = { target: 'reading', type: 'start' };
    // 飞书文档直接走 server 拉全文 Markdown（带 24h 浏览器缓存 + skill 自身磁盘缓存）
    const feishu = url ? await fetchFeishuDocMarkdown(tabId, url, opts) : null;
    if (feishu) {
      console.log('[EthanBrowser] reading:start using feishu API markdown, title=', feishu.title);
      payload.presetMarkdown = feishu.markdown;
      payload.presetTitle = feishu.title;
    } else if (url) {
      console.log('[EthanBrowser] reading:start feishu fetch returned null, falling back to DOM');
    }
    console.log('[EthanBrowser] reading:start sendMessage to tab', tabId);
    await chrome.tabs.sendMessage(tabId, payload);
    return { ok: true };
  } catch (e: any) {
    console.warn('[EthanBrowser] reading:start error', e);
    return { ok: false, error: String(e?.message || e) };
  }
}

/**
 * 阅读模式的流式 AI：薄封装 streamChat，推回 target='reading'。
 *
 * opts.sessionId 传入时走多轮对话（服务端按 session 拼历史），不传走单轮（一次性摘要）。
 * 单轮默认走 direct 模式（跳过 agent loop，纯 LLM 输出，更快）。
 * 多轮也走 direct（摘要 + 对文章提问都是正文相关，不需要工具；同时让服务端把问答对也落库到 session）。
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
    direct: true,
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

// ── 飞书文档全文获取（绕开网页 DOM 的虚拟滚动）────────────────────────────

const FEISHU_DOC_CACHE_KEY = 'feishu_doc_cache_v1';
const FEISHU_DOC_CACHE_MAX_AGE_MS = 24 * 3600 * 1000;

interface FeishuDocCacheEntry {
  markdown: string;
  title: string;
  url: string;
  length: number;
  fetchedAt: number;
}

const FEISHU_HOST_SUFFIXES = ['feishu.cn', 'larksuite.com', 'feishu.net', 'larkoffice.com'];

function isFeishuDocUrl(url: string): boolean {
  if (!url) return false;
  try {
    const u = new URL(url);
    const host = u.hostname.toLowerCase();
    if (!FEISHU_HOST_SUFFIXES.some(s => host.endsWith(s))) {
      return false;
    }
    const parts = u.pathname.split('/').filter(Boolean);
    if (!parts.length) return false;
    const prefix = parts[0].toLowerCase();
    // 仅处理云文档，忽略多维表格 / 表格（虚拟滚动且非纯文档）
    return ['docx', 'wiki', 'doc', 'docs'].includes(prefix);
  } catch {
    return false;
  }
}

async function readFeishuDocCache(url: string): Promise<FeishuDocCacheEntry | null> {
  try {
    const all = await chrome.storage.local.get([FEISHU_DOC_CACHE_KEY]);
    const map: Record<string, FeishuDocCacheEntry> = all[FEISHU_DOC_CACHE_KEY] || {};
    const e = map[url];
    if (!e) return null;
    if (Date.now() - (e.fetchedAt || 0) > FEISHU_DOC_CACHE_MAX_AGE_MS) return null;
    return e;
  } catch {
    return null;
  }
}

async function writeFeishuDocCache(url: string, entry: FeishuDocCacheEntry): Promise<void> {
  try {
    const all = await chrome.storage.local.get([FEISHU_DOC_CACHE_KEY]);
    const map: Record<string, FeishuDocCacheEntry> = all[FEISHU_DOC_CACHE_KEY] || {};
    map[url] = entry;
    // 清理超龄项，避免 storage 无限涨
    for (const k of Object.keys(map)) {
      if (Date.now() - (map[k].fetchedAt || 0) > FEISHU_DOC_CACHE_MAX_AGE_MS) {
        delete map[k];
      }
    }
    await chrome.storage.local.set({ [FEISHU_DOC_CACHE_KEY]: map });
  } catch {
    /* ignore */
  }
}

export async function invalidateFeishuDocCache(url: string): Promise<void> {
  try {
    const all = await chrome.storage.local.get([FEISHU_DOC_CACHE_KEY]);
    const map: Record<string, FeishuDocCacheEntry> = all[FEISHU_DOC_CACHE_KEY] || {};
    delete map[url];
    await chrome.storage.local.set({ [FEISHU_DOC_CACHE_KEY]: map });
  } catch { /* ignore */ }
}

/** 通过本地 server 抓飞书文档全文 Markdown（带浏览器缓存 24h，server 端也自带缓存）。
 * 失败返回 null（调用方退回 DOM 抽取方案）。 */
export async function fetchFeishuDocMarkdown(
  tabId: number,
  url: string,
  opts?: { nocache?: boolean },
): Promise<{ markdown: string; title: string; url: string; length: number } | null> {
  if (!isFeishuDocUrl(url)) {
    console.log('[EthanBrowser] feishu-doc: URL not recognized as feishu doc:', url);
    return null;
  }
  console.log('[EthanBrowser] feishu-doc: detected feishu doc URL, fetching via API:', url);

  // 先查浏览器 storage 的缓存，避免即使有 /tmp 缓存仍要走 HTTP 往返
  if (!opts?.nocache) {
    const cached = await readFeishuDocCache(url);
    if (cached) {
      console.log('[EthanBrowser] feishu-doc: hit browser cache');
      return { markdown: cached.markdown, title: cached.title, url: cached.url, length: cached.length };
    }
  }

  const cfg = await readConfig();
  if (!cfg) {
    console.warn('[EthanBrowser] feishu-doc: no server config (serverUrl/token missing), fallback to DOM');
    return null;
  }
  try {
    const apiUrl = `${cfg.httpBase}/api/feishu-doc/fetch`;
    console.log('[EthanBrowser] feishu-doc: calling', apiUrl);
    const res = await fetch(apiUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${cfg.token}` },
      body: JSON.stringify({ url, nocache: !!opts?.nocache, renderer: 'chrome' }),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      console.warn('[EthanBrowser] feishu-doc: API returned', res.status, text.slice(0, 200));
      return null;
    }
    const data = await res.json();
    if (!data?.ok || !data.markdown) {
      console.warn('[EthanBrowser] feishu-doc: API response not ok or empty markdown', JSON.stringify({ ok: data?.ok, error: data?.error, length: data?.length }).slice(0, 300));
      return null;
    }
    console.log('[EthanBrowser] feishu-doc: success, length=', data.length);
    const entry: FeishuDocCacheEntry = {
      markdown: String(data.markdown),
      title: String(data.title || documentTitleFor(url)),
      url: String(data.url || url),
      length: Number(data.length || 0),
      fetchedAt: Date.now(),
    };
    await writeFeishuDocCache(url, entry);
    return { markdown: entry.markdown, title: entry.title, url: entry.url, length: entry.length };
  } catch (e: any) {
    console.warn('[EthanBrowser] feishu-doc: fetch error', e?.message || e);
    return null;
  }
}

function documentTitleFor(_url: string): string {
  return '';
}
