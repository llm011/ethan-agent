"use client";

import { useEffect } from "react";
import { fetchPoll } from "@/lib/api";
import type { SessionInfo } from "@/lib/api";

/**
 * 会话列表「变化」事件名。
 *
 * 由本 hook 广播，ChatView 消费。事件里**不**带「哪条会话变了」之外的信息：
 * 收到的消费方自己去拉一次当前会话的尾部（见 chat-view 的 handleRefreshSession），
 * 而不是指望这里把内容一并送过来。
 */
export const IDLE_SESSION_REFRESH_EVENT = "idle-refresh";

/**
 * 轮询间隔。与 Sidebar 现有轮询同频，但**这两条轮询不能合并**：
 * Sidebar 的轮询会被「正在搜索」和「隐藏标签页」等条件跳过，那对侧边栏是合理的，
 * 对「当前打开的会话要不要跟上新内容」却不行 —— 用户正在搜索框里打字时，
 * 聊天窗口里新追加的一轮照样应该刷上来。所以信号源必须独立于那些条件存在。
 */
const POLL_INTERVAL_MS = 3000;

/** 广播一次「有会话在后台变了」。 */
export function broadcastSessionRefresh(sessionIds: string[]): void {
  if (typeof window === "undefined" || sessionIds.length === 0) return;
  window.dispatchEvent(
    new CustomEvent(IDLE_SESSION_REFRESH_EVENT, { detail: { sessionIds } })
  );
}

/** 上一次轮询的观测结果，用来和本轮比对。 */
export interface LivePollBaseline {
  updatedAt: Map<string, number>;
}

/**
 * 比对「本次 / 上一次」的 /poll 结果，返回更新时间前进了的会话 id。
 *
 * 纯函数、就地更新 baseline，便于单测覆盖 —— 这层判定是整个自动刷新功能的正确性核心：
 * 判错只会表现为「该刷的不刷」或「一直白刷」，都不会报错，所以必须有测试钉住。
 *
 * 判据只有 `updated_at` 一条，这是**实测**后的结论，不是随手选的：
 *
 * - /poll 另有一个 `active_sessions`（服务端 RunManager 里「还在产出」的会话集合）
 *   看起来更适合当「这一轮跑完了」的信号，但它对本场景没有用 —— 后端在把正文写进库
 *   的那一刻就把该标志翻掉了（见 run_manager.create/_touch_session_soon 的说明），
 *   实测为真的窗口只有毫秒级，3s 一轮的轮询基本抓不到。既然只有 updated_at 这一个
 *   可靠观测，就只用它，别为「看起来更语义化」的标志位留一条永远不触发的分支。
 * - 后端为此在**每一轮开始时**也推了一次 updated_at（原先只有结束时推）。否则
 *   「刚开始」和「已结束」对客户端是同一个观测，一整轮跑完前界面都不知道有事在发生。
 *
 * 所以「updated_at 前进」同时覆盖了「别处又追加了一轮」和「这一轮跑完了、内容已落库」
 * 两种时刻 —— 而每次广播后调用方都会去拉一页尾部核对内容，多刷一次的代价只是
 * 一次廉价 GET，漏刷的代价则是用户盯着 stale 的界面。
 */
export function collectChangedSessions(
  baseline: LivePollBaseline,
  sessions: { id: string; updated_at: number }[]
): string[] {
  const changed: string[] = [];
  for (const s of sessions) {
    const before = baseline.updatedAt.get(s.id);
    // 没见过的新会话、或更新时间前进了，都算变化。
    if (before === undefined || s.updated_at !== before) changed.push(s.id);
    baseline.updatedAt.set(s.id, s.updated_at);
  }

  // 清理已经不在列表里的会话，避免 Map 随运行时长无限增长。
  if (baseline.updatedAt.size > sessions.length * 2 + 64) {
    const live = new Set(sessions.map((s) => s.id));
    for (const id of Array.from(baseline.updatedAt.keys())) {
      if (!live.has(id)) baseline.updatedAt.delete(id);
    }
  }
  return changed;
}

/**
 * 监听后台发生的会话变化，广播 { sessionIds }，由消费方决定是否刷新。
 *
 * 为什么要有这个 hook：会话内容变化本来只会在两种情况下被前端发现 —— 要么本窗口
 * 正开着 SSE 流（实时推送，见 use-chat-stream），要么用户手动切会话/刷新页面。
 * 于是「这条会话已经跑完、但别处（定时任务、另一个窗口、CLI、渠道）又追加了一轮」
 * 这类变化，在本窗口里**永远不会自己浮现**：界面上一直停在上次打开时的样子，
 * 直到用户碰它一下才发现内容早就变了。
 *
 * 信号取 /poll 的 sessions[].updated_at（每轮开始与结束各推一次，见后端
 * run_manager.create 的说明），规则见 collectChangedSessions。
 *
 * 刻意**不**维护「我打开的这条会话上次的 updated_at」那种精确基线：这里的列表是
 * 隐藏了心跳会话前缀的**过滤切片**（定时会话保留，见 tick 里 fetchPoll 的说明），
 * 而消费方那侧可能正开着一条被过滤掉的会话。两边口径一旦不一致，基线就会永久地
 * 一边刷个不停、一边永远不刷。只比「本次与上一次」的相对变化，则与过滤口径完全无关。
 */
export function useLiveSessions(): void {
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    const baseline: LivePollBaseline = { updatedAt: new Map() };
    let primed = false;

    const tick = async () => {
      // 隐藏标签页不轮询：用户看不见，刷新纯属浪费；重新可见那一刻会立刻补一次。
      if (document.hidden) return;
      let data;
      try {
        // hideHeartbeat=true：心跳会话是纯内部噪声，用户不会打开，滤掉省带宽。
        // hideScheduled=false：**定时会话必须留下**——本功能最初就是盯着一个定时任务
        // 会话发现「跑完后别处又追加一轮不刷新」的，若把 [定时] 前缀滤掉（后端 chat.py:151），
        // 那条会话的 updated_at 变化永远不会进入比对，它自己反而刷不上来。
        data = await fetchPoll(true, false);
      } catch {
        // 网络/后端暂时不可用：保留上一次的基线，下一轮再比。
        return;
      }
      const sessions = (data.sessions || []) as SessionInfo[];

      // 第一次只用来建立基线（此时基线全空，比出来的「变化」全是假变化）。
      if (!primed) {
        primed = true;
        collectChangedSessions(baseline, sessions);
        return;
      }

      broadcastSessionRefresh(collectChangedSessions(baseline, sessions));
    };

    const start = () => {
      if (!timer) timer = setInterval(tick, POLL_INTERVAL_MS);
    };
    const stop = () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };
    // 回到前台立刻补一次：否则用户切回来以后要空等一个轮询间隔才看到新内容。
    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        void tick();
        start();
      }
    };

    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);
}
