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

export interface StreamChatOpts {
  /** 推回消息挂的 target：阅读模式用 'reading'，结果面板用 'result'。默认 'result'。 */
  uiTarget?: string;
  /** 传入走多轮（session_id + btw=false，服务端按 session 拼历史）；不传走单轮 btw=true。 */
  sessionId?: string;
  /** 指令指定的模型（如翻译走小模型）；不传用服务端默认。 */
  model?: string;
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

  let res: Response;
  try {
    res = await fetch(`${cfg.httpBase}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${cfg.token}`,
      },
      body: JSON.stringify(body),
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
