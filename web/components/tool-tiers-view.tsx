"use client";

import { useEffect, useState, useCallback } from "react";
import { fetchToolTiers, ToolTiers, TierTool } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Loader2, RefreshCw, Zap, Layers, Maximize2 } from "lucide-react";

const TIER_ICON: Record<string, React.ReactNode> = {
  fast: <Zap className="h-4 w-4 text-amber-500" />,
  medium: <Layers className="h-4 w-4 text-sky-500" />,
  full: <Maximize2 className="h-4 w-4 text-violet-500" />,
};

function TierTable({ tools }: { tools: TierTool[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="text-left text-xs text-muted-foreground border-b border-border/60">
            <th className="py-2 pr-4 font-medium w-44">工具</th>
            <th className="py-2 pr-4 font-medium">说明</th>
            <th className="py-2 pr-3 font-medium w-16 text-center">副作用</th>
            <th className="py-2 font-medium w-16 text-center">不压缩</th>
          </tr>
        </thead>
        <tbody>
          {tools.map((t) => (
            <tr key={t.name} className="border-b border-border/30 align-top">
              <td className="py-2 pr-4">
                <code className="text-xs font-mono text-foreground/90">{t.name}</code>
              </td>
              <td className="py-2 pr-4 text-xs text-muted-foreground leading-relaxed">{t.description}</td>
              <td className="py-2 pr-3 text-center">
                {t.side_effect ? <span title="有副作用：改文件/发消息/花钱等，非主人调用会被拦截">⚠️</span> : <span className="text-muted-foreground/30">—</span>}
              </td>
              <td className="py-2 text-center">
                {t.no_compress ? <span title="输出不压缩：含 ID/ref/结构化数据，逐字给模型">🔒</span> : <span className="text-muted-foreground/30">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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

      <div className="flex-1 overflow-y-auto p-6">
        {loading && !data ? (
          <div className="flex items-center justify-center pt-10">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : !data ? (
          <div className="text-center text-muted-foreground pt-10">加载失败，点右上角刷新重试。</div>
        ) : (
          <div className="flex flex-col gap-6 max-w-4xl">
            <p className="text-sm text-muted-foreground leading-relaxed">
              对话按「快捷路由」规则与消息长度实时路由到三档。<b className="text-foreground/80">Fast</b> 档命中规则关键字时进入，
              固定挂载下列基础工具 + 命中规则的额外工具，其余长尾能力需模型调{" "}
              <code className="text-xs font-mono">find_tools</code> 激活；
              <b className="text-foreground/80">Medium / Full</b> 档全量工具直接可见。当前共注册{" "}
              <b className="text-foreground/80">{data.total_count}</b> 个工具，其中 Fast 基础{" "}
              <b className="text-foreground/80">{data.fast_count}</b> 个。
              <span className="ml-1">（未命中规则时：≤ {data.medium_max_length} 字走 medium，更长走 full · 规则在「设置 → 快捷路由」配置）</span>
            </p>

            {data.tiers.map((tier) => (
              <div key={tier.key} className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  {TIER_ICON[tier.key]}
                  <span className="font-semibold text-sm">{tier.label}</span>
                  <Badge variant="secondary" className="text-[10px]">
                    {tier.tools.length} 个工具
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">{tier.desc}</p>
                <TierTable tools={tier.tools} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
