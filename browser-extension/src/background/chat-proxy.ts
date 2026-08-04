/* eslint-disable */
// 通用后台流式对话代理：POST /api/chat（stream SSE），逐块用 chrome.tabs.sendMessage
// 把 delta 推回目标 tab 的 content script。content script 无法跨域 fetch 后端，
// 所有网络请求都由背景代理。
//
// 阅读模式（reading-injector）与结果面板（result-panel）共用这一条通道，
// 区别只在推回消息的 target（uiTarget）：'reading' | 'result'。

import { wsToHttp, readServerConfig } from '../shared';

interface HttpConfig {
  httpBase: string;
  token: string;
}

async function readConfig(): Promise<HttpConfig | null> {
  const cfg = await readServerConfig();
  if (!cfg) return null;
  return { httpBase: wsToHttp(cfg.serverUrl), token: cfg.token };
}

/** 拉取 Ethan 服务端已配置的模型列表（供指令管理页选 model）。 */
export async function fetchModels(): Promise<{ ok: boolean; models?: { id: string; description?: string }[]; error?: string }> {
  const cfg = await readConfig();
  if (!cfg) return { ok: false, error: '未配置 Ethan Server 地址或 Token' };
  try {
    const res = await fetch(`${cfg.httpBase}/api/models`, {
      headers: { Authorization: `Bearer ${cfg.token}` },
    });
    if (!res.ok) return { ok: false, error: `请求失败 (${res.status})` };
    const data = await res.json();
    const models = (data.models || []).map((m: any) => ({ id: m.id, description: m.description || '' }));
    return { ok: true, models };
  } catch (e: any) {
    return { ok: false, error: '连接不上 Ethan 服务' };
  }
}

export interface StreamChatOpts {
  /** 推回消息挂的 target：阅读模式用 'reading'，结果面板用 'result'。默认 'result'。 */
  uiTarget?: string;
  /** 传入走多轮（session_id + btw=false，服务端按 session 拼历史）；不传走单轮 btw=true。 */
  sessionId?: string;
  /** 指令指定的模型（如翻译走小模型）；不传用服务端默认。 */
  model?: string;
  /** 外部传入的取消信号；streamChat 内部也会自建一个，用哪个都能停。 */
  signal?: AbortSignal;
}

/** 正在进行中的流式请求：requestId → {abort}，供扩展侧「停止」按钮中止。 */
const ACTIVE_STREAMS: Map<string, { abort: () => void; tabId: number }> = new Map();

/** 取消某条正在流式的请求（无则静默）。通常由页面结果面板/阅读面板的「停止」按钮触发。 */
export function cancelStream(requestId: string): boolean {
  const entry = ACTIVE_STREAMS.get(requestId);
  if (!entry) return false;
  ACTIVE_STREAMS.delete(requestId);
  try { entry.abort(); } catch {}
  return true;
}

/**
 * 流式 AI：POST /api/chat，逐块把 delta 推回 content script。
 *
 * 推回的消息形如 { target, type, requestId, delta? , error? }：
 *   - chatChunk：{ delta }
 *   - chatDone：{ error? }
 */
export async function streamChat(
  tabId: number,
  requestId: string,
  prompt: string,
  opts: StreamChatOpts = {},
): Promise<void> {
  const uiTarget = opts.uiTarget || 'result';
  const push = (msg: Record<string, unknown>) => {
    chrome.tabs.sendMessage(tabId, { target: uiTarget, ...msg }).catch(() => {});
  };

  const cfg = await readConfig();
  if (!cfg) {
    push({ type: 'chatDone', requestId, error: '未配置 Ethan Server 地址或 Token' });
    return;
  }

  const body: Record<string, unknown> = {
    messages: [{ role: 'user', content: prompt }],
    stream: true,
    channel: 'browser-extension',
  };
  if (opts.model) body.model = opts.model;
  if (opts.sessionId) {
    body.session_id = opts.sessionId;
    body.btw = false;  // 多轮：服务端按 session 拼历史
  } else {
    body.btw = true;   // 单轮：不带历史
  }

  // 取消控制器：外部 signal + 内部 selfAbort 任一触发都会中断底层 fetch。
  const selfAbort = new AbortController();
  const combinedSig = opts.signal
    ? AbortSignal.any([selfAbort.signal, opts.signal])
    : selfAbort.signal;

  const entry = { abort: () => selfAbort.abort(), tabId };
  ACTIVE_STREAMS.set(requestId, entry);
  const cleanup = () => { if (ACTIVE_STREAMS.get(requestId) === entry) ACTIVE_STREAMS.delete(requestId); };

  let res: Response;
  try {
    res = await fetch(`${cfg.httpBase}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${cfg.token}`,
      },
      body: JSON.stringify(body),
      signal: combinedSig,
    });
  } catch (e: any) {
    cleanup();
    if (e?.name === 'AbortError' || combinedSig.aborted) {
      push({ type: 'chatDone', requestId, error: '已取消' });
    } else {
      push({ type: 'chatDone', requestId, error: '连接不上 Ethan 服务，请确认后端已启动' });
    }
    return;
  }

  if (!res.ok || !res.body) {
    cleanup();
    push({ type: 'chatDone', requestId, error: `请求失败 (${res.status})` });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let sawDone = false;
  let aborted = false;

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
    if (e?.name === 'AbortError' || combinedSig.aborted) {
      aborted = true;
      push({ type: 'chatDone', requestId, error: '已取消' });
    } else {
      push({ type: 'chatDone', requestId, error: String(e?.message || e) });
    }
  } finally {
    cleanup();
    // 稳妥：万一 reader 没释放，显式取消一下 reader
    try { if (!aborted) void reader.cancel(); } catch {}
  }
}
