/* 本地服务存活状态指示器：绿/红/黄圆点 + 文字（浅色 Tag 样式）。
 *
 * 放 ChatHeader 右上角和 Sidebar 顶部 logo 旁，共享 useServerHealth 单例。
 * - ok：绿色，"服务正常"，hover 显示版本/延迟/上次检查时间
 * - down：红色，"连接不可用"，hover 显示上次检查时间
 * - checking：橙色脉冲，"检测中"
 */
import { useServerHealth, type ServerStatus } from "@/lib/use-server-health";

interface ServerStatusBadgeProps {
  /** compact = 只显示圆点；full = 圆点 + 文字 */
  variant?: "compact" | "full";
  /** 附加在外层容器上的 className（如 ml-auto 推到右侧） */
  className?: string;
}

const STATUS_STYLES: Record<ServerStatus, {
  dot: string;
  text: string;
  container: string;
  pulse: boolean;
}> = {
  ok: {
    dot: "bg-emerald-500",
    text: "text-emerald-700 dark:text-emerald-300",
    container: "bg-emerald-500/15 border-emerald-500/30",
    pulse: false,
  },
  down: {
    dot: "bg-red-500",
    text: "text-red-700 dark:text-red-300",
    container: "bg-red-500/15 border-red-500/30",
    pulse: false,
  },
  checking: {
    dot: "bg-amber-500",
    text: "text-amber-700 dark:text-amber-300",
    container: "bg-amber-500/15 border-amber-500/30",
    pulse: true,
  },
};

const STATUS_LABEL: Record<ServerStatus, string> = {
  ok: "服务正常",
  down: "连接不可用",
  checking: "检测中",
};

function formatAgo(ms: number): string {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s 前`;
  const m = Math.floor(s / 60);
  return `${m}m 前`;
}

export function ServerStatusBadge({ variant = "compact", className = "" }: ServerStatusBadgeProps) {
  const health = useServerHealth();
  const style = STATUS_STYLES[health.status];
  const label = STATUS_LABEL[health.status];

  // title 用于 hover 提示：版本、延迟、上次检查时间
  const parts: string[] = [label];
  if (health.status === "ok") {
    if (health.version) parts.push(`v${health.version}`);
    if (health.latencyMs != null) parts.push(`${health.latencyMs}ms`);
  }
  if (health.lastCheck) parts.push(formatAgo(Date.now() - health.lastCheck));
  const title = parts.join(" · ");

  return (
    <span
      className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full font-medium border ${style.container} ${style.text}${className ? ` ${className}` : ""}`}
      title={title}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full shrink-0 ${style.dot}${style.pulse ? " animate-pulse" : ""}`}
      />
      {variant === "full" && <span className="leading-none">{label}</span>}
    </span>
  );
}
