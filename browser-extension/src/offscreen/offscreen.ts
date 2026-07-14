/* eslint-disable */
// Offscreen document — 在 MV3 中持久托管 WS 连接。
// 不依赖外部 import，全部内联，避免模块加载问题。

const PING_INTERVAL_MS = 15_000;
const PONG_TIMEOUT_MS = 10_000;  // ping 后 10s 没收到 pong 则认为连接已死
const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;
const STABLE_MS = 5_000;

interface WsClientConfig {
  serverUrl: string;
  token: string;
}

type RequestHandler = (message: unknown) => Promise<unknown | null>;

class BrowserWsClient {
  private ws: WebSocket | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private stableTimer: ReturnType<typeof setTimeout> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;
  private backoff = BASE_BACKOFF_MS;
  private authed = false;
  private stopped = false;
  private connecting = false;

  constructor(
    private getConfig: () => Promise<WsClientConfig | null>,
    private onRequest: RequestHandler,
  ) {}

  get isConnected(): boolean {
    return !!this.ws && this.ws.readyState === WebSocket.OPEN && this.authed;
  }

  start(): void {
    this.stopped = false;
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    this.ws?.close();
    this.ws = null;
  }

  private async connect(): Promise<void> {
    if (this.connecting) return;
    this.connecting = true;
    try {
      await this._doConnect();
    } finally {
      this.connecting = false;
    }
  }

  private async _doConnect(): Promise<void> {
    this.clearReconnect();
    const cfg = await this.getConfig();
    if (this.stopped) return;  // stop() called during await
    console.log('[EthanBrowser:offscreen] connect called, cfg=', cfg ? { url: cfg.serverUrl, hasToken: !!cfg.token } : null);
    if (!cfg || !cfg.serverUrl || !cfg.token) {
      console.warn('[EthanBrowser:offscreen] missing server url/token');
      this.scheduleReconnect();
      return;
    }

    let ws: WebSocket;
    try {
      console.log('[EthanBrowser:offscreen] creating WebSocket to', cfg.serverUrl);
      ws = new WebSocket(cfg.serverUrl);
    } catch (e) {
      console.warn('[EthanBrowser:offscreen] ws construct failed', e);
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    this.authed = false;

    ws.onopen = () => {
      console.log('[EthanBrowser:offscreen] ws opened, sending auth');
      ws.send(JSON.stringify({ type: 'auth', token: cfg.token }));
    };

    ws.onmessage = ev => {
      void this.handleFrame(ev.data);
    };

    ws.onclose = (e) => {
      console.log('[EthanBrowser:offscreen] ws closed', e.code, e.reason);
      this.authed = false;
      this.clearPing();
      this.clearStable();
      this.clearPong();
      if (this.ws === ws) {
        this.ws = null;
      }
      this.scheduleReconnect();
    };

    ws.onerror = (e) => {
      console.warn('[EthanBrowser:offscreen] ws error', e);
      try {
        ws.close();
      } catch {}
    };
  }

  private async handleFrame(raw: unknown): Promise<void> {
    if (typeof raw !== 'string') return;
    let msg: any;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }

    if (msg.type === 'auth_ok') {
      console.log('[EthanBrowser:offscreen] auth ok');
      this.authed = true;
      this.startPing();
      this.clearStable();
      this.stableTimer = setTimeout(() => {
        this.backoff = BASE_BACKOFF_MS;
      }, STABLE_MS);
      return;
    }
    if (msg.type === 'pong') {
      this.clearPong();
      return;
    }

    const response = await this.onRequest(msg);
    if (response && this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(response));
    }
  }

  private startPing(): void {
    this.clearPing();
    this.pingTimer = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
        // 启动 pong 超时检测：超时未收到 pong 则主动重连
        this.clearPong();
        this.pongTimer = setTimeout(() => {
          console.warn('[EthanBrowser:offscreen] pong timeout, force reconnect');
          try { this.ws?.close(); } catch {}
        }, PONG_TIMEOUT_MS);
      }
    }, PING_INTERVAL_MS);
  }

  private clearPong(): void {
    if (this.pongTimer) { clearTimeout(this.pongTimer); this.pongTimer = null; }
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.reconnectTimer) return;
    const delay = Math.min(this.backoff, MAX_BACKOFF_MS);
    console.log('[EthanBrowser:offscreen] schedule reconnect in', delay, 'ms');
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect();
    }, delay);
    this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS);
  }

  private clearPing(): void {
    if (this.pingTimer) { clearInterval(this.pingTimer); this.pingTimer = null; }
  }
  private clearReconnect(): void {
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
  }
  private clearStable(): void {
    if (this.stableTimer) { clearTimeout(this.stableTimer); this.stableTimer = null; }
  }
  private clearTimers(): void {
    this.clearPing();
    this.clearReconnect();
    this.clearStable();
    this.clearPong();
  }
}

// offscreen document 只支持 chrome.runtime API，不支持 chrome.storage。
// 配置由 SW 通过 runtime.sendMessage 推送，或通过初始消息传入。
let cachedConfig: WsClientConfig | null = null;

async function loadConfig(): Promise<WsClientConfig | null> {
  if (cachedConfig) return cachedConfig;
  // 向 SW 请求配置
  try {
    const resp = await chrome.runtime.sendMessage({ target: 'sw', type: 'get_config' });
    if (resp && resp.serverUrl && resp.token) {
      cachedConfig = resp;
      console.log('[EthanBrowser:offscreen] got config from SW:', { url: resp.serverUrl, hasToken: !!resp.token });
      return cachedConfig;
    }
  } catch (e) {
    console.warn('[EthanBrowser:offscreen] get config from SW failed', e);
  }
  return null;
}

async function dispatchToSW(message: unknown): Promise<unknown | null> {
  try {
    const response = await chrome.runtime.sendMessage({ target: 'sw', rpc: message });
    return response ?? null;
  } catch (e) {
    console.warn('[EthanBrowser:offscreen] dispatch to SW failed', e);
    return null;
  }
}

const wsClient = new BrowserWsClient(loadConfig, dispatchToSW);
wsClient.start();

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.target !== 'offscreen') return undefined;
  // SW 推送配置（storage 变化或初始创建时）
  if (msg.type === 'config' && msg.config) {
    const newCfg = msg.config;
    const changed = !cachedConfig
      || cachedConfig.serverUrl !== newCfg.serverUrl
      || cachedConfig.token !== newCfg.token;
    cachedConfig = newCfg;
    console.log('[EthanBrowser:offscreen] config received:', { url: newCfg.serverUrl, hasToken: !!newCfg.token, changed });
    // 只在配置变化时才重连，避免重复重连
    if (changed) {
      wsClient.stop();
      wsClient.start();
    }
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === 'get_status') {
    sendResponse({ connected: wsClient.isConnected });
    return true;
  }
  if (msg.type === 'reconnect') {
    wsClient.stop();
    wsClient.start();
    sendResponse({ ok: true });
    return true;
  }
  return undefined;
});

console.log('[EthanBrowser:offscreen] offscreen document started');
