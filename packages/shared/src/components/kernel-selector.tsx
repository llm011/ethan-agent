/**
 * 内核选择器 —— 多内核运行时的设置界面（desktop / web 共用）。
 *
 * 交互设计要点：
 *
 * 1. **不可用的内核不隐藏，显示「安装」**。
 *    隐藏会让人以为没有这个能力；显示出来并说明装什么、多大，才有选择权。
 *
 * 2. **选中即安装**。
 *    点「安装并启用」→ 调 `installKernel` → 装完自动 `selectKernel`。
 *    用户不需要去终端敲 npm。失败时把确切原因和后端给的解法展示出来
 *    （比如 npm 权限不足时给 `npm config set prefix` 的建议）。
 *
 * 3. **能力差异必须明说**。
 *    外部内核不走 Ethan 的工具/技能/记忆，也不做中途授权——这是真实取舍，
 *    不是 bug。UI 上标出来，用户才不会用错场景后困惑。
 *
 * 4. **"按任务自动选" 折叠起来**。
 *    高级功能，默认收起，避免主界面变成一个配置面板。
 */

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Check, Download, Loader2, RefreshCw, Zap } from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

/** 与后端 `KernelInfo` 对应（见 ethan/interface/routers/settings.py）。 */
export interface KernelCapabilities {
  streaming: boolean;
  tools: boolean;
  consent: boolean;
  ethan_context: boolean;
  resumable: boolean;
}

export interface KernelInfo {
  kind: string;
  name: string;
  available: boolean;
  reason: string;
  capabilities: KernelCapabilities;
  install_command: string;
  install_hint: string;
}

export interface KernelSelectorProps {
  kernels: KernelInfo[];
  current: string;
  taskRules: Record<string, string>;
  loading?: boolean;
  /** 切换默认内核（内部会确保依赖就绪）。抛错表示切换失败。 */
  onSelect: (kind: string) => Promise<void>;
  /** 只安装依赖，不切换。 */
  onInstall?: (kind: string) => Promise<void>;
  onSetTaskRules?: (rules: Record<string, string>) => Promise<void>;
  onRefresh?: () => void;
}

/** 任务类型的中文标签。与后端 `_infer_task_kind` 的取值对应。 */
const TASK_LABELS: Record<string, string> = {
  coding: "编码任务",
  research: "调研任务",
  chat: "日常对话",
};

