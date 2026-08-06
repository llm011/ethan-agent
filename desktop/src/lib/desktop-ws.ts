/**
 * Desktop WebSocket client — 桌面端与 server 的常驻长连接。
 * 接收 server 推送的 JSON-RPC 通知（countdown 指令、桌面通知等）。
 */
import { invoke } from "@tauri-apps/api/core";
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";
import { getServerUrl, getAuthToken } from "./api-base";

type MessageHandler = (method: string, params: Record<string, unknown>) => void;

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let handlers: MessageHandler[] = [];

function getWsUrl(): string {
  const base = getServerUrl().replace(/^http/, "ws");
  return `${base}/ws/desktop`;
}

function connect() {
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
    return;
  }

  const token = getAuthToken();
  if (!token) {
    console.warn("[DesktopWS] no auth token, retrying later...");
    scheduleReconnect();
    return;
  }

  const url = getWsUrl();
  console.log("[DesktopWS] connecting to", url);
  const sock = new WebSocket(url);
  ws = sock;

  sock.onopen = () => {
    sock.send(JSON.stringify({ type: "auth", token, name: "desktop" }));
  };

  sock.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "auth_ok") {
        console.log("[DesktopWS] connected as", msg.name);
        return;
      }
      if (msg.type === "pong") return;
      // JSON-RPC notification (no id) or request (has id)
      if (msg.method) {
        dispatch(msg.method, msg.params || {});
        // If it has an id, respond with ack
        if (msg.id != null) {
          sock.send(JSON.stringify({ id: msg.id, result: "ok" }));
        }
      }
    } catch {
      // ignore parse errors
    }
  };

  sock.onclose = (ev) => {
    console.warn("[DesktopWS] closed, code:", ev.code, ev.reason);
    if (ws === sock) {
      ws = null;
      scheduleReconnect();
    }
  };

  sock.onerror = () => {
    sock.close();
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, 5000);
}

function keepAlive() {
  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "ping" }));
    }
  }, 30000);
}

function dispatch(method: string, params: Record<string, unknown>) {
  for (const h of handlers) {
    try {
      h(method, params);
    } catch (e) {
      console.error("[DesktopWS] handler error:", e);
    }
  }
}

// ─── Built-in handlers ───────────────────────────────────────

async function handleCountdown(params: Record<string, unknown>) {
  const action = params.action as string;
  switch (action) {
    case "start":
      try {
        await invoke("open_countdown_window_cmd");
      } catch { /* already open */ }
      // Send event to countdown window via localStorage (cross-window communication)
      localStorage.setItem(
        "countdown_command",
        JSON.stringify({ action: "start", minutes: params.minutes || 25, ts: Date.now() })
      );
      break;
    case "pause":
    case "resume":
    case "reset":
      localStorage.setItem("countdown_command", JSON.stringify({ action, ts: Date.now() }));
      break;
    case "close":
      try {
        await invoke("close_countdown_window");
      } catch { /* window might not exist */ }
      break;
  }
}

async function handleNotification(params: Record<string, unknown>) {
  const title = (params.title as string) || "Ethan";
  const body = (params.body as string) || "";
  let granted = await isPermissionGranted();
  if (!granted) {
    const permission = await requestPermission();
    granted = permission === "granted";
  }
  if (granted) {
    sendNotification({ title, body });
  }
}

// ─── Public API ──────────────────────────────────────────────

export function addHandler(handler: MessageHandler) {
  handlers.push(handler);
}

export function removeHandler(handler: MessageHandler) {
  handlers = handlers.filter((h) => h !== handler);
}

export function reconnectDesktopWebSocket() {
  if (ws) {
    ws.close();
    ws = null;
  }
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  connect();
}

export function initDesktopWebSocket() {
  // Register built-in handlers
  addHandler((method, params) => {
    if (method === "countdown") handleCountdown(params);
    else if (method === "notification") handleNotification(params);
  });
  connect();
  keepAlive();
}
