"use client";

import { useEffect, useState, useCallback } from "react";
import { fetchToolTiers, ToolTiers, TierTool } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Loader2, RefreshCw, Zap, Layers, Maximize2, AlertTriangle, Lock } from "lucide-react";

const TIER_ICON: Record<string, React.ReactNode> = {
  fast: <Zap className="h-4 w-4 text-amber-500" />,
  medium: <Layers className="h-4 w-4 text-sky-500" />,
  full: <Maximize2 className="h-4 w-4 text-violet-500" />,
};

function ToolRow({ t }: { t: TierTool }) {
  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-border/30 last:border-0">
      <code className="text-xs font-mono text-foreground/90 shrink-0 mt-0.5">{t.name}</code>
      <span className="text-xs text-muted-foreground flex-1 leading-relaxed">{t.description}</span>
      <div className="flex gap-1 shrink-0">
        {t.side_effect && (
          <span title="有副作用（改文件/发消息/花钱等），非主人调用会被拦截">
            <AlertTriangle className="h-3 w-3 text-orange-400/80" />
          </span>
        )}
        {t.no_compress && (
          <span title="输出不压缩：含 ID/ref/结构化数据，逐字给模型">
            <Lock className="h-3 w-3 text-emerald-500/70" />
          </span>
        )}
      </div>
    </div>
  );
}

export function ToolTiersView() {
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
      <header className="h-12 border-b border-border flex items-center px-4 justify-between shrink-0">
        <h1 className="font-semibold text-lg">模式工具集 (Tool Tiers)</h1>
        <Button variant="ghost" size="icon" onClick={load} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </header>

      <ScrollArea className="flex-1 p-6">
        {loading && !data ? (
          <div className="flex items-center justify-center pt-10">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : !data ? (
          <div className="text-center text-muted-foreground pt-10">加载失败，点右上角刷新重试。</div>
        ) : (
          <div className="flex flex-col gap-5 max-w-3xl">
            <p className="text-sm text-muted-foreground leading-relaxed">
              对话按消息长度与触发词实时路由到三档。<b className="text-foreground/80">Fast</b> 档只广播下面这些常驻工具，
              其余长尾能力需模型主动调 <code className="text-xs font-mono">find_tools</code> 激活；
              <b className="text-foreground/80">Medium / Full</b> 档全量工具直接可见。当前共注册{" "}
              <b className="text-foreground/80">{data.total_count}</b> 个工具，其中常驻{" "}
              <b className="text-foreground/80">{data.fast_count}</b> 个。
              <span className="ml-1">（fast ≤ {data.fast_max_length} 字 · medium ≤ {data.medium_max_length} 字 · 更长走 full）</span>
            </p>

            <div className="flex items-center gap-4 text-[11px] text-muted-foreground">
              <span className="flex items-center gap-1">
                <AlertTriangle className="h-3 w-3 text-orange-400/80" /> 有副作用
              </span>
              <span className="flex items-center gap-1">
                <Lock className="h-3 w-3 text-emerald-500/70" /> 输出不压缩
              </span>
            </div>

            {data.tiers.map((tier) => (
              <div key={tier.key} className="rounded-lg border border-border/60 bg-muted/10 overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border/40 bg-muted/20">
                  {TIER_ICON[tier.key]}
                  <span className="font-semibold text-sm">{tier.label}</span>
                  <Badge variant="secondary" className="text-[10px]">
                    {tier.tools.length} 个工具
                  </Badge>
                </div>
                <p className="px-4 pt-2.5 text-xs text-muted-foreground leading-relaxed">{tier.desc}</p>
                <div className="px-4 py-2">
                  {tier.tools.map((t) => (
                    <ToolRow key={t.name} t={t} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
