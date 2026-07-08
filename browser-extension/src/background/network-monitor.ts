// Network 监听器：每个 session 对应一个监听实例，用 CDP Network 域捕获请求/响应。
import type {
  BrowserNetworkEntry,
  BrowserNetworkListResult,
  BrowserNetworkDetailResult,
  BrowserNetworkStartResult,
  BrowserNetworkStopResult,
} from '../shared';
import { addCdpEventListener, removeCdpEventListeners, withCdpClient } from './cdp-client';
import type { BrowserSessionStore } from './session-store';

// 每个 session 最多保留的请求数（防止内存无限增长）
const MAX_ENTRIES_PER_SESSION = 500;

export class NetworkMonitor {
  // sessionId -> requestId -> entry
  private readonly sessions = new Map<string, Map<string, BrowserNetworkEntry>>();

  constructor(private readonly sessionStore: BrowserSessionStore) {}

  async start(params: { sessionId: string }): Promise<BrowserNetworkStartResult> {
    const { sessionId } = params;
    if (this.sessions.has(sessionId)) {
      // 幂等：已在监听，直接返回
      return { ok: true, sessionId };
    }

    const activeTab = await this.sessionStore.getActiveTab({ sessionId });
    const tabId = activeTab.tab.tabId;
    const entries = new Map<string, BrowserNetworkEntry>();
    this.sessions.set(sessionId, entries);

    await withCdpClient(tabId, async client => {
      await client.send('Network.enable');
    });

    // requestWillBeSent
    addCdpEventListener(tabId, 'Network.requestWillBeSent', raw => {
      const e = raw as {
        requestId: string;
        request: { url: string; method: string; headers?: Record<string, string>; postData?: string };
        type?: string;
        timestamp?: number;
      };
      if (!this.sessions.has(sessionId)) return;
      if (entries.size >= MAX_ENTRIES_PER_SESSION) {
        // 删最旧的
        const oldest = entries.keys().next().value;
        if (oldest) entries.delete(oldest);
      }
      entries.set(e.requestId, {
        requestId: e.requestId,
        url: e.request.url,
        method: e.request.method,
        resourceType: e.type,
        requestTime: e.timestamp,
        requestHeaders: e.request.headers,
        ...(e.request.postData ? { postData: e.request.postData } : {}),
      });
    });

    // responseReceived
    addCdpEventListener(tabId, 'Network.responseReceived', raw => {
      const e = raw as {
        requestId: string;
        response: { status: number; mimeType?: string; headers?: Record<string, string> };
        timestamp?: number;
      };
      const entry = entries.get(e.requestId);
      if (!entry) return;
      entry.status = e.response.status;
      entry.mimeType = e.response.mimeType;
      entry.responseTime = e.timestamp;
      entry.responseHeaders = e.response.headers;
    });

    // loadingFinished
    addCdpEventListener(tabId, 'Network.loadingFinished', raw => {
      const e = raw as { requestId: string; encodedDataLength?: number };
      const entry = entries.get(e.requestId);
      if (!entry) return;
      entry.encodedDataLength = e.encodedDataLength;
    });

    // loadingFailed
    addCdpEventListener(tabId, 'Network.loadingFailed', raw => {
      const e = raw as { requestId: string; errorText?: string };
      const entry = entries.get(e.requestId);
      if (!entry) return;
      entry.failed = true;
      entry.errorText = e.errorText;
    });

    return { ok: true, sessionId };
  }

  async stop(params: { sessionId: string }): Promise<BrowserNetworkStopResult> {
    const { sessionId } = params;
    const entries = this.sessions.get(sessionId);
    const count = entries?.size ?? 0;
    this.sessions.delete(sessionId);

    try {
      const activeTab = await this.sessionStore.getActiveTab({ sessionId });
      removeCdpEventListeners(activeTab.tab.tabId, 'Network.requestWillBeSent');
      removeCdpEventListeners(activeTab.tab.tabId, 'Network.responseReceived');
      removeCdpEventListeners(activeTab.tab.tabId, 'Network.loadingFinished');
      removeCdpEventListeners(activeTab.tab.tabId, 'Network.loadingFailed');
      await withCdpClient(activeTab.tab.tabId, async client => {
        await client.send('Network.disable');
      });
    } catch {
      // tab 可能已关闭，忽略
    }

    return { ok: true, sessionId, count };
  }

  list(params: { sessionId: string; filter?: string }): Promise<BrowserNetworkListResult> {
    const { sessionId, filter } = params;
    const entries = this.sessions.get(sessionId);
    if (!entries) {
      return Promise.resolve({ ok: true, sessionId, requests: [] });
    }
    let list = Array.from(entries.values()).map(({ responseBody: _rb, postData: _pd, ...rest }) => rest);
    if (filter) {
      const f = filter.toLowerCase();
      list = list.filter(e => e.url.toLowerCase().includes(f) || (e.resourceType || '').toLowerCase().includes(f));
    }
    return Promise.resolve({ ok: true, sessionId, requests: list });
  }

  async detail(params: { sessionId: string; requestId: string }): Promise<BrowserNetworkDetailResult> {
    const { sessionId, requestId } = params;
    const entries = this.sessions.get(sessionId);
    const entry = entries?.get(requestId);
    if (!entry) {
      return { ok: true, sessionId, request: null };
    }

    // 如果没有 responseBody，尝试通过 CDP 拉取
    if (entry.responseBody === undefined && !entry.failed) {
      try {
        const activeTab = await this.sessionStore.getActiveTab({ sessionId });
        const body = await withCdpClient(activeTab.tab.tabId, client =>
          client.send<{ body: string; base64Encoded: boolean }>('Network.getResponseBody', { requestId }),
        );
        entry.responseBody = body.base64Encoded
          ? `[base64] ${body.body.slice(0, 2000)}`
          : body.body.slice(0, 10000);
      } catch {
        entry.responseBody = '[unavailable]';
      }
    }

    return { ok: true, sessionId, request: { ...entry } };
  }
}
