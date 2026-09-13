"use client";

/**
 * 记忆页列表的两条交互（Web + Desktop 共用）：
 * - 双击 tab 回到顶部
 * - 滚到底自动加载下一页
 *
 * 放在 @ethan/shared 是为了两端行为一致 —— 这类「手势 + 滚动」的细节很容易
 * 各写一版然后慢慢漂移（一处 300ms、一处 250ms，一处提前 2 条、一处提前 10 条）。
 */

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

/**
 * 双击判定窗口（毫秒）。
 *
 * 与浏览器原生 dblclick 的口径对齐（各平台大致 300-500ms，取偏紧的 300）。
 * 代价是单击切换 tab 要等这个窗口过去才生效 —— 与 Android 端 `detectTapGestures`
 * 的 ~300ms 行为一致，两端手感相同。
 */
const DOUBLE_TAP_MS = 300;

/**
 * 让 tab 同时支持「单击切换」和「双击回顶」。
 *
 * 原生 `onDoubleClick` 不够用：dblclick 一定在 click 之后触发，而 click 已经
 * 把 tab 切走了。所以这里自己做计时 —— 单击延迟到窗口结束才切，双击则
 * 「切到该 tab + 回顶」一次做完，不会切两次 tab。
 *
 * @param onSwitch    单击：切到该 tab
 * @param onDoubleTap 双击：切到该 tab 并回到顶部
 */
export function useDoubleTapTab<T extends string>(
  onSwitch: (key: T) => void,
  onDoubleTap: (key: T) => void,
): (key: T) => void {
  const lastTap = useRef<Partial<Record<T, number>>>({});
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 卸载时清掉待触发的单击，否则切页后定时器还会去 setState
  useEffect(() => () => {
    if (pending.current) clearTimeout(pending.current);
  }, []);

  return useCallback((key: T) => {
    const now = Date.now();
    const prev = lastTap.current[key] ?? 0;
    if (now - prev < DOUBLE_TAP_MS) {
      // 双击：取消待触发的单击，直接「切过去 + 回顶」
      lastTap.current[key] = 0;
      if (pending.current) {
        clearTimeout(pending.current);
        pending.current = null;
      }
      onDoubleTap(key);
      return;
    }
    lastTap.current[key] = now;
    if (pending.current) clearTimeout(pending.current);
    pending.current = setTimeout(() => {
      pending.current = null;
      onSwitch(key);
    }, DOUBLE_TAP_MS);
  }, [onSwitch, onDoubleTap]);
}

/** 滚到容器顶部。`behavior: "smooth"` 与双击手势的手感匹配（不是瞬移）。 */
export function scrollContainerToTop(el: HTMLElement | null): void {
  if (!el) return;
  el.scrollTo({ top: 0, behavior: "smooth" });
}

/**
 * 滚到接近底部时触发加载下一页。
 *
 * 用 IntersectionObserver 而不是监听 `scroll` 事件：不必每帧读 `scrollHeight`
 * 触发同步布局，且元素一进入视野就触发，天然就是「快到尾部」的判定。
 *
 * @param hasMore  还有没有下一页；false 时不挂观察
 * @param loading  请求中不重复触发
 * @param onLoadMore 触发回调
 * @returns 哨兵元素的 ref，挂在列表**末尾**
 */
export function useLoadMoreOnReachEnd(
  hasMore: boolean,
  loading: boolean,
  onLoadMore: () => void,
): RefObject<HTMLDivElement | null> {
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  // 用 ref 存回调：否则 onLoadMore 每次渲染换新引用会把 observer 反复拆了重挂
  const cb = useRef(onLoadMore);
  cb.current = onLoadMore;

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !hasMore || loading) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) cb.current();
      },
      // root 用视口即可：哨兵在 ScrollArea 内部，可见性判断已经相对其滚动容器
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasMore, loading]);

  return sentinelRef;
}

/** 记录某个 tab 是否已经加载过首页，避免来回切 tab 反复请求。 */
export function useLoadedTabs<T extends string>(): {
  markLoaded: (key: T) => void;
  hasLoaded: (key: T) => boolean;
  reset: (key: T) => void;
} {
  const loaded = useRef(new Set<T>());
  const [, force] = useState(0);
  return {
    markLoaded: useCallback((key: T) => {
      if (!loaded.current.has(key)) {
        loaded.current.add(key);
        force((n) => n + 1);
      }
    }, []),
    hasLoaded: useCallback((key: T) => loaded.current.has(key), []),
    reset: useCallback((key: T) => {
      loaded.current.delete(key);
    }, []),
  };
}
