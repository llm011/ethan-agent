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

import { useCallback, useState } from "react";
import { AlertCircle, Check, Download, Loader2, RefreshCw, Wrench, Zap } from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";

/** 与后端 `KernelInfo` 对应（见 ethan/interface/routers/settings.py）。 */
export interface KernelCapabilities {
  streaming: boolean;
  tools: boolean;
  consent: boolean;
  ethan_context: boolean;
  resumable: boolean;
  /** 能否共享 Ethan 的工具/技能（经 MCP 注入）。这是"内核作为 Ethan 心脏"的核心指标 */
  shares_ethan_tools: boolean;
  /** 不能共享时的原因（可操作说明，不是「暂不支持」） */
  shares_ethan_tools_reason: string;
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

export type KernelInjectContextMode = "off" | "rules_profile" | "full";

export interface KernelSelectorProps {
  kernels: KernelInfo[];
  current: string;
  taskRules: Record<string, string>;
  injectContext?: KernelInjectContextMode;
  loading?: boolean;
  /** 拉取内核列表失败时的错误信息，避免列表为空时无声失败 */
  loadError?: string;
  /** 切换默认内核（内部会确保依赖就绪）。抛错表示切换失败。 */
  onSelect: (kind: string) => Promise<void>;
  /** 只安装依赖，不切换。 */
  onInstall?: (kind: string) => Promise<void>;
  onSetTaskRules?: (rules: Record<string, string>) => Promise<void>;
  onSetInjectContext?: (mode: KernelInjectContextMode) => Promise<void>;
  onRefresh?: () => void;
}

/** 外部内核上下文注入档位的中文标签与说明。 */
const INJECT_CONTEXT_OPTIONS: Array<{
  value: KernelInjectContextMode;
  label: string;
  desc: string;
  badge: string;
}> = [
  {
    value: "rules_profile",
    label: "准则与画像（推荐）",
    desc: "注入 soul.md（主人权限与安全红线）、我的画像、纠错准则，保留外部内核原生语气。",
    badge: "注入准则与画像",
  },
  {
    value: "full",
    label: "完整人格与画像",
    desc: "在准则与画像基础上，额外注入 identity.md 与当前模式人设（可能与外部内核风格重叠）。",
    badge: "注入完整人格/画像",
  },
  {
    value: "off",
    label: "仅工具简报（关闭上下文）",
    desc: "不注入 soul.md、画像或人设，仅在共享 Ethan 工具时提供技能与记忆提示。",
    badge: "不注入 Ethan 人格/画像",
  },
];

/** 任务类型的中文标签。与后端 `_infer_task_kind` 的取值对应。 */
const TASK_LABELS: Record<string, string> = {
  coding: "编码任务",
  research: "调研任务",
  chat: "日常对话",
};

const FOLLOW_DEFAULT_VALUE = "__default__";

export function KernelSelector({
  kernels,
  current,
  taskRules,
  injectContext = "rules_profile",
  loading = false,
  loadError = "",
  onSelect,
  onInstall,
  onSetTaskRules,
  onSetInjectContext,
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
        {loading && kernels.length === 0 && (
          <div className="flex items-center gap-2 rounded-lg border border-dashed px-3 py-6 text-xs text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>正在加载内核列表…</span>
          </div>
        )}

        {!loading && loadError && kernels.length === 0 && (
          <div className="flex items-start justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
            <div className="flex gap-2">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="space-y-1">
                <p className="font-medium">无法加载内核列表</p>
                <p className="whitespace-pre-wrap text-destructive/90">{loadError}</p>
              </div>
            </div>
            {onRefresh && (
              <Button size="sm" variant="outline" onClick={onRefresh}>
                重试
              </Button>
            )}
          </div>
        )}

        {!loading && !loadError && kernels.length === 0 && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-dashed px-3 py-4 text-xs text-muted-foreground">
            <span>未获取到可用内核配置，请检查后端服务状态。</span>
            {onRefresh && (
              <Button size="sm" variant="outline" onClick={onRefresh}>
                刷新
              </Button>
            )}
          </div>
        )}

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
                    <>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {/* 最关键的一条：能不能用 Ethan 的工具干活 */}
                        {k.capabilities.shares_ethan_tools ? (
                          <Badge
                            variant="default"
                            className="gap-1 bg-emerald-500/15 text-[10px] text-emerald-600 hover:bg-emerald-500/20"
                          >
                            <Wrench className="h-2.5 w-2.5" />
                            可用 Ethan 的工具
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="gap-1 text-[10px] text-muted-foreground">
                            <Wrench className="h-2.5 w-2.5" />
                            仅自带工具
                          </Badge>
                        )}
                        {/* ethan_context=False 表示使用外部内核自身系统提示词；
                            具体是否注入 soul/画像/人设由 injectContext 配置决定。 */}
                        {!k.capabilities.ethan_context && (
                          <Badge variant="outline" className="text-[10px]">
                            {INJECT_CONTEXT_OPTIONS.find((o) => o.value === injectContext)?.badge ??
                              "注入准则与画像"}
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

                      {/* 不能共享时说明原因——别让用户以为是 bug */}
                      {!k.capabilities.shares_ethan_tools &&
                        k.capabilities.shares_ethan_tools_reason && (
                          <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                            {k.capabilities.shares_ethan_tools_reason}
                          </p>
                        )}
                    </>
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

        {/* 外部内核上下文注入粒度：控制 soul.md / user_profile.md / identity.md 是否注入 */}
        {onSetInjectContext && kernels.length > 0 && (
          <div className="rounded-lg border border-border/70 bg-muted/20 p-3 space-y-2">
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs font-medium">外部内核上下文注入</span>
              <Select
                value={injectContext}
                onValueChange={(val) => {
                  const next = (val || "rules_profile") as KernelInjectContextMode;
                  setError("");
                  onSetInjectContext(next).catch((err) =>
                    setError(err instanceof Error ? err.message : String(err)),
                  );
                }}
              >
                <SelectTrigger size="sm" className="min-w-[170px] bg-background text-xs">
                  <SelectValue>
                    {(v: string) =>
                      INJECT_CONTEXT_OPTIONS.find((o) => o.value === v)?.label ??
                      "准则与画像（推荐）"
                    }
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {INJECT_CONTEXT_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value} className="text-xs">
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              {INJECT_CONTEXT_OPTIONS.find((o) => o.value === injectContext)?.desc ??
                INJECT_CONTEXT_OPTIONS[0].desc}
            </p>
          </div>
        )}

        {/* 按任务自动选：高级功能，默认收起；内核列表未加载时不展示空下拉 */}
        {onSetTaskRules && kernels.length > 0 && (
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
              <div className="mt-2 space-y-2.5 rounded-lg border border-border/70 bg-muted/20 p-3">
                {Object.keys(TASK_LABELS).map((task) => {
                  const selectedKind = taskRules[task] || FOLLOW_DEFAULT_VALUE;
                  const availableKernels = kernels.filter((k) => k.available);
                  const labelMap: Record<string, string> = {
                    [FOLLOW_DEFAULT_VALUE]: "跟随默认",
                    ...Object.fromEntries(kernels.map((k) => [k.kind, k.name])),
                  };
                  return (
                    <div key={task} className="flex items-center justify-between gap-3">
                      <span className="text-xs font-medium">{TASK_LABELS[task]}</span>
                      <Select
                        value={selectedKind}
                        onValueChange={(val) => {
                          const next = { ...taskRules };
                          if (val && val !== FOLLOW_DEFAULT_VALUE) next[task] = val;
                          else delete next[task];
                          onSetTaskRules(next).catch((err) =>
                            setError(err instanceof Error ? err.message : String(err)),
                          );
                        }}
                      >
                        <SelectTrigger size="sm" className="min-w-[140px] bg-background text-xs">
                          <SelectValue placeholder="跟随默认">
                            {(v: string) => labelMap[v] ?? v ?? "跟随默认"}
                          </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={FOLLOW_DEFAULT_VALUE} className="text-xs">
                            跟随默认
                          </SelectItem>
                          {availableKernels.map((k) => (
                            <SelectItem key={k.kind} value={k.kind} className="text-xs">
                              {k.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  );
                })}
                <p className="text-[11px] text-muted-foreground">
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
