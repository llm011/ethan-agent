/**
 * 关于页：显示当前版本、手动检查更新、自动更新开关。
 */

import { useEffect, useState } from "react";
import { RefreshCw, CheckCircle2, AlertCircle, Download, RotateCw } from "lucide-react";
import { Button } from "@ethan/shared/ui/button";
import { getVersion as getTauriAppVersion } from "@tauri-apps/api/app";
import { startAutoUpdate, useUpdater } from "@/lib/use-updater";

const AUTO_UPDATE_KEY = "ethan_auto_update_disabled";

export function AboutTab() {
  const { state, update, progress, error, checkNow, installNow } = useUpdater();
  const [appVersion, setAppVersion] = useState<string>("");
  const [autoUpdateDisabled, setAutoUpdateDisabled] = useState(false);
  const [autostartEnabled, setAutostartEnabled] = useState(false);

  // 首次安装默认开启开机自启（仅初始化一次）
  useEffect(() => {
    const AUTOSTART_INIT_KEY = "ethan_autostart_initialized";
    (async () => {
      if (typeof window === "undefined" || !(window as any).__TAURI_INTERNALS__) return;
      try {
        const { isEnabled, enable } = await import("@tauri-apps/plugin-autostart");
        const enabled = await isEnabled();
        if (!enabled && !localStorage.getItem(AUTOSTART_INIT_KEY)) {
          await enable();
          localStorage.setItem(AUTOSTART_INIT_KEY, "1");
          setAutostartEnabled(true);
        } else {
          setAutostartEnabled(enabled);
        }
      } catch {
        // autostart 插件不可用时静默忽略
      }
    })();
  }, []);

  useEffect(() => {
    getTauriAppVersion().then(setAppVersion).catch(() => setAppVersion(""));
    setAutoUpdateDisabled(localStorage.getItem(AUTO_UPDATE_KEY) === "1");
  }, []);

  const toggleAutoUpdate = () => {
    const next = !autoUpdateDisabled;
    setAutoUpdateDisabled(next);
    if (next) {
      localStorage.setItem(AUTO_UPDATE_KEY, "1");
    } else {
      localStorage.removeItem(AUTO_UPDATE_KEY);
      startAutoUpdate();
    }
  };

  const toggleAutostart = async () => {
    if (typeof window === "undefined" || !(window as any).__TAURI_INTERNALS__) return;
    try {
      const { enable, disable, isEnabled } = await import("@tauri-apps/plugin-autostart");
      if (autostartEnabled) {
        await disable();
        setAutostartEnabled(false);
      } else {
        await enable();
        setAutostartEnabled(true);
        localStorage.setItem("ethan_autostart_initialized", "1");
      }
    } catch {
      // 忽略错误
    }
  };

  const isBusy = state === "checking" || state === "downloading";
  const statusLabel = {
    idle: "已是最新版本",
    checking: "检查中…",
    downloading: `下载中 ${progress}%`,
    ready: "已下载，等待安装",
    installing: "安装中…",
    installed: "已安装，正在重启",
    error: "检查失败",
  }[state];

  const StatusIcon = state === "idle" ? CheckCircle2
    : state === "error" ? AlertCircle
    : state === "ready" || state === "installed" || state === "installing" ? RotateCw
    : state === "downloading" ? Download
    : RefreshCw;

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium mb-1">版本与更新</h3>
        <p className="text-sm text-muted-foreground">
          桌面端通过 GitHub Release 分发，启动后自动检查更新并在后台静默下载。
        </p>
      </div>

      {/* 版本信息 */}
      <div className="rounded-md border border-border/60 divide-y divide-border/40">
        <div className="flex items-center justify-between px-4 py-3">
          <span className="text-sm text-muted-foreground">当前版本</span>
          <code className="text-sm font-mono">v{appVersion || "—"}</code>
        </div>
        <div className="flex items-center justify-between px-4 py-3">
          <span className="text-sm text-muted-foreground">最新版本</span>
          <code className="text-sm font-mono">
            {update?.version ? `v${update.version}` : "—"}
          </code>
        </div>
        <div className="flex items-center justify-between px-4 py-3">
          <span className="text-sm text-muted-foreground">状态</span>
          <span className="inline-flex items-center gap-1.5 text-sm">
            <StatusIcon className={`h-3.5 w-3.5 ${state === "error" ? "text-red-500" : state === "installed" ? "text-emerald-500" : "text-muted-foreground"} ${isBusy ? "animate-spin" : ""}`} />
            {statusLabel}
          </span>
        </div>
        {error && (
          <div className="px-4 py-2 text-xs text-red-500 break-all">{error}</div>
        )}
      </div>

      {/* 操作按钮 */}
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={isBusy}
          onClick={() => void checkNow()}
        >
          <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${isBusy ? "animate-spin" : ""}`} />
          {state === "checking" ? "检查中…" : "手动检查更新"}
        </Button>
        {state === "ready" && (
          <Button size="sm" onClick={() => void installNow()}>
            <RotateCw className="h-3.5 w-3.5 mr-1.5" />
            立即安装并重启
          </Button>
        )}
      </div>

      {/* 自动更新开关 */}
      <div className="flex items-start justify-between gap-4 pt-2 border-t border-border/40">
        <div>
          <div className="text-sm font-medium">启动时自动检查更新</div>
          <div className="text-xs text-muted-foreground mt-1">
            关闭后桌面端不再主动检查，但仍可通过上方按钮手动触发。
          </div>
        </div>
        <button
          onClick={toggleAutoUpdate}
          role="switch"
          aria-checked={!autoUpdateDisabled}
          className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${autoUpdateDisabled ? "bg-muted" : "bg-primary"}`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-background transition-transform ${autoUpdateDisabled ? "translate-x-0.5" : "translate-x-4"}`}
          />
        </button>
      </div>

      {/* 开机自启开关 */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-medium">开机时自动启动</div>
          <div className="text-xs text-muted-foreground mt-1">
            登录系统后自动在后台启动 Ethan Agent。
          </div>
        </div>
        <button
          onClick={() => void toggleAutostart()}
          role="switch"
          aria-checked={autostartEnabled}
          className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${autostartEnabled ? "bg-primary" : "bg-muted"}`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-background transition-transform ${autostartEnabled ? "translate-x-4" : "translate-x-0.5"}`}
          />
        </button>
      </div>

      {/* 更新说明 */}
      {update?.notes && (
        <div className="pt-2 border-t border-border/40">
          <div className="text-sm font-medium mb-2">更新日志</div>
          <div className="text-xs text-muted-foreground whitespace-pre-wrap rounded-md bg-muted/30 p-3 max-h-80 overflow-y-auto">
            {update.notes}
          </div>
        </div>
      )}

      <div className="pt-2 border-t border-border/40 text-xs text-muted-foreground space-y-1">
        <p>· macOS 通过 Tauri Updater 更新的版本不会携带 quarantine 属性，无需再跑 <code className="bg-muted px-1 rounded">xattr -dr</code>。</p>
        <p>· 首次安装仍需手动 xattr 一次（来自浏览器下载的隔离属性），后续更新不再需要。</p>
      </div>
    </div>
  );
}
