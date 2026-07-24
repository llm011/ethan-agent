import { useEffect, useState, useCallback } from "react";
import { fetchToolTiers, ToolTiers, TierTool } from "@/lib/api";
import { Button } from "@ethan/shared/ui/button";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@ethan/shared/ui/tooltip";
import { Loader2, RefreshCw, Zap, Maximize2 } from "lucide-react";

const TIER_META: Record<string, { icon: React.ReactNode; color: string; check: string }> = {
  fast: {
    icon: <Zap className="h-3.5 w-3.5" />,
    color: "text-amber-500",
    check: "text-amber-500",
  },
  full: {
    icon: <Maximize2 className="h-3.5 w-3.5" />,
    color: "text-violet-500",
    check: "text-violet-500",
  },
};

function calcChars(tools: TierTool[]): number {
  return tools.reduce((sum, t) => sum + t.name.length + t.description.length, 0);
}

function fmtChars(n: number): string {
  return n >= 1000 ? `~${Math.round(n / 100) / 10}k` : `${n}`;
}

function ComparisonTable({ data }: { data: ToolTiers }) {
  const { tiers, full_count, longtail_count } = data;
  // Full 档作为工具全集
  const allTools = tiers.find((t) => t.key === "full")?.tools ?? [];

  const memberSets = Object.fromEntries(
    tiers.map((tier) => [tier.key, new Set(tier.tools.map((t) => t.name))])
  );

  // fast tools first, then alphabetical
  const sorted = [...allTools].sort((a, b) => {
    const af = memberSets["fast"]?.has(a.name) ? 0 : 1;
    const bf = memberSets["fast"]?.has(b.name) ? 0 : 1;
    if (af !== bf) return af - bf;
    return a.name.localeCompare(b.name);
  });

  const fastCount = sorted.filter((t) => memberSets["fast"]?.has(t.name)).length;

  return (
    <TooltipProvider delay={200}>
      <div className="overflow-x-auto rounded-md border border-border/60">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-border/60 bg-muted/30">
              <th className="py-3 px-4 text-left text-xs font-medium text-muted-foreground w-56">
                工具
              </th>
              {tiers.map((tier) => {
                const meta = TIER_META[tier.key];
                // Fast: 直接显示基础工具数；Full: 显示「初始广播 N + 长尾 M」
                const isFull = tier.key === "full";
                const initialCount = isFull ? full_count : tier.tools.length;
                const longtail = isFull ? longtail_count : 0;
                // 字符统计：Full 只统计初始广播集（长尾不广播，不耗 token）
                const charsTools = isFull
                  ? tier.tools.filter((t) => t.in_full_base)
                  : tier.tools;
                return (
                  <th key={tier.key} className="py-3 px-4 text-center w-28">
                    <Tooltip>
                      <TooltipTrigger render={<div className="flex flex-col items-center gap-0.5 cursor-default select-none" />}>
                          <div className={`flex items-center gap-1 font-semibold text-xs ${meta.color}`}>
                            {meta.icon}
                            {tier.label}
                          </div>
                          <div className="text-[10px] text-muted-foreground font-normal">
                            {isFull ? (
                              <span>{initialCount} 初始{longtail > 0 ? ` + ${longtail} 长尾` : ""}</span>
                            ) : (
                              <span>{initialCount} 个工具</span>
                            )}
                          </div>
                          <div className="text-[10px] text-muted-foreground/50 font-normal">
                            {fmtChars(calcChars(charsTools))} 字符
                          </div>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-56 text-center">
                        {tier.desc}
                      </TooltipContent>
                    </Tooltip>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((tool, i) => {
              const isLastFast = i === fastCount - 1 && fastCount < sorted.length;
              return (
                <tr
                  key={tool.name}
                  className={`align-middle hover:bg-muted/20 transition-colors ${
                    isLastFast
                      ? "border-b-2 border-b-amber-500/40"
                      : "border-b border-border/30"
                  }`}
                >
                  <td className="py-2 px-4">
                    <Tooltip>
                      <TooltipTrigger render={<span className="inline-flex items-center gap-1.5 cursor-default" />}>
                          <code className="text-xs font-mono text-foreground/90">
                            {tool.name}
                          </code>
                          {tool.side_effect && (
                            <Tooltip>
                              <TooltipTrigger render={<span className="text-[11px] leading-none cursor-default" />}>
                                ⚠️
                              </TooltipTrigger>
                              <TooltipContent side="right" className="max-w-48">
                                有副作用：会改状态/发消息/花钱，非主人调用被拦截
                              </TooltipContent>
                            </Tooltip>
                          )}
                          {tool.no_compress && (
                            <Tooltip>
                              <TooltipTrigger render={<span className="text-[11px] leading-none cursor-default" />}>
                                🔒
                              </TooltipTrigger>
                              <TooltipContent side="right" className="max-w-48">
                                不压缩：输出含关键 ID/ref，必须原样传回
                              </TooltipContent>
                            </Tooltip>
                          )}
                      </TooltipTrigger>
                      <TooltipContent side="right" className="max-w-64">
                        {tool.description}
                      </TooltipContent>
                    </Tooltip>
                  </td>
                  {tiers.map((tier) => {
                    const has = memberSets[tier.key]?.has(tool.name);
                    const meta = TIER_META[tier.key];
                    // Full 列：长尾工具（不在初始广播集）显示「需激活」，区别于 Fast 列的 ✗
                    const isFullLongtail = tier.key === "full" && has && !tool.in_full_base;
                    return (
                      <td key={tier.key} className="py-2 px-4 text-center">
                        {has ? (
                          isFullLongtail ? (
                            <Tooltip>
                              <TooltipTrigger render={<span className="text-[10px] text-muted-foreground/60 cursor-default" />}>
                                激活
                              </TooltipTrigger>
                              <TooltipContent side="top" className="max-w-56">
                                长尾工具：模型调 find_tools 后才可见
                              </TooltipContent>
                            </Tooltip>
                          ) : (
                            <span className={`text-sm font-bold ${meta.check}`}>✓</span>
                          )
                        ) : (
                          <span className="text-xs text-muted-foreground/20">✗</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </TooltipProvider>
  );
}

export function ToolTiersView({ embedded = false }: { embedded?: boolean }) {
  const [data, setData] = useState<ToolTiers | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchToolTiers());
    } catch (e) {
      console.error("Failed to load tool tiers", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex flex-col h-full bg-background text-foreground">
      {!embedded && (
        <header className="h-12 border-b border-border flex items-center px-4 justify-between shrink-0">
          <h1 className="font-semibold text-lg">模式工具集 (Tool Tiers)</h1>
          <Button variant="ghost" size="icon" onClick={load} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </header>
      )}

      <div className={`flex-1 overflow-y-auto ${embedded ? "p-4" : "p-6"}`}>
        {loading && !data ? (
          <div className="flex items-center justify-center pt-10">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : !data ? (
          <div className="text-center text-muted-foreground pt-10">
            加载失败，点右上角刷新重试。
          </div>
        ) : (
          <div className="flex flex-col gap-3 max-w-2xl">
            <p className="text-sm text-muted-foreground leading-relaxed">
              对话按规则路由到两档。
              <b className="text-foreground/80">Fast</b> 档仅含基础工具 + 规则额外工具，长尾能力靠{" "}
              <code className="text-xs font-mono">find_tools</code> 激活；
              <b className="text-foreground/80">Full</b> 档初始广播{" "}
              <b className="text-foreground/80">{data.full_count}</b> 个核心工具，剩余{" "}
              <b className="text-foreground/80">{data.longtail_count}</b> 个长尾工具同样靠{" "}
              <code className="text-xs font-mono">find_tools</code> 激活。
              共注册 <b className="text-foreground/80">{data.total_count}</b> 个工具。
            </p>
            <p className="text-xs text-muted-foreground/50">
              hover 工具名查看说明 · ⚠️ 有副作用 · 🔒 输出不压缩 · 橙色分隔线以上为 Fast 档工具
            </p>
            <ComparisonTable data={data} />
          </div>
        )}
      </div>
    </div>
  );
}
