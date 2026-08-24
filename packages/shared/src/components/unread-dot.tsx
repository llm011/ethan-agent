/** 未读红点：侧边栏会话行 / 全部会话卡片共用。 */
export function UnreadDot({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-block h-2 w-2 shrink-0 rounded-full bg-red-500 ${className}`}
      title="有未读消息"
      aria-label="有未读消息"
    />
  );
}
