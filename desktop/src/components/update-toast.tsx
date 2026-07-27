/**
 * 自动更新 toast：右下角轻量提示，不打扰对话。
 *
 * - downloading：仅显示一条细进度条（5px 高，右下角，无文字）
 * - ready：弹出小卡片，显示新版本号 + 「立即安装并重启」/「下次再说」按钮
 * - error：3s 内自动消失
 *
 * 半静默策略：下载过程完全静默，下载完成后才提示安装。
 */

import { useEffect, useState } from "react";
import { RefreshCw, X } from "lucide-react";
import { useUpdater } from "@/lib/use-updater";

export function UpdateToast() {
  const { state, update, progress, error, installNow, dismiss } = useUpdater();
  const [dismissed, setDismissed] = useState(false);

  // 状态切换时重置 dismissed 标记
  useEffect(() => {
    setDismissed(false);
  }, [state, update?.version]);

  // 下载中：极细进度条，无文字
  if (state === "downloading" && progress < 100) {
    return (
      <div className="fixed bottom-4 right-4 z-50 pointer-events-none">
        <div className="w-48 h-1.5 bg-muted/60 rounded-full overflow-hidden shadow-sm">
          <div
            className="h-full bg-primary/60 transition-all duration-200"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
    );
  }

  // 已下载待安装：显示卡片
  if (state === "ready" && !dismissed) {
    return (
      <div className="fixed bottom-4 right-4 z-50 pointer-events-auto">
        <div className="flex items-start gap-3 p-3 pr-2 rounded-lg bg-background border border-border shadow-lg max-w-sm">
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium">新版本已就绪</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {update?.version ? `v${update.version} · ` : ""}安装并重启后生效
            </div>
            {update?.notes && (
              <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                {update.notes}
              </div>
            )}
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={() => void installNow()}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              <RefreshCw className="h-3 w-3" />
              立即安装
            </button>
            <button
              onClick={() => {
                setDismissed(true);
                dismiss();
              }}
              className="p-1 text-muted-foreground hover:text-foreground rounded"
              aria-label="下次再说"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  // 错误：短暂提示
  if (state === "error" && !dismissed && error) {
    return (
      <div className="fixed bottom-4 right-4 z-50 pointer-events-auto">
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-destructive/10 border border-destructive/30 text-destructive text-xs shadow-sm">
          <span>更新检查失败</span>
          <button
            onClick={() => setDismissed(true)}
            className="p-0.5 hover:bg-destructive/10 rounded"
            aria-label="关闭"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      </div>
    );
  }

  return null;
}
