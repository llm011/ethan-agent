/**
 * 半静默自动更新 hook。
 *
 * 策略：
 * - 应用启动 30s 后首次检查
 * - 之后每 4 小时检查一次
 * - 检测到新版本：后台静默下载，不打扰用户
 * - 下载完成：提示用户“立即重启以安装”，由用户决定何时安装并重启
 * - 任何错误均静默吞掉，绝不打断对话流
 *
 * 非 Tauri 环境（web dev）下所有操作自动降级为 no-op。
 */

import { useEffect, useState, useCallback, useRef } from "react";

// Tauri API 动态导入：避免在 web dev 环境下顶层 import 报错
type UpdaterModule = typeof import("@tauri-apps/plugin-updater");
type ProcessModule = typeof import("@tauri-apps/plugin-process");

let _updaterMod: UpdaterModule | null | undefined;
let _processMod: ProcessModule | null | undefined;

async function loadUpdater(): Promise<UpdaterModule | null> {
  if (_updaterMod !== undefined) return _updaterMod;
  if (typeof window === "undefined" || !(window as any).__TAURI_INTERNALS__) {
    _updaterMod = null;
    return null;
  }
  try {
    _updaterMod = await import("@tauri-apps/plugin-updater");
    return _updaterMod;
  } catch {
    _updaterMod = null;
    return null;
  }
}

async function loadProcess(): Promise<ProcessModule | null> {
  if (_processMod !== undefined) return _processMod;
  if (typeof window === "undefined" || !(window as any).__TAURI_INTERNALS__) {
    _processMod = null;
    return null;
  }
  try {
    _processMod = await import("@tauri-apps/plugin-process");
    return _processMod;
  } catch {
    _processMod = null;
    return null;
  }
}

export type UpdateState = "idle" | "checking" | "downloading" | "ready" | "installing" | "installed" | "error";

export interface UpdateInfo {
  version: string;
  notes: string;
  pubDate: string;
}

export interface UpdaterState {
  state: UpdateState;
  update: UpdateInfo | null;
  error: string | null;
  progress: number; // 0-100，downloading 期间实时更新
}

const INITIAL_STATE: UpdaterState = {
  state: "idle",
  update: null,
  error: null,
  progress: 0,
};

// 模块级单例：多个组件订阅同一个状态，避免重复检查
let currentState: UpdaterState = INITIAL_STATE;
const listeners = new Set<(s: UpdaterState) => void>();
let started = false;
let pendingDownload: any = null;

function setState(next: Partial<UpdaterState>) {
  currentState = { ...currentState, ...next };
  for (const l of listeners) l(currentState);
}

function isAutoUpdateEnabled(): boolean {
  if (typeof window === "undefined") return true;
  return localStorage.getItem("ethan_auto_update_disabled") !== "1";
}

const STARTUP_DELAY_MS = 30_000;
const CHECK_INTERVAL_MS = 4 * 60 * 60_000; // 4 小时

/**
 * 检查并下载更新（如果有）。
 * - 静默执行，错误吞掉只更新 state
 * - 如果已有更新就绪或已安装待重启，跳过
 * - 如果当前正在 checking/downloading，跳过
 */
export async function checkForUpdate(): Promise<void> {
  if (currentState.state === "checking" || currentState.state === "downloading" || currentState.state === "installing") return;
  if (currentState.state === "ready" || currentState.state === "installed") return;

  const mod = await loadUpdater();
  if (!mod) return;

  setState({ state: "checking", error: null, progress: 0 });
  try {
    const update = await mod.check();
    if (!update) {
      pendingDownload = null;
      setState({ state: "idle", update: null });
      return;
    }
    const info: UpdateInfo = {
      version: update.version,
      notes: update.body ?? "",
      pubDate: update.date ?? "",
    };
    setState({ state: "downloading", update: info, progress: 0 });
    pendingDownload = update;
    let total = 0;
    let downloaded = 0;
    await update.download((event: any) => {
      if (event.event === "Started" && event.data.contentLength) {
        total = event.data.contentLength;
      } else if (event.event === "Progress") {
        downloaded += event.data.chunkLength;
        if (total > 0) {
          const pct = Math.min(100, Math.round((downloaded / total) * 100));
          setState({ progress: pct });
        }
      } else if (event.event === "Finished") {
        setState({ progress: 100 });
      }
    });
    setState({ state: "ready", progress: 100 });
  } catch (e: any) {
    pendingDownload = null;
    setState({ state: "error", error: e?.message ?? String(e) });
    setTimeout(() => {
      if (currentState.state === "error") setState({ state: "idle" });
    }, 5000);
  }
}

/** 下载完成后由用户点击触发：先安装已下载更新，再重启应用。 */
export async function installAndRestart(): Promise<void> {
  const proc = await loadProcess();
  if (!proc || !pendingDownload) return;
  try {
    setState({ state: "installing" });
    await pendingDownload.install();
    pendingDownload = null;
    setState({ state: "installed" });
    await proc.relaunch();
  } catch (e: any) {
    setState({ state: "error", error: e?.message ?? String(e) });
    setTimeout(() => {
      if (currentState.state === "error") setState({ state: "ready" });
    }, 5000);
  }
}

/** 关闭提示，不安装本次已下载更新；下次检查会重新发现。 */
export function dismissUpdate(): void {
  pendingDownload = null;
  setState({ state: "idle", update: null, progress: 0, error: null });
}

/** 启动后台自动检查（应用初始化时调用一次）。 */
export function startAutoUpdate(): void {
  if (started) return;
  if (!isAutoUpdateEnabled()) return;
  started = true;
  setTimeout(() => {
    void checkForUpdate();
    setInterval(() => {
      if (!isAutoUpdateEnabled()) return;
      void checkForUpdate();
    }, CHECK_INTERVAL_MS);
  }, STARTUP_DELAY_MS);
}

/** React hook：订阅 updater 状态。 */
export function useUpdater() {
  const [state, setLocalState] = useState<UpdaterState>(currentState);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    const listener = (s: UpdaterState) => {
      if (mountedRef.current) setLocalState(s);
    };
    listeners.add(listener);
    // 首次订阅时立即同步当前状态
    setLocalState(currentState);
    // 应用启动时自动检查（仅一次）
    startAutoUpdate();
    return () => {
      mountedRef.current = false;
      listeners.delete(listener);
    };
  }, []);

  const checkNow = useCallback(() => checkForUpdate(), []);
  const installNow = useCallback(() => installAndRestart(), []);
  const dismiss = useCallback(() => dismissUpdate(), []);

  return { ...state, checkNow, installNow, dismiss };
}
