import { useMemo } from "react";
import { fetchPoll } from "@/lib/api";
import {
  useLiveSessions as useLiveSessionsImpl,
  type LiveSessionsDeps,
} from "@ethan/shared/chat/use-live-sessions";

export {
  IDLE_SESSION_REFRESH_EVENT,
  broadcastSessionRefresh,
  collectChangedSessions,
  type LivePollBaseline,
} from "@ethan/shared/chat/use-live-sessions";

/**
 * 薄包装：真正的实现在 @ethan/shared。共享模块取不到本端的 "@/lib/api"，
 * 所以 fetchPoll 由这里注入，两端用同一个 hook。
 */
export function useLiveSessions(): void {
  const deps = useMemo<LiveSessionsDeps>(() => ({ fetchPoll }), []);
  useLiveSessionsImpl(deps);
}
