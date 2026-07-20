"use client";
/* 本地服务存活检测 hook：单例轮询 /api/health，多组件共享一次轮询。
 *
 * 设计要点：
 * - 模块级 singleton state + 订阅列表，多个组件用同一个 useServerHealth() 时只起一个定时器
 * - 轮询周期 12s（轻量，/health 无 DB 访问，几ms 就返回）
 * - fetch 超时 3s（后端挂了不会卡住前端）
 * - 页面重新可见时立即检测一次（用户切回桌面端不用等下个周期）
 * - API_URL 在 fetch 时实时读取，响应 Settings 中修改 API URL
 */
import { useEffect, useState } from "react";
import { API_URL } from "./api-base";

export type ServerStatus = "ok" | "down" | "checking";

export interface ServerHealth {
  status: ServerStatus;
  version: string | null;
  latencyMs: number | null;
  lastCheck: number | null; // Date.now() 时间戳（ms）
}

const POLL_INTERVAL_MS = 12_000;
const FETCH_TIMEOUT_MS = 3_000;

// 模块级 singleton：所有组件共享一份状态和一次轮询
let _state: ServerHealth = {
  status: "checking",
  version: null,
  latencyMs: null,
  lastCheck: null,
};
const _subscribers = new Set<() => void>();
let _pollingStarted = false;
let _pollTimer: ReturnType<typeof setInterval> | null = null;

async function checkOnce(): Promise<void> {
  const t0 =
    typeof performance !== "undefined" ? performance.now() : Date.now();
  try {
    const ctrl = new AbortController();
    const to = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
    const res = await fetch(`${API_URL}/health`, {
      signal: ctrl.signal,
      headers: { "Cache-Control": "no-cache" },
    });
    clearTimeout(to);
    const latency = Math.round(
      (typeof performance !== "undefined" ? performance.now() : Date.now()) - t0
    );
    if (res.ok) {
      const data = await res.json();
      _state = {
        status: "ok",
        version: data.version ?? null,
        latencyMs: latency,
        lastCheck: Date.now(),
      };
    } else {
      _state = {
        status: "down",
        version: null,
        latencyMs: null,
        lastCheck: Date.now(),
      };
    }
  } catch {
    _state = {
      status: "down",
      version: null,
      latencyMs: null,
      lastCheck: Date.now(),
    };
  }
  _subscribers.forEach((fn) => fn());
}

function startPolling(): void {
  if (_pollingStarted) return;
  _pollingStarted = true;
  // 立即检测一次（首次挂载时不用等 12s 才有状态）
  void checkOnce();
  _pollTimer = setInterval(() => void checkOnce(), POLL_INTERVAL_MS);
  // 页面重新可见时立即检测：用户切走再切回，不用等下个周期才知道状态
  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) void checkOnce();
    });
  }
}

/**
 * 订阅本地服务存活状态。多个组件共享一次轮询。
 * 返回 { status, version, latencyMs, lastCheck }。
 */
export function useServerHealth(): ServerHealth {
  const [, setTick] = useState(0);
  useEffect(() => {
    const fn = () => setTick((t) => t + 1);
    _subscribers.add(fn);
    startPolling();
    return () => {
      _subscribers.delete(fn);
    };
  }, []);
  return _state;
}
