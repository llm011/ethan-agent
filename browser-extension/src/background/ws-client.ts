/* eslint-disable */
// WS client：连接 ethan server 的 /ws/browser，带鉴权握手 + 保活 + 指数退避重连。
//
// MV3 service worker 会被 Chrome 回收，这里三重保活（方案最高风险点 Q3）：
//   1. 每 20s 发 ping；
//   2. chrome.alarms 每 ~25s 唤醒 SW（防回收）；
//   3. 断线指数退避重连，重连后重发 auth 帧。

const PING_INTERVAL_MS = 20_000;
const KEEPALIVE_ALARM = 'ethan-browser-keepalive';
const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;
// 连接需稳定存活这么久，才认为「连成功了」并把退避重置回 base。
// 防止多浏览器实例争抢单连接（server last-wins）时，被驱逐方刚 auth 就以 1s 疯狂重连，
// 形成每秒一次的「驱逐风暴」。存活不足此阈值即断开 → 退避继续指数增长 → 风暴自动收敛。
const STABLE_MS = 5_000;

export interface WsClientConfig {
  serverUrl: string; // 如 ws://localhost:8900/ws/browser
  token: string;
}

type RequestHandler = (message: unknown) => Promise<unknown | null>;

export class BrowserWsClient {
  private ws: WebSocket | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private stableTimer: ReturnType<typeof setTimeout> | null = null;
  private backoff = BASE_BACKOFF_MS;
  private authed = false;
  private stopped = false;

  constructor(
    private getConfig: () => Promise<WsClientConfig | null>,
    private onRequest: RequestHandler,
  ) {}

  /** 弹窗查询用：WS 已打开且鉴权通过。 */
  get isConnected(): boolean {
    return !!this.ws && this.ws.readyState === WebSocket.OPEN && this.authed;
  }

  start(): void {
    this.stopped = false;
    void this.connect();
    // chrome.alarms 兜底唤醒。offscreen document 中也可安全调用。
    // Chrome MV3 最小 alarm 周期为 0.5 分钟（30s），低于此值会被强制调整。
    try {
      chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 0.5 });
    } catch {
      // offscreen 或其他不支持 alarms 的上下文中静默忽略
    }
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    this.ws?.close();
    this.ws = null;
  }

  /** alarm/启动时调用：连接已断则重连。 */
  ensureConnected(): void {
    if (this.stopped) {
      return;
    }
    if (!this.ws || this.ws.readyState === WebSocket.CLOSED) {
      void this.connect();
    }
  }

  private async connect(): Promise<void> {
    this.clearReconnect();
    const cfg = await this.getConfig();
    if (!cfg || !cfg.serverUrl || !cfg.token) {
      console.warn('[EthanBrowser] missing server url/token, configure in options');
      this.scheduleReconnect();
      return;
    }

    let ws: WebSocket;
    try {
      ws = new WebSocket(cfg.serverUrl);
    } catch (e) {
      console.warn('[EthanBrowser] ws construct failed', e);
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    this.authed = false;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'auth', token: cfg.token }));
    };

    ws.onmessage = ev => {
      void this.handleFrame(ev.data);
    };

    ws.onclose = () => {
      this.authed = false;
      this.clearPing();
      this.clearStable();
      if (this.ws === ws) {
        this.ws = null;
      }
      this.scheduleReconnect();
    };

    ws.onerror = () => {
      // onclose 会随后触发，统一在那里重连
      try {
        ws.close();
      } catch {}
    };
  }

  private async handleFrame(raw: unknown): Promise<void> {
    if (typeof raw !== 'string') {
      return;
    }
    let msg: any;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }

    // 鉴权结果
    if (msg.type === 'auth_ok') {
      this.authed = true;
      this.startPing();
      // 不立即重置退避：等连接稳定存活 STABLE_MS 才算「真连上」再重置。
      // 否则多实例争抢时，被驱逐方刚 auth 就把退避清零、1s 疯狂重连 → 驱逐风暴。
      this.clearStable();
      this.stableTimer = setTimeout(() => {
        this.backoff = BASE_BACKOFF_MS;
      }, STABLE_MS);
      return;
    }
    if (msg.type === 'pong') {
      return;
    }

    // JSON-RPC 请求：交给 dispatch，结果回写
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
      }
    }, PING_INTERVAL_MS);
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.reconnectTimer) {
      return;
    }
    const delay = Math.min(this.backoff, MAX_BACKOFF_MS);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect();
    }, delay);
    this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS);
  }

  private clearPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private clearReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private clearStable(): void {
    if (this.stableTimer) {
      clearTimeout(this.stableTimer);
      this.stableTimer = null;
    }
  }

  private clearTimers(): void {
    this.clearPing();
    this.clearReconnect();
    this.clearStable();
  }
}

export { KEEPALIVE_ALARM };
