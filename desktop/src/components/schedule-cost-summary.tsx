import type { ScheduleCost } from "@/lib/api-misc";

// Preserve the API number's shortest round-trip representation for fractions.
// Locale's default fraction limit would round tiny positive cache usage to zero.
const formatTokens = (value: number) => Number.isInteger(value) ? value.toLocaleString("en-US") : String(value);

/** Exact numbers, not compact estimates: directly comparable to SQL fixtures. */
export function ScheduleCostSummary({ cost }: { cost?: ScheduleCost | null }) {
  if (!cost) return <p className="text-[11px] text-muted-foreground">近7天成本暂不可用</p>;
  return (
    <div className="text-[11px] text-muted-foreground space-y-0.5" aria-label="近7天运行成本">
      <p>近{cost.window_days}天：运行 {cost.run_count} 次 · 平均步数 {cost.average_steps ?? "—"}</p>
      <p>输入 {formatTokens(cost.input_tokens)} token · 缓存 {formatTokens(cost.cache_tokens)}</p>
      <p>命中率 {cost.cache_hit_rate === null ? "—" : `${cost.cache_hit_rate.toFixed(1)}%`}</p>
      <p title="一条最终落库 assistant 消息代表一次运行，含失败；不计运行中的占位消息。">最终 assistant 行计运行（含失败）</p>
      {cost.usage_run_count < cost.run_count && <p>有效 usage：{cost.usage_run_count}/{cost.run_count} 次（缺失不估算）</p>}
      {cost.unattributed_runs > 0 && <p>本用户另有 {cost.unattributed_runs} 次历史运行未归因，不计入此任务</p>}
    </div>
  );
}
