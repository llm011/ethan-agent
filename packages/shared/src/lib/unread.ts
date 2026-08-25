/**
 * 会话未读状态（侧边栏红点）。
 *
 * 后端语义：last_read_at 是未读水位，updated_at > last_read_at 即有未读。
 * 标题/模式等元数据更新由后端保证不制造未读（水位跟随已读态），因此
 * 该比较即「自上次阅读后有无新消息」。秒级时间戳（Python time.time()）。
 */
export interface UnreadLike {
  updated_at?: number;
  last_read_at?: number;
}

export function hasUnread(s: UnreadLike | null | undefined): boolean {
  if (!s) return false;
  return (s.updated_at ?? 0) > (s.last_read_at ?? 0);
}

/** 本地乐观标记已读：水位推进到 updated_at（等价后端 mark_read 的效果）。 */
export function withReadMark<T extends UnreadLike>(s: T): T {
  return { ...s, last_read_at: s.updated_at };
}