export function KernelSelector({
  kernels,
  current,
  taskRules,
  loading = false,
  onSelect,
  onInstall,
  onSetTaskRules,
  onRefresh,
}: KernelSelectorProps) {
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [showRules, setShowRules] = useState(false);

  const handleSelect = useCallback(
    async (k: KernelInfo) => {
      setError("");
      setBusy(k.kind);
      try {
        await onSelect(k.kind);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy("");
      }
    },
    [onSelect],
  );

  const handleInstall = useCallback(
    async (k: KernelInfo) => {
      if (!onInstall) return;
      setError("");
      setBusy(k.kind);
      try {
        await onInstall(k.kind);
        onRefresh?.();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy("");
      }
    },
    [onInstall, onRefresh],
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>AI 内核</CardTitle>
          {onRefresh && (
            <Button variant="ghost" size="sm" onClick={onRefresh} disabled={loading}>
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            </Button>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          决定「由谁执行」这一轮对话。原生内核使用 Ethan 的全部能力；
          外部内核把执行权交给对应 CLI，各自有自己的工具与提示词。
        </p>
      </CardHeader>

      <CardContent className="space-y-3">
        {kernels.map((k) => {
          const isCurrent = k.kind === current;
          const isBusy = busy === k.kind;
          const isExternal = k.kind !== "ethan";

          return (
            <div
              key={k.kind}
              className={`rounded-lg border p-3 transition-colors ${
                isCurrent ? "border-primary/40 bg-primary/5" : "border-border"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{k.name}</span>
                    <code className="text-[10px] text-muted-foreground">{k.kind}</code>
                    {isCurrent && (
                      <Badge variant="default" className="gap-1">
                        <Check className="h-3 w-3" />
                        当前
                      </Badge>
                    )}
                    {!k.available && (
                      <Badge variant="secondary" className="gap-1">
                        <Download className="h-3 w-3" />
                        未安装
                      </Badge>
                    )}
                  </div>

                  {/* 不可用原因：这是用户最需要知道的信息 */}
                  {!k.available && k.reason && (
                    <p className="mt-1 text-xs text-amber-500">{k.reason}</p>
                  )}

                  {/* 能力差异：外部内核的取舍要明说，否则用户会当成 bug */}
                  {isExternal && k.capabilities && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {!k.capabilities.ethan_context && (
                        <Badge variant="outline" className="text-[10px]">
                          不共享 Ethan 技能/记忆
                        </Badge>
                      )}
                      {!k.capabilities.consent && (
                        <Badge variant="outline" className="text-[10px]">
                          无中途授权
                        </Badge>
                      )}
                      {k.capabilities.resumable && (
                        <Badge variant="outline" className="text-[10px]">
                          支持会话续接
                        </Badge>
                      )}
                    </div>
                  )}
                </div>

                <div className="flex shrink-0 gap-2">
                  {!k.available && onInstall ? (
                    <Button
                      size="sm"
                      onClick={() => handleInstall(k)}
                      disabled={isBusy}
                    >
                      {isBusy ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Download className="h-3.5 w-3.5" />
                      )}
                      安装
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant={isCurrent ? "secondary" : "default"}
                      disabled={isCurrent || isBusy || (!k.available && !isCurrent)}
                      onClick={() => handleSelect(k)}
                    >
                      {isBusy ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : null}
                      {isCurrent ? "使用中" : "启用"}
                    </Button>
                  )}
                </div>
              </div>

              {/* 安装命令：给想自己装/想看装什么的人 */}
              {!k.available && k.install_command && (
                <p className="mt-2 truncate font-mono text-[10px] text-muted-foreground">
                  {k.install_command}
                  {k.install_hint ? `  ·  ${k.install_hint}` : ""}
                </p>
              )}
            </div>
          );
        })}

        {error && (
          <div className="flex gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="whitespace-pre-wrap">{error}</span>
          </div>
        )}

        {/* 按任务自动选：高级功能，默认收起 */}
        {onSetTaskRules && (
          <div className="pt-2">
            <button
              type="button"
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setShowRules((v) => !v)}
            >
              <Zap className="h-3 w-3" />
              按任务类型自动选内核
              <span className="text-[10px]">{showRules ? "收起" : "展开"}</span>
            </button>

            {showRules && (
              <div className="mt-2 space-y-2 rounded-md border p-2">
                {Object.keys(TASK_LABELS).map((task) => (
                  <div key={task} className="flex items-center justify-between gap-2">
                    <span className="text-xs">{TASK_LABELS[task]}</span>
                    <select
                      className="rounded border bg-background px-1.5 py-1 text-xs"
                      value={taskRules[task] || ""}
                      onChange={(e) => {
                        const next = { ...taskRules };
                        if (e.target.value) next[task] = e.target.value;
                        else delete next[task];
                        onSetTaskRules(next).catch((err) =>
                          setError(err instanceof Error ? err.message : String(err)),
                        );
                      }}
                    >
                      <option value="">跟随默认</option>
                      {kernels
                        .filter((k) => k.available)
                        .map((k) => (
                          <option key={k.kind} value={k.kind}>
                            {k.name}
                          </option>
                        ))}
                    </select>
                  </div>
                ))}
                <p className="text-[10px] text-muted-foreground">
                  任务类型由关键词粗判（编码/调研/对话）。判断不准时会回退到默认内核，不会出错。
                </p>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
