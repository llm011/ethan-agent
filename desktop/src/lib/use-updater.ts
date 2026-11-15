/**
 * 半静默自动更新 hook。
 *
 * 策略：
 * - 应用启动 5s 后首次检查
 * - 之后每 1 小时检查一次
 * - 检测到新版本：后台静默下载，不打扰用户
 * - 下载完成：提示用户"立即重启以安装"，由用户决定何时安装并重启
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
  /** 最近一次检查的时间戳（ms）。用来给「已是最新」反馈做 30 秒自动隐藏。 */
  checkedAt?: number;
  /** 本次检查明确得出「没有更新」。之前这里是静默的，用户会以为按钮坏了。 */
  upToDate?: boolean;
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

const STARTUP_DELAY_MS = 5_000;
const CHECK_INTERVAL_MS = 60 * 60_000; // 1 小时
// 状态允许停留的最长时间。超过就认为卡死（下载挂起 / 回调丢失），允许重置。
const STUCK_STATE_MS = 6 * 60_000;

/**
 * 检查并下载更新（如果有）。
 * - 静默执行，错误吞掉只更新 state
 * - 如果已有更新就绪或已安装待重启，跳过
 * - 如果当前正在 checking/downloading，跳过
 */
/** 读取当前安装版本（Tauri 的 app.getVersion）。拿不到就返回 unknown。 */
async function getCurrentVersion(): Promise<string> {
  try {
    const { getVersion } = await import("@tauri-apps/api/app");
    return await getVersion();
  } catch {
    return "unknown";
  }
}

export async function checkForUpdate(): Promise<void> {
  // `ready` / `installed` 是「已经下好了，等用户重启」，这时再检查没有意义。
  if (currentState.state === "ready" || currentState.state === "installed") return;

  // 但 `checking` / `downloading` / `installing` 不该无条件拦截——
  // 一旦某次下载挂起，状态会卡在 downloading，之后所有检查都静默 return，
  // 用户看到的就是「点检查没反应」。这里加时间闸：超过 6 分钟视为僵尸状态，强行重置。
  if (
    currentState.state === "checking" ||
    currentState.state === "downloading" ||
    currentState.state === "installing"
  ) {
    const stuck = Date.now() - (currentState.checkedAt ?? 0);
    if (stuck < STUCK_STATE_MS) {
      // 确实是「刚发起，还在进行中」——安静返回，不打扰
      return;
    }
    console.warn(
      `[updater] 检测到状态卡在 ${currentState.state} 已 ${Math.round(stuck / 1000)}s，强制重置后重试`,
    );
    setState({ state: "idle", error: null, progress: 0 });
  }

  const mod = await loadUpdater();
  if (!mod) {
    // 非 Tauri 环境（web dev）或插件没装 —— 明确告诉用户为什么点不动
    console.warn("[updater] 当前环境不支持自动更新（不在 Tauri 内或插件缺失）");
    setState({ state: "error", error: "当前环境不支持自动更新" });
    return;
  }

  setState({ state: "checking", error: null, progress: 0, checkedAt: Date.now(), upToDate: false });
  try {
    // 打印检查结果，方便用户/我们判断「为什么没检测到」：
    //   · 返回 null        → 真的没有更新（或版本号相等/更旧）
    //   · 抛异常           → 网络/签名/latest.json 解析问题，见 catch
    const current = await getCurrentVersion();
    console.log(`[updater] 检查更新，当前版本 ${current}`);
    const update = await mod.check();
    if (!update) {
      console.log(`[updater] 没有可用更新（当前 ${current}）`);
      pendingDownload = null;
      // 之前这里静默回到 idle，用户完全不知道检查发生过。
      // 现在带上「已是最新」的可见反馈，避免「点了没反应」的错觉。
      setState({ state: "idle", update: null, checkedAt: Date.now(), upToDate: true });
      return;
    }
    console.log(`[updater] 发现新版本 ${current} → ${update.version}`);
    const info: UpdateInfo = {
      version: update.version,
      notes: update.body ?? "",
      pubDate: update.date ?? "",
    };
    setState({ state: "downloading", update: info, progress: 0, checkedAt: Date.now() });
    pendingDownload = update;
    let total = 0;
    let downloaded = 0;
    // 下载超时保护。
    //
    // 没有它的话，`update.download()` 一旦挂起（网络抖动、CDN 卡住），
    // 状态会永远停在 `downloading`；而 `checkForUpdate()` 开头有
    //   if (state === "downloading") return;
    // 于是**之后每次点「检查更新」都静默返回**——用户看到的就是「点了没反应」，
    // 而且界面上那条 1.5px 进度条几乎看不见。实测踩到。
    //
    // 5 分钟对 8MB 的桌面更新包足够；超时后主动抛错走 catch，状态回到 error → idle，
    // 下次检查就能重新开始。
    const DOWNLOAD_TIMEOUT_MS = 5 * 60_000;
    const downloadPromise = update.download((event: any) => {
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
    await Promise.race([
      downloadPromise,
      new Promise<never>((_, reject) =>
        setTimeout(
          () => reject(new Error(`下载超时（${DOWNLOAD_TIMEOUT_MS / 1000}s），请稍后重试`)),
          DOWNLOAD_TIMEOUT_MS,
        ),
      ),
    ]);
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

    // 监听 tray 菜单 "Check for Updates" 事件
    let unlisten: (() => void) | undefined;
    (async () => {
      if (typeof window !== "undefined" && (window as any).__TAURI_INTERNALS__) {
        try {
          const { listen } = await import("@tauri-apps/api/event");
          unlisten = await listen("tray-check-update", () => {
            void checkForUpdate();
          });
        } catch {}
      }
    })();

    return () => {
      mountedRef.current = false;
      listeners.delete(listener);
      unlisten?.();
    };
  }, []);

  const checkNow = useCallback(() => checkForUpdate(), []);
  const installNow = useCallback(() => installAndRestart(), []);
  const dismiss = useCallback(() => dismissUpdate(), []);

  return { ...state, checkNow, installNow, dismiss };
}
