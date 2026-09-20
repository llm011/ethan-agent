import { useState, useRef, useLayoutEffect, useEffect } from "react";
import { createPortal } from "react-dom";
import type { Message } from "@ethan/shared/chat/types";

interface QueryDotsProps {
  messages: Message[];
  /**
   * 消息列表当前渲染窗口的起始下标。必须与 message-list 渲染 data-msg-idx 用的是
   * 同一个坐标系（那里写的是 startIdx + i）。
   */
  startIdx: number;
  scrollRef: React.RefObject<HTMLDivElement | null>;
  /**
   * 点击的圆点落在尚未渲染的更早一屏时调用：请父组件展开分页让**目标消息**进 DOM，
   * 之后本组件再滚动过去。
   *
   * 入参是目标下标——父组件据此一次展开到位。不要做成「每次只多展开一屏」：
   * 目标可能早好几屏，靠本组件重试几帧是等不到的。
   */
  onNeedOlder?: (targetIdx: number) => void;
  /**
   * 滚动前调用，让父组件把这次滚动标记为「程序触发」——否则会被
   * message-list 的手动滚动监听误判成用户上滑，而解除跟随底部的锁定。
   */
  onBeforeScroll?: () => void;
}

interface TooltipPos {
  top: number;   // viewport 坐标，垂直中心
  left: number;  // viewport 坐标，按钮右边缘
  text: string;
}

export function QueryDots({ messages, startIdx, scrollRef, onNeedOlder, onBeforeScroll }: QueryDotsProps) {
  const [tooltip, setTooltip] = useState<TooltipPos | null>(null);
  // hideTimer：鼠标从按钮移到 tooltip 的 8px 间隙过渡期保留 tooltip
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dotsRef = useRef<HTMLDivElement>(null);
  // 递增令牌，用于作废过期的「等分页展开后滚动」重试链（见 handleClick）
  const clickTokenRef = useRef(0);

  const userMessages = messages
    .map((m, i) => ({ msg: m, idx: i }))
    .filter(({ msg }) => msg.role === "user");

  // 动态 gap：消息多时紧凑
  const gap = userMessages.length > 20 ? 0 : userMessages.length > 10 ? 0.5 : 1;

  const clearHideTimer = () => {
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  };

  const scheduleHide = () => {
    clearHideTimer();
    hideTimerRef.current = setTimeout(() => setTooltip(null), 150);
  };

  useEffect(() => {
    return () => clearHideTimer();
  }, []);

  useLayoutEffect(() => {
    if (!tooltip) return;
    // 滚动时关闭 tooltip，避免位置错位
    const container = scrollRef.current;
    if (!container) return;
    const onScroll = () => setTooltip(null);
    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, [tooltip, scrollRef]);

  if (userMessages.length < 2) return null;

  /**
   * 把某条消息滚进视野。返回是否真的滚了。
   *
   * 用 container.scrollTop 而不是 el.scrollIntoView()：容器是 overflow-y-auto，
   * scrollIntoView 会连带滚动外层祖先（整个页面布局也会被拽），而且滚动是否成功
   * 无从判断。直接算 offsetTop 更可控，也让「没找到目标」变成一个可断言的结果。
   */
  const scrollToMsg = (msgIdx: number): boolean => {
    const container = scrollRef.current;
    if (!container) return false;
    const el = container.querySelector<HTMLElement>(`[data-msg-idx="${msgIdx}"]`);
    if (!el) return false;
    onBeforeScroll?.();
    // offsetTop 相对偏移父级，而消息的直接父级正是这个容器内的 max-w-3xl 包装层，
    // 中间没有别的定位祖先，所以 offsetTop 可直接当作容器内坐标。
    container.scrollTo({ top: Math.max(0, el.offsetTop - 8), behavior: "smooth" });
    return true;
  };

  const handleClick = (msgIdx: number) => {
    // 每次点击领一个新令牌，作废上一次仍在等待的重试链——否则连点两个圆点时，
    // 前一个「等分页展开」的 rAF 链可能在新目标滚到位之后才命中，把视图拽回去。
    clickTokenRef.current += 1;
    const token = clickTokenRef.current;

    if (scrollToMsg(msgIdx)) return;

    // 目标在尚未渲染的更早一屏（首屏只渲染末尾 visibleCount 条）。
    // 这里必须主动展开分页再滚，否则就是「点了没反应、控制台也不报错」。
    if (onNeedOlder && msgIdx < startIdx) {
      onNeedOlder(msgIdx); // 父组件一次展开到目标可见
      // 等展开后 DOM 提交并完成布局再滚。轮询重试而不是固定 sleep，避免消息多时
      // 还没渲染完就去查；查不到就继续等，直到超时。
      //
      // 用 setTimeout 而非 requestAnimationFrame：rAF 在后台标签页会被节流甚至
      // 停摆，用户切走再切回来就会一直等不到；而且 jsdom 里没有帧循环，用 rAF
      // 会让这条重试链在测试中永远不执行（等于没覆盖）。
      let attempts = 0;
      const tryScroll = () => {
        // 已被更晚的点击取代 → 放弃本次重试，别去抢滚动
        if (token !== clickTokenRef.current) return;
        if (scrollToMsg(msgIdx)) return;
        if (++attempts < 20) {
          setTimeout(tryScroll, 50);
        } else {
          console.warn(
            `[QueryDots] 展开分页后仍找不到 data-msg-idx=${msgIdx}（startIdx=${startIdx}）`
          );
        }
      };
      tryScroll();
      return;
    }

    // 走到说明这是个不该出现的 miss，别再静默吞掉——之前就是它让 bug 完全无迹可循。
    console.warn(
      `[QueryDots] 找不到 data-msg-idx=${msgIdx}（startIdx=${startIdx}, ` +
        `onNeedOlder=${onNeedOlder ? "有" : "无"}）`
    );
  };

  const showTooltip = (e: React.MouseEvent<HTMLButtonElement>, text: string) => {
    clearHideTimer();
    const rect = e.currentTarget.getBoundingClientRect();
    setTooltip({
      top: rect.top + rect.height / 2,
      left: rect.right + 8,
      text: text || "(空)",
    });
  };

  return (
    <>
      <div
        ref={dotsRef}
        className="absolute left-0 top-0 bottom-0 w-7 z-20 flex flex-col items-center justify-center pointer-events-none overflow-hidden"
        style={{ gap: `${gap * 4}px` }}
      >
        {userMessages.map(({ msg, idx }) => (
          <button
            key={idx}
            type="button"
            onClick={() => handleClick(idx)}
            onMouseEnter={(e) => showTooltip(e, msg.content)}
            onMouseLeave={scheduleHide}
            className="pointer-events-auto h-4 w-4 flex items-center justify-center cursor-pointer group/btn shrink-0"
          >
            <span className="block h-[7px] w-[7px] rounded-full bg-muted-foreground/50 group-hover/btn:bg-primary group-hover/btn:scale-[1.8] transition-all duration-150" />
          </button>
        ))}
      </div>

      {tooltip && createPortal(
        <div
          className="fixed z-[9999] w-[576px] max-h-64 px-2.5 py-1.5 rounded-lg bg-foreground text-background text-xs leading-snug shadow-lg overflow-y-auto break-words whitespace-normal"
          style={{
            top: tooltip.top,
            left: tooltip.left,
            transform: "translateY(-50%)",
          }}
          onMouseEnter={clearHideTimer}
          onMouseLeave={scheduleHide}
        >
          {tooltip.text}
        </div>,
        document.body,
      )}
    </>
  );
}
